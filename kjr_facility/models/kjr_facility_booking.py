# -*- coding: utf-8 -*-
"""Einrichtungsbuchung mit Workflow, Preis-/Steuerberechnung und Rechnungsstellung."""
import base64
import logging
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from markupsafe import Markup, escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# ── DSGVO: Aufbewahrung / Anonymisierung (Befund K5, Audit vom 21.08.2026) ───
# Aufbau und Begründungsstil bewusst übernommen von kjr_grant
# (kjr.grant.participant._cron_anonymize_expired und die Nebenschauplätze in
# kjr_grant_application.py), damit beide Module gleich zu prüfen und zu pflegen
# sind. Eine Modulabhängigkeit zu kjr_grant besteht nicht und soll nicht
# entstehen — die wenigen Helfer sind deshalb bewusst dupliziert.
#
# WICHTIG: Für Einrichtungsbuchungen ist KEINE Aufbewahrungsfrist entschieden.
# Beide Parameter sind im Auslieferungszustand NICHT gesetzt; der Code liest dann
# '0', und '0' bedeutet: es passiert GAR NICHTS. Erst ein vom KJR eingetragener
# Wert > 0 schaltet die Verarbeitung ein.
#
# Anhaltspunkte aus dem Projektvault — ausschließlich Entscheidungshilfe für den
# KJR, bewusst NICHT als Default gesetzt und hier ausdrücklich keine Rechtsaussage:
#   • Buchungsbelege: 8 Jahre (§ 147 AO, § 257 HGB)
#   • Verwendungsnachweise: 5 Jahre (ANBest-P Nr. 6.6)
#   • "1 Jahr Ferienprogramm" ist eine selbstdefinierte Policy des KJR und
#     ausdrücklich keine gesetzliche Frist.
# TODO(KJR): Frist festlegen und KJR_FACILITY_RETENTION_PARAM setzen.
# TODO(DSGVO): Festlegung und Verfahren von der Datenschutzbeauftragten
# bestätigen lassen, insbesondere den Umgang mit Chatter und Feldhistorie.
KJR_FACILITY_RETENTION_PARAM = 'kjr_facility.booking_retention_years'
KJR_FACILITY_TRACES_PARAM = 'kjr_facility.booking_anonymize_traces'

# Platzhalter und Idempotenz-Marker (Schreibweise wie in kjr_grant).
# ir.attachment.description ist ein freies Textfeld; ein eigenes Feld auf
# ir.attachment wird bewusst nicht angelegt (Fremdmodell).
DSGVO_REDACTED = '(anonymisiert)'
DSGVO_ANON_MARKER = '[DSGVO-anonymisiert]'


class KjrFacilityBooking(models.Model):
    _name = 'kjr.facility.booking'
    _description = 'KJR Einrichtungsbuchung'
    _order = 'check_in desc, name desc'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']

    name = fields.Char(
        string='Buchungsnummer', required=True, copy=False, readonly=True,
        default=lambda self: _('Neu'), tracking=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Gesellschaft', required=True, index=True,
        default=lambda self: self.env.company,
    )
    state = fields.Selection([
        ('draft', 'Anfrage'),
        ('reserved', 'Reserviert (vorgemerkt)'),
        ('confirmed', 'Gebucht'),
        ('deposit', 'Anzahlung'),
        ('checked_in', 'Angereist'),
        ('invoiced', 'Berechnet'),
        ('done', 'Abgeschlossen'),
        ('cancelled', 'Storniert'),
    ], string='Status', default='draft', required=True, tracking=True, index=True)
    # F1: Reservierung (vorgemerkt) klar von verbindlicher Buchung (gebucht) trennen.
    reservation_date = fields.Date(string='Reserviert am', tracking=True)
    reservation_expiry = fields.Date(
        string='Reservierung gültig bis', tracking=True,
        help='Ablaufdatum der Vormerkung. Nach Ablauf erfolgt ein Hinweis per Cron.')
    is_booked = fields.Boolean(
        string='Verbindlich gebucht', compute='_compute_is_booked', store=True,
        help='Wahr, sobald die Buchung verbindlich (gebucht) oder weiter fortgeschritten ist.')

    facility_id = fields.Many2one(
        'kjr.facility', string='Einrichtung', required=True,
        ondelete='restrict', tracking=True,
    )
    color = fields.Integer(related='facility_id.color', store=True)
    # F1: Kalenderfarbe — reservierte (vorgemerkte) Buchungen heller/neutral darstellen.
    calendar_color = fields.Integer(
        string='Kalenderfarbe (Status)', compute='_compute_calendar_color', store=True)
    partner_id = fields.Many2one(
        'res.partner', string='Gruppe / Mieter', required=True,
        ondelete='restrict', tracking=True,
    )
    group_name = fields.Char(string='Gruppenbezeichnung')
    # F2: Bisher gab es nur die Betreuerzahl sowie E-Mail/Telefon, aber keinen Namen
    # der verantwortlichen Ansprechperson — im Website-Termin bemängelt.
    contact_person = fields.Char(
        string='Ansprechpartner/in',
        help='Name der verantwortlichen Ansprechperson der Gruppe (Anmeldung, Rückfragen, '
             'Schlüsselübergabe).')
    contact_email = fields.Char(string='E-Mail')
    contact_phone = fields.Char(string='Telefon')

    # ── Zeitraum ─────────────────────────────────────────────────────────────
    check_in = fields.Date(string='Anreise', required=True, tracking=True)
    check_out = fields.Date(string='Abreise', required=True, tracking=True)
    nights = fields.Integer(string='Nächte', compute='_compute_nights', store=True)

    # ── Belegung ─────────────────────────────────────────────────────────────
    participant_count = fields.Integer(string='Teilnehmer', default=0, tracking=True)
    leader_count = fields.Integer(string='Betreuer', default=0)
    supervision_ok = fields.Boolean(string='Betreuung ausreichend', compute='_compute_supervision')
    # F2: Belegungsregeln der Einrichtung (Mindestbelegung/-aufenthalt, Zielgruppe).
    is_organized_group = fields.Boolean(
        string='Organisierte Jugend-/Bildungsgruppe',
        help='Ankreuzen, wenn die Gruppe ein anerkannter Träger der Jugendarbeit, eine Schule '
             'oder eine vergleichbare Bildungseinrichtung ist. Einige Einrichtungen dürfen nur '
             'an solche Gruppen vergeben werden.')
    occupancy_warning = fields.Char(
        string='Hinweis Belegungs-/Vorlaufregeln', compute='_compute_occupancy_warning',
        help='Weicher Hinweis (kein harter Constraint) auf Mindestbelegung, '
             'Mindestaufenthalt, Zielgruppe und Buchungsvorlauf: Die Geschäftsstelle darf '
             'abweichende Buchungen im Backend bewusst erfassen. Hart durchgesetzt werden '
             'diese Regeln nur im Website-Anfrageformular.')
    visitor_tax_exempt_count = fields.Integer(
        string='Zusätzlich vom Fremdenverkehrsbeitrag befreit', default=0,
        help='Anzahl der TEILNEHMENDEN, für die zusätzlich kein Fremdenverkehrsbeitrag '
             'anfällt: Einwohnerinnen und Einwohner der Standortgemeinde, Kinder unter '
             '7 Jahren sowie Schwerbehinderte. ACHTUNG: Betreuerinnen und Betreuer '
             '(Feld „Betreuer") sind nach der Satzungslage ohnehin befreit und gehen '
             'gar nicht erst in die Berechnung ein — sie dürfen hier NICHT noch einmal '
             'eingetragen werden, sonst wird doppelt abgezogen. '
             'Beitragspflichtig sind: Teilnehmer − dieser Wert.')
    room_ids = fields.Many2many(
        'kjr.facility.room', 'kjr_booking_room_rel', 'booking_id', 'room_id',
        string='Räume',
    )
    bed_count = fields.Integer(string='Betten gebucht', compute='_compute_bed_count')

    # ── Leistungen ───────────────────────────────────────────────────────────
    tariff_id = fields.Many2one('kjr.facility.tariff', string='Tarif', tracking=True)
    meal_option = fields.Selection([
        ('none', 'Selbstverpflegung'),
        ('breakfast', 'Frühstück'),
        ('half', 'Halbpension'),
        ('full', 'Vollpension'),
    ], string='Verpflegung', default='none', required=True)
    equipment_ids = fields.Many2many(
        'kjr.facility.equipment', 'kjr_booking_equipment_rel', 'booking_id', 'equipment_id',
        string='Zusatzausstattung',
    )
    equipment_notes = fields.Text(string='Anmerkungen Ausstattung')

    # ── Förderbezug (entkoppelt von kjr_grant) ───────────────────────────────
    is_grant_funded = fields.Boolean(string='Gefördert (Zuschuss)')
    grant_reference = fields.Char(
        string='Zuschuss-Aktenzeichen', groups='kjr_facility.group_kjr_facility_user')

    # ── Beträge ──────────────────────────────────────────────────────────────
    currency_id = fields.Many2one(related='company_id.currency_id')
    amount_accommodation = fields.Monetary(string='Unterkunft', compute='_compute_amounts', store=True)
    amount_meals = fields.Monetary(string='Verpflegung (Betrag)', compute='_compute_amounts', store=True)
    amount_equipment = fields.Monetary(string='Ausstattung', compute='_compute_amounts', store=True)
    # F2: Fremdenverkehrsbeitrag (pro Person und Nacht) und einmalige Endreinigung.
    amount_visitor_tax = fields.Monetary(
        string='Fremdenverkehrsbeitrag', compute='_compute_amounts', store=True)
    amount_cleaning = fields.Monetary(
        string='Endreinigung', compute='_compute_amounts', store=True)
    amount_untaxed = fields.Monetary(string='Netto', compute='_compute_amounts', store=True)
    amount_tax = fields.Monetary(string='USt', compute='_compute_amounts', store=True)
    amount_total = fields.Monetary(string='Gesamt (brutto)', compute='_compute_amounts', store=True)
    deposit_pct = fields.Float(string='Anzahlung (%)', default=20.0)
    deposit_amount = fields.Monetary(string='Anzahlungsbetrag', compute='_compute_deposit', store=True)
    deposit_paid = fields.Boolean(string='Anzahlung erhalten', tracking=True)
    # F5: Anzahlungs-Fälligkeit für den Overdue-Cron.
    deposit_due_date = fields.Date(string='Anzahlung fällig bis', tracking=True)

    # F5: Vertrags-Nachverfolgung (gesendet / unterschrieben).
    contract_sent_date = fields.Date(string='Vertrag gesendet am', readonly=True, copy=False, tracking=True)
    contract_signed = fields.Boolean(string='Vertrag unterschrieben', tracking=True)

    # F5: Persistente Versand-Flags — verhindern, dass die Erinnerungs-/Mahn-Mails
    # bei jedem Cron-Lauf erneut versendet werden (Activity-Dedup allein reicht nicht,
    # da erledigte Activities aus activity_ids verschwinden, die Bedingung aber bleibt).
    reminder_sent = fields.Boolean(string='Anreise-Erinnerung versendet', default=False, copy=False)
    contract_followup_sent = fields.Boolean(string='Vertrags-Mahnung versendet', default=False, copy=False)
    deposit_reminder_sent = fields.Boolean(string='Anzahlungs-Mahnung versendet', default=False, copy=False)

    # F7: An-/Abreisezeiten je Buchung (Default aus Einrichtungs-Stammdaten).
    arrival_time = fields.Float(string='Anreisezeit', help='Uhrzeit der Anreise (HH:MM).')
    departure_time = fields.Float(string='Abreisezeit', help='Uhrzeit der Abreise (HH:MM).')

    invoice_id = fields.Many2one('account.move', string='Rechnung', readonly=True, copy=False)
    # B-cross: Zahlungsstatus aus der Rechnung gespiegelt (für Form/Liste/Portal).
    payment_status = fields.Selection([
        ('none', 'Keine Rechnung'),
        ('not_paid', 'Offen'),
        ('in_payment', 'In Zahlung'),
        ('partial', 'Teilweise bezahlt'),
        ('paid', 'Bezahlt'),
        ('reversed', 'Storniert'),
    ], string='Zahlungsstatus', compute='_compute_payment_status', store=True)
    note = fields.Text(string='Anmerkungen')
    internal_note = fields.Text(
        string='Interne Notiz', groups='kjr_facility.group_kjr_facility_user',
        help='Nur für Mitarbeiter sichtbar (nicht im Portal).')

    # DSGVO: Merker für die Anonymisierung nach Ablauf der Aufbewahrungsfrist
    # (siehe _cron_anonymize_expired). Gleiches Muster wie kjr.grant.participant:
    # der Merker macht den Lauf idempotent, damit ein zweiter Cron-Durchlauf einen
    # bereits anonymisierten Vorgang nicht erneut anfasst.
    data_anonymized = fields.Boolean(
        string='Anonymisiert (DSGVO)', default=False, readonly=True, copy=False,
        help='Die personenbezogenen Angaben dieser Buchung (Ansprechperson, E-Mail, '
             'Telefon, Gruppenbezeichnung, Freitexte und die Namen im Übergabe- bzw. '
             'Rücknahmeprotokoll) wurden nach Ablauf der Aufbewahrungsfrist maschinell '
             'geleert. Zeitraum, Personenzahlen und Beträge bleiben für Auswertung und '
             'Abrechnung erhalten.',
    )

    # ── Übergabeprotokoll (F: Haus/Zeltplatz, beide Richtungen) ──────────────
    #
    # Übergabe und Schadensfeststellung liefen bisher auf Papier und waren am
    # Vorgang nicht auffindbar. Fachliche Leitplanke (übernommen aus dem
    # Rückgabeprotokoll in kjr_rental, siehe _check_handover_protocol): Das
    # Protokoll dokumentiert den ZUSTAND, es ist KEINE Freigabebedingung. Ein
    # Mangel darf den Abschluss der Buchung nicht verhindern — er verlangt nur
    # einen Vermerk. Andernfalls kreuzt das Personal wahrheitswidrig „in Ordnung"
    # an und das Protokoll verliert genau den Nachweiswert, für den es gebaut wird.
    #
    # Zählerstände sind bewusst freie Zahlenfelder ohne Vorbelegung und ohne
    # Verbrauchs-/Preislogik.
    # TODO(KJR): Ob und wie Mehrverbrauch (Strom/Wasser/Gas) abgerechnet wird, ist
    # nicht entschieden. Es gibt dafür weder einen belegten Arbeitspreis noch eine
    # belegte Freimenge, deshalb wird hier ausschließlich dokumentiert.

    _HANDOVER_CONDITIONS = [
        ('ok', 'Ordnungsgemäß'),
        ('minor', 'Kleinere Mängel'),
        ('major', 'Erhebliche Mängel'),
    ]

    # ── Anreise: Übergabe an die Gruppe ──────────────────────────────────────
    handover_in_date = fields.Date(
        string='Übergabe am (Anreise)', tracking=True, copy=False,
        help='Tag der Übergabe an die Gruppe. Wird beim Erfassen des Anreiseprotokolls '
             'automatisch auf heute gesetzt, falls leer, und kann nachgetragen werden.')
    handover_in_user_id = fields.Many2one(
        'res.users', string='Übergeben durch (KJR)', copy=False,
        help='Person der Geschäftsstelle/Hausbetreuung, die das Haus bzw. den Zeltplatz '
             'übergeben hat.')
    handover_in_received_by = fields.Char(
        string='Übernommen durch (Gruppe)', copy=False,
        help='Name der Person der Gruppe, die das Objekt übernommen hat (in der Regel die '
             'verantwortliche Ansprechperson).')
    handover_in_condition = fields.Selection(
        _HANDOVER_CONDITIONS, string='Zustand bei Übergabe', tracking=True, copy=False,
        help='Festgestellter Zustand bei der Übergabe an die Gruppe. Leer = noch nicht '
             'erfasst. Der Eintrag dokumentiert den Zustand und verhindert nichts; '
             'Mängel verlangen nur einen Vermerk.')
    handover_in_keys = fields.Integer(
        string='Schlüssel übergeben (Anzahl)', default=0, copy=False,
        help='Anzahl der bei der Anreise ausgehändigten Schlüssel/Transponder. 0 = nicht '
             'erfasst oder keine Schlüsselübergabe.')
    handover_in_meter_electricity = fields.Float(
        string='Zählerstand Strom Anreise (kWh)', digits=(12, 2), copy=False,
        help='Ablesewert bei der Übergabe. Reine Dokumentation, es wird nichts daraus '
             'berechnet (siehe TODO(KJR) zur Verbrauchsabrechnung).')
    handover_in_meter_water = fields.Float(
        string='Zählerstand Wasser Anreise (m³)', digits=(12, 2), copy=False,
        help='Ablesewert bei der Übergabe. Reine Dokumentation.')
    handover_in_meter_gas = fields.Float(
        string='Zählerstand Gas/Heizung Anreise', digits=(12, 2), copy=False,
        help='Ablesewert bei der Übergabe (Einheit je nach Zähler: m³ oder kWh). '
             'Reine Dokumentation.')
    handover_in_damage = fields.Boolean(
        string='Schaden festgestellt (Anreise)', tracking=True, copy=False,
        help='Bei der Übergabe wurde ein Schaden oder Mangel festgestellt — z. B. ein '
             'Vorschaden, den die Gruppe nicht zu vertreten hat. Dann ist die '
             'Schadensbeschreibung Pflicht.')
    handover_in_damage_note = fields.Text(
        string='Schadensbeschreibung (Anreise)', copy=False,
        help='Was genau ist beschädigt oder mangelhaft? Pflicht, sobald „Schaden '
             'festgestellt (Anreise)" gesetzt ist. Bitte das Kennzeichen NICHT '
             'wahrheitswidrig entfernen, um die Erfassung abzukürzen.')
    handover_in_note = fields.Text(
        string='Vermerk (Anreise)', copy=False,
        help='Freitext zur Übergabe: Einweisung, Absprachen, Besonderheiten, fehlende '
             'Ausstattung.')

    # ── Abreise: Rücknahme von der Gruppe ────────────────────────────────────
    handover_out_date = fields.Date(
        string='Rücknahme am (Abreise)', tracking=True, copy=False,
        help='Tag der Rücknahme von der Gruppe. Wird beim Erfassen des Abreiseprotokolls '
             'automatisch auf heute gesetzt, falls leer.')
    handover_out_user_id = fields.Many2one(
        'res.users', string='Zurückgenommen durch (KJR)', copy=False,
        help='Person der Geschäftsstelle/Hausbetreuung, die das Objekt zurückgenommen hat.')
    handover_out_handed_by = fields.Char(
        string='Übergeben durch (Gruppe)', copy=False,
        help='Name der Person der Gruppe, die das Objekt zurückgegeben hat.')
    handover_out_condition = fields.Selection(
        _HANDOVER_CONDITIONS, string='Zustand bei Rücknahme', tracking=True, copy=False,
        help='Festgestellter Zustand bei der Rücknahme. Leer = noch nicht erfasst. '
             'Auch „Erhebliche Mängel" hindert den Abschluss der Buchung nicht — es '
             'verlangt einen Vermerk.')
    handover_out_keys = fields.Integer(
        string='Schlüssel zurück (Anzahl)', default=0, copy=False,
        help='Anzahl der bei der Abreise zurückgegebenen Schlüssel/Transponder. Weicht die '
             'Zahl von der Ausgabe ab, bitte im Vermerk festhalten.')
    handover_out_cleaning_ok = fields.Boolean(
        string='Gereinigt übergeben', copy=False,
        help='Das Objekt wurde im vereinbarten Reinigungszustand zurückgegeben. Das '
             'Häkchen dokumentiert nur den Zustand; bleibt es leer, ist die Rücknahme '
             'trotzdem abschließbar — dann bitte mit Vermerk. Unabhängig davon werden '
             'die Räume der Buchung beim Abschluss auf „Zu reinigen" gesetzt.')
    handover_out_meter_electricity = fields.Float(
        string='Zählerstand Strom Abreise (kWh)', digits=(12, 2), copy=False,
        help='Ablesewert bei der Rücknahme. Reine Dokumentation.')
    handover_out_meter_water = fields.Float(
        string='Zählerstand Wasser Abreise (m³)', digits=(12, 2), copy=False,
        help='Ablesewert bei der Rücknahme. Reine Dokumentation.')
    handover_out_meter_gas = fields.Float(
        string='Zählerstand Gas/Heizung Abreise', digits=(12, 2), copy=False,
        help='Ablesewert bei der Rücknahme (Einheit je nach Zähler). Reine Dokumentation.')
    handover_out_damage = fields.Boolean(
        string='Schaden festgestellt (Abreise)', tracking=True, copy=False,
        help='Bei der Rücknahme wurde ein Schaden oder Verlust festgestellt. Dann ist die '
             'Schadensbeschreibung Pflicht. Ob daraus eine Forderung entsteht, entscheidet '
             'die Geschäftsstelle — automatisch passiert nichts.')
    handover_out_damage_note = fields.Text(
        string='Schadensbeschreibung (Abreise)', copy=False,
        help='Was genau ist beschädigt, fehlt oder wurde vereinbart? Pflicht, sobald '
             '„Schaden festgestellt (Abreise)" gesetzt ist. Der Text ist die dokumentierte '
             'Feststellung und zugleich die Begründung für eine mögliche Nachbelastung.')
    handover_out_note = fields.Text(
        string='Vermerk (Abreise)', copy=False,
        help='Freitext zur Rücknahme: Reinigungszustand, Absprachen, offene Punkte, '
             'abweichende Schlüsselzahl.')

    # ══════════════════════════════════════════════════════════════════════════
    # COMPUTED
    # ══════════════════════════════════════════════════════════════════════════

    @api.depends('check_in', 'check_out')
    def _compute_nights(self):
        for rec in self:
            if rec.check_in and rec.check_out and rec.check_out > rec.check_in:
                rec.nights = (rec.check_out - rec.check_in).days
            else:
                rec.nights = 0

    @api.depends('participant_count', 'leader_count', 'facility_id.supervision_ratio')
    def _compute_supervision(self):
        for rec in self:
            ratio = rec.facility_id.supervision_ratio or 0
            if not rec.participant_count:
                rec.supervision_ok = True
            elif ratio <= 0:
                rec.supervision_ok = True
            else:
                rec.supervision_ok = (rec.leader_count * ratio) >= rec.participant_count

    @api.depends('room_ids.capacity')
    def _compute_bed_count(self):
        for rec in self:
            rec.bed_count = sum(rec.room_ids.mapped('capacity'))

    @api.model
    def _stay_is_weekday_only(self, check_in, check_out):
        """F2: Prüft, ob der gesamte Aufenthalt in die Woche (Mo–Fr) fällt.

        Fachliche Regel laut Geschäftsstelle ("Wochenendtarif nur, wenn wirklich keine
        Wochenendnacht dabei ist, mind. 4 Nächte unter der Woche"):

        * Übernachtet wird in den Nächten check_in .. check_out - 1 Tag.
        * Eine Nacht gilt als Wochenendnacht, wenn sie an einem Freitag, Samstag oder
          Sonntag BEGINNT (Fr->Sa, Sa->So, So->Mo).
        * Der Aufenthalt ist also genau dann reiner Wochentagsaufenthalt, wenn jede
          Nacht an einem Montag bis Donnerstag beginnt. Daraus folgt automatisch:
          Anreise Mo–Do, Abreise spätestens Fr derselben Woche, maximal 4 Nächte
          (Mo, Di, Mi, Do) — mehr Wochentagsnächte gibt es am Stück nicht.

        Die Mindestnächte-Bedingung (tariff_id.weekday_min_nights) wird bewusst NICHT
        hier geprüft, damit die Kalenderregel getrennt testbar bleibt.

        :return: True, wenn keine Wochenendnacht im Zeitraum liegt.
        """
        if not check_in or not check_out or check_out <= check_in:
            return False
        night = check_in
        while night < check_out:
            if night.weekday() > 3:  # 0=Mo … 3=Do sind Wochentagsnächte
                return False
            night += timedelta(days=1)
        return True

    def _uses_weekday_rate(self):
        """F2: Gilt für diese Buchung der Mo–Fr-Sondertarif?

        Der günstigere Mo–Fr-Satz greift nur, wenn ALLE drei Bedingungen erfüllt sind:
        gepflegter Wochentagspreis > 0, reiner Mo–Fr-Aufenthalt (siehe
        :meth:`_stay_is_weekday_only`) und mindestens ``weekday_min_nights`` Nächte.
        """
        self.ensure_one()
        t = self.tariff_id
        if not t or (t.weekday_price_per_person_night or 0.0) <= 0.0:
            return False
        return ((self.nights or 0) >= (t.weekday_min_nights or 0)
                and self._stay_is_weekday_only(self.check_in, self.check_out))

    def _accommodation_rate_per_person_night(self):
        """F2: Liefert den anzuwendenden Personen-Nachtpreis (Regel- oder Mo–Fr-Tarif)."""
        self.ensure_one()
        t = self.tariff_id
        if not t:
            return 0.0
        if self._uses_weekday_rate():
            return t.weekday_price_per_person_night or 0.0
        return t.price_per_person_night or 0.0

    # ── Fremdenverkehrsbeitrag: Bemessung und steuerliche Behandlung ─────────
    #
    # TODO(Steuer): Der Fremdenverkehrsbeitrag wird DERZEIT als DURCHLAUFENDER
    # POSTEN behandelt, d. h. ohne Umsatzsteuer gerechnet und ohne Steuerschlüssel
    # auf die Rechnung gestellt. Grundlage ist die Zusage auf der Website ("Den
    # Beitrag führen wir an die Gemeinde ab") — für eine an die Standortgemeinde
    # abzuführende kommunale Abgabe ist das die konservative Annahme. Die endgültige
    # steuerliche Einordnung ist laut Projektunterlagen noch mit dem Steuerbüro zu
    # klären.
    #
    # UMSTELLUNG auf die steuerpflichtige Variante: ``_visitor_tax_pass_through``
    # auf False setzen (bzw. im Kundenmodul überschreiben). Dann läuft der Beitrag
    # mit dem Steuersatz des Tarifs (tariff_id.tax_id) sowohl in die Summenfelder
    # als auch in die Rechnungsposition. Weitere Anpassungen sind nicht nötig:
    # Berechnung und Rechnungserzeugung lesen beide _visitor_tax_taxes().
    _visitor_tax_pass_through = True

    def _visitor_tax_taxes(self):
        """Steuerschlüssel der Position „Fremdenverkehrsbeitrag“.

        Leeres Recordset = durchlaufender Posten (kein Steuerausweis).
        Siehe TODO(Steuer) oben.
        """
        self.ensure_one()
        if self._visitor_tax_pass_through:
            return self.env['account.tax']
        return self.tariff_id.tax_id if self.tariff_id else self.env['account.tax']

    def _visitor_tax_person_count(self):
        """Anzahl der beitragspflichtigen Personen (Bemessungsgrundlage).

        Nach der Immenstädter Satzungslage sind Betreuende und Begleitpersonen vom
        Fremdenverkehrsbeitrag BEFREIT; sie gehen deshalb gar nicht erst in die
        Grundmenge ein (``leader_count`` wird bewusst nicht addiert).
        ``visitor_tax_exempt_count`` erfasst ausschließlich ZUSÄTZLICH befreite
        Teilnehmende (Einwohner der Standortgemeinde, Kinder unter 7 Jahren,
        Schwerbehinderte) — Betreuende dort erneut einzutragen wäre ein doppelter
        Abzug (siehe Hilfetext des Feldes). Das Ergebnis wird nie negativ.
        """
        self.ensure_one()
        return max(0, (self.participant_count or 0) - (self.visitor_tax_exempt_count or 0))

    @api.depends(
        'nights', 'check_in', 'check_out', 'participant_count',
        'visitor_tax_exempt_count', 'meal_option', 'tariff_id',
        'tariff_id.price_per_person_night', 'tariff_id.price_flat_per_night',
        'tariff_id.weekday_price_per_person_night', 'tariff_id.weekday_min_nights',
        'tariff_id.visitor_tax_per_person_night', 'tariff_id.final_cleaning_fee',
        'tariff_id.meal_breakfast', 'tariff_id.meal_half', 'tariff_id.meal_full',
        'tariff_id.tax_id', 'equipment_ids', 'equipment_ids.price_per_day',
        'company_id', 'company_id.currency_id',
    )
    def _compute_amounts(self):
        for rec in self:
            t = rec.tariff_id
            nights = rec.nights or 0
            pax = rec.participant_count or 0
            # F2: Personen-Nachtpreis ggf. als Mo–Fr-Sondertarif.
            rate_per_person = rec._accommodation_rate_per_person_night()
            accommodation = nights * (pax * rate_per_person
                                      + (t.price_flat_per_night if t else 0.0))
            meal_rate = 0.0
            if t:
                meal_rate = {
                    'breakfast': t.meal_breakfast,
                    'half': t.meal_half,
                    'full': t.meal_full,
                }.get(rec.meal_option, 0.0)
            meals = nights * pax * meal_rate
            equipment = nights * sum(rec.equipment_ids.mapped('price_per_day'))
            # F2: Endreinigung fällt EINMALIG je Buchung an (nicht je Nacht/Person).
            cleaning = (t.final_cleaning_fee or 0.0) if (t and nights > 0) else 0.0
            # F2: Fremdenverkehrsbeitrag je beitragspflichtiger Person und Nacht.
            # Bemessungsgrundlage siehe _visitor_tax_person_count(): Betreuende sind
            # satzungsgemäß befreit und zählen nicht mit, visitor_tax_exempt_count
            # zieht zusätzlich befreite Teilnehmende ab (nie negativ).
            liable_persons = rec._visitor_tax_person_count()
            visitor_tax = nights * liable_persons * (t.visitor_tax_per_person_night or 0.0) if t else 0.0
            rec.amount_accommodation = accommodation
            rec.amount_meals = meals
            rec.amount_equipment = equipment
            rec.amount_cleaning = cleaning
            rec.amount_visitor_tax = visitor_tax
            # Steuer positionsweise berechnen, damit die Buchungsbeträge exakt mit der
            # später erzeugten Rechnung (Rundung je Position) übereinstimmen.
            currency = rec.company_id.currency_id or self.env.company.currency_id
            taxes = t.tax_id if t else self.env['account.tax']
            untaxed = tax = 0.0
            for component in (accommodation, meals, equipment, cleaning):
                if not component:
                    continue
                res = taxes.compute_all(component, currency=currency, quantity=1.0)
                untaxed += res['total_excluded']
                tax += res['total_included'] - res['total_excluded']
            # Fremdenverkehrsbeitrag getrennt: er kann (Default) als durchlaufender
            # Posten ohne Steuer laufen — siehe TODO(Steuer) bei
            # _visitor_tax_pass_through. Die Rechnungsposition in
            # action_create_invoice verwendet exakt denselben Steuerschlüssel, damit
            # amount_total der Buchung und der Rechnungsbetrag identisch bleiben.
            if visitor_tax:
                visitor_taxes = rec._visitor_tax_taxes()
                if visitor_taxes:
                    res = visitor_taxes.compute_all(visitor_tax, currency=currency, quantity=1.0)
                    untaxed += res['total_excluded']
                    tax += res['total_included'] - res['total_excluded']
                else:
                    # Ohne Steuerschlüssel entspricht das Netto der Position exakt dem
                    # (kaufmännisch gerundeten) Betrag — genau wie bei einer
                    # Rechnungszeile mit tax_ids = [].
                    untaxed += currency.round(visitor_tax)
            rec.amount_untaxed = untaxed
            rec.amount_tax = tax
            rec.amount_total = untaxed + tax

    @api.depends(
        'participant_count', 'leader_count', 'nights', 'is_organized_group', 'facility_id',
        'check_in', 'facility_id.min_persons', 'facility_id.min_nights',
        'facility_id.requires_organized_group', 'facility_id.max_advance_months',
    )
    def _compute_occupancy_warning(self):
        """F2: Weicher Hinweis auf verletzte Belegungs- und Vorlaufregeln.

        Bewusst KEIN Constraint: Die Geschäftsstelle muss Ausnahmen im Backend erfassen
        dürfen (Projektstandard). Die harte Durchsetzung erfolgt nur im Website-Formular.
        """
        today = fields.Date.today()
        for rec in self:
            facility = rec.facility_id
            issues = []
            if facility:
                # Mindestbelegung zählt Teilnehmende UND Betreuende (siehe Hilfetext des
                # Feldes kjr.facility.min_persons) — genauso rechnet auch die Prüfung im
                # Website-Formular. Würde hier nur participant_count verglichen, meldete
                # das Backend eine Unterbelegung für Buchungen, die die Website zulässt.
                persons = (rec.participant_count or 0) + (rec.leader_count or 0)
                if facility.min_persons and persons < facility.min_persons:
                    issues.append(_(
                        'die Mindestbelegung von %(min)d Personen ist mit %(cur)d Personen '
                        '(Teilnehmende und Betreuende) unterschritten'
                    ) % {'min': facility.min_persons, 'cur': persons})
                if facility.min_nights and (rec.nights or 0) < facility.min_nights:
                    issues.append(_(
                        'der Mindestaufenthalt von %(min)d Nächten ist mit %(cur)d Nächten '
                        'unterschritten'
                    ) % {'min': facility.min_nights, 'cur': rec.nights or 0})
                if facility.requires_organized_group and not rec.is_organized_group:
                    issues.append(_(
                        'die Einrichtung darf nur an organisierte Jugend-/Bildungsgruppen '
                        'vergeben werden'
                    ))
                # B4: Buchungsvorlauf (Vorstandsbeschluss vom 21.07.2026) ist wie die
                # übrigen Belegungsregeln nur ein weicher Hinweis. Die Geschäftsstelle
                # muss begründete Ausnahmen (z. B. Stammgruppen mit langfristiger
                # Planung) erfassen können; hart durchgesetzt wird die Frist allein im
                # Website-Anfrageformular. 0 Monate = unbegrenzt; Anreisen in der
                # Vergangenheit/heute werden nie bemängelt (Altbuchungen, Nacherfassung).
                months = facility.max_advance_months or 0
                if months > 0 and rec.check_in and rec.check_in > today:
                    latest = today + relativedelta(months=months)
                    if rec.check_in > latest:
                        issues.append(_(
                            'der Buchungsvorlauf von %(m)d Monaten ist überschritten '
                            '(Anreise %(wish)s, laut Vorstandsbeschluss vom 21.07.2026 '
                            'spätestens %(latest)s)'
                        ) % {
                            'm': months,
                            'wish': rec.check_in.strftime('%d.%m.%Y'),
                            'latest': latest.strftime('%d.%m.%Y'),
                        })
            if issues:
                if len(issues) == 1:
                    detail = issues[0]
                else:
                    detail = _('%(head)s sowie %(last)s') % {
                        'head': ', '.join(issues[:-1]), 'last': issues[-1],
                    }
                rec.occupancy_warning = _(
                    'Hinweis: Für %(fac)s %(detail)s. Bitte Ausnahme mit der Geschäftsstelle '
                    'abstimmen.'
                ) % {'fac': facility.name or '', 'detail': detail}
            else:
                rec.occupancy_warning = False

    @api.depends('amount_total', 'deposit_pct')
    def _compute_deposit(self):
        for rec in self:
            rec.deposit_amount = rec.amount_total * (rec.deposit_pct or 0.0) / 100.0

    @api.depends('state')
    def _compute_is_booked(self):
        booked_states = ('confirmed', 'deposit', 'checked_in', 'invoiced', 'done')
        for rec in self:
            rec.is_booked = rec.state in booked_states

    @api.depends('state', 'facility_id.color')
    def _compute_calendar_color(self):
        # Reservierte (vorgemerkte) Buchungen erhalten eine neutrale, "hellere"
        # Farbe (Index 8 = hellgrau), gebuchte die Einrichtungsfarbe.
        for rec in self:
            if rec.state == 'reserved':
                rec.calendar_color = 8
            else:
                rec.calendar_color = rec.facility_id.color or 0

    @api.depends('invoice_id', 'invoice_id.payment_state')
    def _compute_payment_status(self):
        # Mapping account.move.payment_state -> eigenes, sprechendes Feld.
        mapping = {
            'not_paid': 'not_paid',
            'in_payment': 'in_payment',
            'paid': 'paid',
            'partial': 'partial',
            'reversed': 'reversed',
            'invoicing_legacy': 'not_paid',
        }
        for rec in self:
            if not rec.invoice_id:
                rec.payment_status = 'none'
            else:
                rec.payment_status = mapping.get(rec.invoice_id.payment_state, 'not_paid')

    def _compute_access_url(self):
        super()._compute_access_url()
        for rec in self:
            rec.access_url = f'/my/einrichtungsbuchungen/{rec.id}'

    # ══════════════════════════════════════════════════════════════════════════
    # CONSTRAINTS
    # ══════════════════════════════════════════════════════════════════════════

    @api.constrains('check_in', 'check_out')
    def _check_dates(self):
        for rec in self:
            if rec.check_in and rec.check_out and rec.check_out <= rec.check_in:
                raise ValidationError(_('Die Abreise muss nach der Anreise liegen.'))

    @api.constrains('participant_count', 'leader_count')
    def _check_counts(self):
        for rec in self:
            if rec.participant_count < 0 or rec.leader_count < 0:
                raise ValidationError(_('Teilnehmer-/Betreuerzahlen dürfen nicht negativ sein.'))

    @api.constrains('participant_count', 'facility_id', 'room_ids', 'bed_count')
    def _check_capacity(self):
        for rec in self:
            if rec.facility_id.capacity and rec.participant_count > rec.facility_id.capacity:
                raise ValidationError(_(
                    'Die Teilnehmerzahl (%(p)d) übersteigt die Kapazität der Einrichtung (%(c)d).',
                    p=rec.participant_count, c=rec.facility_id.capacity,
                ))
            if rec.room_ids and rec.bed_count and rec.participant_count > rec.bed_count:
                raise ValidationError(_(
                    'Die Teilnehmerzahl (%(p)d) übersteigt die gebuchten Betten (%(b)d).',
                    p=rec.participant_count, b=rec.bed_count,
                ))

    # B4: Der Buchungsvorlauf (Vorstandsbeschluss vom 21.07.2026) war hier bis
    # 19.0.3.0.0 ein @api.constrains und galt damit auch im Backend. Das widerspricht
    # dem Projektstandard — die Schwesterregeln (Mindestbelegung, Mindestaufenthalt,
    # organisierte Gruppe) sind bewusst nur weiche Hinweise — und machte begründete
    # Ausnahmen der Geschäftsstelle unmöglich; Altbuchungen jenseits der Frist
    # blockierten zudem jedes Speichern. Die Prüfung liegt jetzt als Hinweis in
    # _compute_occupancy_warning (Backend) bzw. als harte Validierung im
    # Website-Controller (_validate_facility_request).

    @api.constrains('room_ids', 'check_in', 'check_out', 'state',
                    'participant_count', 'leader_count', 'facility_id')
    def _check_double_booking(self):
        """Doppelbelegung prüfen — mit und ohne Raumauswahl.

        Mit Raumauswahl: kollidiert einer der gewählten Räume mit einer anderen,
        nicht stornierten Buchung? Ohne Raumauswahl (typisch für Backend-Buchungen
        und Einrichtungen ohne Raumaufteilung) wird stattdessen die Gesamtkapazität
        der Einrichtung im Überlappungszeitraum geprüft.
        """
        for rec in self:
            if rec.state == 'cancelled' or not (rec.check_in and rec.check_out) or not rec.facility_id:
                continue
            overlapping = self._find_overlapping(
                rec.facility_id.id, rec.check_in, rec.check_out,
                room_ids=rec.room_ids.ids or None, exclude_id=rec.id or None,
            )
            if rec.room_ids:
                if overlapping:
                    raise ValidationError(_(
                        'Raum-Doppelbelegung: Mindestens ein gewählter Raum ist im Zeitraum '
                        'bereits durch Buchung %(other)s belegt.'
                    ) % {'other': overlapping[0].name})
                continue
            # F2: Ohne Raumauswahl gegen die Gesamtkapazität der Einrichtung prüfen.
            # Es wird nur eingegriffen, wenn es tatsächlich Parallelbuchungen gibt —
            # die Einzelbuchung allein deckt bereits _check_capacity ab.
            capacity = rec.facility_id.capacity or 0
            if not capacity or not overlapping:
                continue
            others = sum(
                (bk.participant_count or 0) + (bk.leader_count or 0) for bk in overlapping
            )
            own = (rec.participant_count or 0) + (rec.leader_count or 0)
            if others + own > capacity:
                raise ValidationError(_(
                    'Überbelegung: Im Zeitraum %(ci)s–%(co)s sind in %(fac)s bereits '
                    '%(others)d Personen aus %(cnt)d anderen Buchungen (z. B. %(other)s) '
                    'eingeplant. Zusammen mit dieser Buchung (%(own)d Personen) wird die '
                    'Kapazität von %(cap)d Plätzen überschritten.'
                ) % {
                    'ci': rec.check_in.strftime('%d.%m.%Y'),
                    'co': rec.check_out.strftime('%d.%m.%Y'),
                    'fac': rec.facility_id.name or '',
                    'others': others,
                    'cnt': len(overlapping),
                    'other': overlapping[0].name,
                    'own': own,
                    'cap': capacity,
                })

    @api.model
    def _find_overlapping(self, facility_id, check_in, check_out, room_ids=None, exclude_id=None):
        """BUG-a: Liefert kollidierende, nicht stornierte Buchungen im Zeitraum.

        Wird sowohl im Backend als auch von der Website-Anfrage genutzt, um vor dem
        Anlegen eine Doppelbelegung zu erkennen. Ohne Räume wird auf Einrichtungsebene
        geprüft (relevant z. B. für Zeltplatz/Häuser ohne Raumauswahl)."""
        domain = [
            ('state', '!=', 'cancelled'),
            ('facility_id', '=', facility_id),
            ('check_in', '<', check_out),
            ('check_out', '>', check_in),
        ]
        if exclude_id:
            domain.append(('id', '!=', exclude_id))
        if room_ids:
            domain.append(('room_ids', 'in', list(room_ids)))
        return self.search(domain)

    # ══════════════════════════════════════════════════════════════════════════
    # ORM
    # ══════════════════════════════════════════════════════════════════════════

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('Neu'):
                vals['name'] = self.env['ir.sequence'].next_by_code('kjr.facility.booking') or _('Neu')
            # F7: Default-Uhrzeiten aus den Einrichtungs-Stammdaten übernehmen.
            if vals.get('facility_id'):
                facility = self.env['kjr.facility'].browse(vals['facility_id'])
                if 'arrival_time' not in vals and facility.check_in_default_time:
                    vals['arrival_time'] = facility.check_in_default_time
                if 'departure_time' not in vals and facility.check_out_default_time:
                    vals['departure_time'] = facility.check_out_default_time
        return super().create(vals_list)

    def write(self, vals):
        # F5: Versand-Flags zurücksetzen, sobald die auslösende Bedingung aufgelöst ist
        # (Vertrag unterschrieben / Anzahlung erhalten) — erlaubt erneute Erinnerung,
        # falls die Bedingung später wieder eintritt.
        if vals.get('contract_signed'):
            vals.setdefault('contract_followup_sent', False)
        if vals.get('deposit_paid'):
            vals.setdefault('deposit_reminder_sent', False)
        return super().write(vals)

    @api.onchange('facility_id')
    def _onchange_facility_default_times(self):
        # F7: Bei Auswahl der Einrichtung Default-Uhrzeiten im Formular vorbelegen.
        if self.facility_id:
            if not self.arrival_time and self.facility_id.check_in_default_time:
                self.arrival_time = self.facility_id.check_in_default_time
            if not self.departure_time and self.facility_id.check_out_default_time:
                self.departure_time = self.facility_id.check_out_default_time

    # ══════════════════════════════════════════════════════════════════════════
    # WORKFLOW
    # ══════════════════════════════════════════════════════════════════════════

    def _send_template(self, xmlid):
        try:
            self.env.ref(xmlid).send_mail(self.id, force_send=False)
        except Exception as e:  # noqa: BLE001 - Mailversand darf den Workflow nicht blockieren
            _logger.warning('Mailversand %s für %s fehlgeschlagen: %s', xmlid, self.name, e)

    def _store_document(self, report_xmlid, name):
        """F3: Rendert den PDF-Report und legt ihn deterministisch benannt als
        ir.attachment am Datensatz ab. Vorhandener Anhang gleichen Namens wird ersetzt,
        damit keine Dubletten entstehen (idempotent)."""
        self.ensure_one()
        try:
            pdf_content, _dummy = self.env['ir.actions.report']._render_qweb_pdf(
                report_xmlid, res_ids=[self.id])
            Attachment = self.env['ir.attachment']
            existing = Attachment.search([
                ('res_model', '=', self._name),
                ('res_id', '=', self.id),
                ('name', '=', name),
            ])
            if existing:
                existing.unlink()
            return Attachment.create({
                'name': name,
                'type': 'binary',
                'datas': base64.b64encode(pdf_content),
                'res_model': self._name,
                'res_id': self.id,
                'mimetype': 'application/pdf',
            })
        except Exception as e:  # noqa: BLE001 - Ablage darf den Workflow nicht blockieren
            _logger.warning('PDF-Ablage %s für %s fehlgeschlagen: %s', report_xmlid, self.name, e)
            return self.env['ir.attachment']

    def action_reserve(self):
        """F1: Anfrage -> Reserviert (vorgemerkt)."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Nur Anfragen können reserviert (vorgemerkt) werden.'))
            rec.state = 'reserved'
            rec.reservation_date = fields.Date.today()
            if not rec.reservation_expiry:
                rec.reservation_expiry = fields.Date.today() + timedelta(days=14)
            rec._send_template('kjr_facility.mail_template_booking_reserved')
            rec._store_document(
                'kjr_facility.action_report_booking_contract',
                _('Reservierungsbestaetigung_%s.pdf') % (rec.name or '').replace('/', '-'),
            )

    def action_confirm(self):
        for rec in self:
            if rec.state not in ('draft', 'reserved'):
                raise UserError(_('Nur Anfragen oder Reservierungen können gebucht werden.'))
            rec.state = 'confirmed'
            # F2: Vertrag automatisch zuschicken (mail.template mit PDF-Anhang).
            rec._send_template('kjr_facility.mail_template_booking_contract')
            rec.contract_sent_date = fields.Date.today()
            # F3: Vertrags-PDF deterministisch am Datensatz ablegen.
            rec._store_document(
                'kjr_facility.action_report_booking_contract',
                _('Buchungsvertrag_%s.pdf') % (rec.name or '').replace('/', '-'),
            )
            # Bestehende Buchungsbestätigung weiterhin senden.
            rec._send_template('kjr_facility.mail_template_booking_confirmed')

    def action_request_deposit(self):
        for rec in self:
            if rec.state not in ('confirmed',):
                raise UserError(_('Anzahlung kann nur für bestätigte Buchungen angefordert werden.'))
            rec.state = 'deposit'
            rec._send_template('kjr_facility.mail_template_booking_deposit')

    def action_check_in(self):
        for rec in self:
            if rec.state not in ('confirmed', 'deposit'):
                raise UserError(_('Anreise nur bei bestätigter Buchung möglich.'))
            rec.state = 'checked_in'

    def action_create_invoice(self):
        self.ensure_one()
        if self.state in ('draft', 'reserved', 'cancelled'):
            raise UserError(_(
                'Eine Rechnung kann erst ab der verbindlichen Buchung (Status „Gebucht") '
                'und nicht für stornierte Buchungen erstellt werden.'))
        if self.invoice_id:
            return self.action_view_invoice()
        if not self.partner_id:
            raise UserError(_('Bitte einen Mieter/eine Gruppe angeben.'))
        if self.amount_total <= 0:
            raise UserError(_('Es gibt nichts zu berechnen (Betrag ist 0). Bitte Tarif/Zeitraum prüfen.'))
        tax = self.tariff_id.tax_id
        tax_cmd = [(6, 0, tax.ids)] if tax else False
        lines = []
        if self.amount_accommodation:
            # F2: Kenntlich machen, wenn der günstigere Mo–Fr-Tarif angewandt wurde.
            weekday_hint = _(' – Mo–Fr-Tarif') if self._uses_weekday_rate() else ''
            lines.append((0, 0, {
                'name': _('Unterkunft %(fac)s, %(n)d Nächte, %(p)d Pers. (%(ci)s–%(co)s)') % {
                    'fac': self.facility_id.name, 'n': self.nights, 'p': self.participant_count,
                    'ci': self.check_in, 'co': self.check_out,
                } + weekday_hint,
                'quantity': 1.0, 'price_unit': self.amount_accommodation,
                'tax_ids': tax_cmd,
            }))
        if self.amount_meals:
            lines.append((0, 0, {
                'name': _('Verpflegung (%s)') % dict(self._fields['meal_option'].selection).get(self.meal_option),
                'quantity': 1.0, 'price_unit': self.amount_meals, 'tax_ids': tax_cmd,
            }))
        if self.amount_equipment:
            lines.append((0, 0, {
                'name': _('Zusatzausstattung'),
                'quantity': 1.0, 'price_unit': self.amount_equipment, 'tax_ids': tax_cmd,
            }))
        # F2: Endreinigung (einmalig) und Fremdenverkehrsbeitrag als eigene Positionen.
        # Die Endreinigung wird wie die übrigen Leistungen mit dem Tarif-Steuersatz
        # abgerechnet; der Fremdenverkehrsbeitrag folgt _visitor_tax_taxes() (Default:
        # ohne Steuer, siehe TODO(Steuer)). In beiden Fällen entspricht die
        # Rechnungssumme exakt dem in der Buchung ausgewiesenen Gesamtbetrag, weil
        # _compute_amounts dieselbe Fallunterscheidung verwendet.
        if self.amount_cleaning:
            lines.append((0, 0, {
                'name': _('Endreinigung (einmalig)'),
                'quantity': 1.0, 'price_unit': self.amount_cleaning, 'tax_ids': tax_cmd,
            }))
        if self.amount_visitor_tax:
            # B1: Bemessung identisch zu _compute_amounts (Betreuende sind befreit).
            # B2/TODO(Steuer): Steuerschlüssel kommt aus _visitor_tax_taxes() —
            # standardmäßig leer (durchlaufender Posten, „an die Gemeinde abgeführt").
            # Dadurch stimmt die Rechnungssumme exakt mit amount_total überein.
            visitor_taxes = self._visitor_tax_taxes()
            visitor_tax_hint = '' if visitor_taxes else _(
                ' (durchlaufender Posten, wird an die Gemeinde abgeführt)')
            lines.append((0, 0, {
                'name': _('Fremdenverkehrsbeitrag, %(p)d Pers. × %(n)d Nächte') % {
                    'p': self._visitor_tax_person_count(), 'n': self.nights,
                } + visitor_tax_hint,
                'quantity': 1.0, 'price_unit': self.amount_visitor_tax,
                'tax_ids': [(6, 0, visitor_taxes.ids)],
            }))
        move_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'invoice_origin': self.name,
            'invoice_line_ids': lines,
        }
        # B-cross: eigenen Nummernkreis 'V' (Verkaufsjournal) verwenden, falls vorhanden.
        journal = self.env['account.journal'].search([
            ('type', '=', 'sale'),
            ('code', '=', 'V'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if journal:
            move_vals['journal_id'] = journal.id
        move = self.env['account.move'].create(move_vals)
        # Optionaler Auto-Post-Schalter (Stammdaten an der Einrichtung).
        if self.facility_id.invoice_auto_post:
            try:
                move.action_post()
            except Exception as e:  # noqa: BLE001 - Posten darf den Workflow nicht hart abbrechen
                _logger.warning('Auto-Buchen der Rechnung %s fehlgeschlagen: %s', move.name, e)
        self.invoice_id = move.id
        self.state = 'invoiced'
        self.message_post(
            body=_('Rechnung %s erstellt.') % move.name, subtype_xmlid='mail.mt_note',
        )
        # Anzahlung: Die Rechnung lautet bewusst über den vollen Betrag. Eine bereits
        # geleistete Anzahlung ist in der Buchhaltung als Kundenzahlung gegen diese
        # Rechnung abzugleichen (kein automatischer Abzug, um die USt-Aufteilung nicht
        # zu verfälschen). TODO(Steuer): Anzahlungsbesteuerung § 13 UStG final prüfen.
        if self.deposit_paid and self.deposit_amount:
            move.message_post(body=_(
                'Hinweis: Anzahlung von %.2f € wurde bereits geleistet und ist mit dieser '
                'Rechnung als Kundenzahlung zu verrechnen.'
            ) % self.deposit_amount)
        return self.action_view_invoice()

    def action_done(self):
        for rec in self:
            if rec.state not in ('checked_in', 'invoiced'):
                raise UserError(_('Abschluss nur nach Anreise/Rechnung möglich.'))
            if rec.state == 'checked_in' and rec.amount_total > 0 and not rec.invoice_id:
                raise UserError(_(
                    'Bitte zuerst die Rechnung erstellen, bevor die Buchung abgeschlossen wird '
                    '(berechenbarer Betrag vorhanden).'
                ))
            # Übergabeprotokoll Abreise: Ein festgestellter Mangel hindert den Abschluss
            # NICHT — verlangt wird nur, dass jede Feststellung beschrieben ist. Ein gar
            # nicht erfasstes Protokoll blockiert ebenfalls nicht (Nacherfassung,
            # Papierprotokoll); darauf wird unten lediglich im Chatter hingewiesen.
            recorded = rec._handover_recorded('out')
            if recorded:
                rec._check_handover_protocol('out')
            rec.state = 'done'
            # Belegte Räume zur Reinigung markieren (action_handover_departure macht das
            # bereits bei der Rücknahme; hier bleibt es als Auffangnetz für Buchungen
            # ohne erfasstes Abreiseprotokoll).
            rec.room_ids.filtered(lambda r: r.housekeeping_state != 'blocked').write(
                {'housekeeping_state': 'dirty'})
            if not recorded:
                rec.message_post(
                    body=_('Die Buchung wurde abgeschlossen, ohne dass ein '
                           'Übergabeprotokoll für die Abreise erfasst wurde. Bitte im '
                           'Reiter „Übergabe" nachtragen, falls ein Papierprotokoll '
                           'vorliegt.'),
                    subtype_xmlid='mail.mt_note')

    def action_cancel(self):
        for rec in self:
            if rec.state == 'done':
                raise UserError(_('Abgeschlossene Buchungen können nicht storniert werden.'))
            rec.state = 'cancelled'
            rec._send_template('kjr_facility.mail_template_booking_cancelled')

    def action_reset_draft(self):
        for rec in self:
            if rec.state in ('invoiced', 'done'):
                raise UserError(_('Berechnete/abgeschlossene Buchungen können nicht zurückgesetzt werden.'))
            rec.state = 'draft'

    def action_view_invoice(self):
        self.ensure_one()
        if not self.invoice_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Rechnung'),
            'res_model': 'account.move',
            'res_id': self.invoice_id.id,
            'view_mode': 'form',
        }

    # ══════════════════════════════════════════════════════════════════════════
    # ÜBERGABEPROTOKOLL (Anreise / Abreise)
    # ══════════════════════════════════════════════════════════════════════════
    #
    # Aufbau bewusst analog zum Rückgabeprotokoll in kjr_rental
    # (kjr.rental.order._return_findings / _check_return_checklist / action_return),
    # inklusive der dort gezogenen Lehre: Die Checkliste hält den ZUSTAND fest und
    # ist KEINE Freigabebedingung. Ein Mangel darf den Abschluss der Buchung nicht
    # verhindern, er verlangt nur einen Vermerk.

    def _handover_field(self, direction, suffix):
        """Feldwert des Protokollteils ``direction`` ('in' = Anreise, 'out' = Abreise)."""
        self.ensure_one()
        return getattr(self, 'handover_%s_%s' % (direction, suffix))

    def _handover_label(self, direction):
        return _('Anreise') if direction == 'in' else _('Abreise')

    def _handover_recorded(self, direction):
        """Wurde der Protokollteil überhaupt angefasst?

        Wichtig für ``action_done``: Ein NICHT erfasstes Protokoll darf den Abschluss
        nicht blockieren (Nacherfassung von Altvorgängen, Papierprotokoll). Erst wenn
        etwas erfasst wurde, wird die Vollständigkeit des Vermerks eingefordert.
        """
        self.ensure_one()
        return bool(
            self._handover_field(direction, 'date')
            or self._handover_field(direction, 'condition')
            or self._handover_field(direction, 'damage')
            or (self._handover_field(direction, 'note') or '').strip()
            or (self._handover_field(direction, 'damage_note') or '').strip()
        )

    def _handover_findings(self, direction):
        """Abweichungen des Protokollteils als Klartextliste (leer = alles in Ordnung)."""
        self.ensure_one()
        findings = []
        condition = self._handover_field(direction, 'condition')
        if condition == 'minor':
            findings.append(_('kleinere Mängel festgestellt'))
        elif condition == 'major':
            findings.append(_('erhebliche Mängel festgestellt'))
        if self._handover_field(direction, 'damage'):
            findings.append(_('Schaden festgestellt'))
        if direction == 'out' and not self.handover_out_cleaning_ok:
            findings.append(_('nicht als gereinigt übergeben markiert'))
        return findings

    def _check_handover_protocol(self, direction):
        """Prüft NUR, ob jede Feststellung auch beschrieben ist.

        Der Zustand selbst (Mängel, Schaden, ungereinigt) hindert weder die Erfassung
        noch den Abschluss der Buchung — genau dafür ist das Protokoll da. Verlangt
        wird ausschließlich:

        * „Schaden festgestellt" gesetzt  -> Schadensbeschreibung ausfüllen,
        * sonstige Abweichung             -> irgendein Vermerk, der sie beschreibt.

        Die Häkchen dürfen NICHT wahrheitswidrig gesetzt werden, um die Erfassung
        abzukürzen; sonst verliert das Protokoll den Nachweiswert (siehe kjr_rental).
        """
        for rec in self:
            label = rec._handover_label(direction)
            damage_note = (rec._handover_field(direction, 'damage_note') or '').strip()
            if rec._handover_field(direction, 'damage') and not damage_note:
                raise UserError(_(
                    'Im Übergabeprotokoll %(dir)s von %(name)s ist „Schaden festgestellt" '
                    'angekreuzt. Bitte die Schadensbeschreibung ausfüllen: was ist '
                    'beschädigt, seit wann, wer hat es festgestellt. Das Kennzeichen bitte '
                    'nicht entfernen, um die Erfassung abzukürzen — es hält den '
                    'tatsächlichen Zustand fest.',
                    dir=label, name=rec.name,
                ))
            findings = rec._handover_findings(direction)
            free_text = damage_note or (rec._handover_field(direction, 'note') or '').strip()
            if findings and not free_text:
                raise UserError(_(
                    'Das Übergabeprotokoll %(dir)s von %(name)s weist Abweichungen auf '
                    '(%(findings)s). Bitte den Vermerk im Reiter „Übergabe" ausfüllen: was '
                    'wurde festgestellt, was wurde vereinbart. War alles in Ordnung, bitte '
                    'den Zustand entsprechend setzen (bei der Abreise auch „Gereinigt '
                    'übergeben") — nur wahrheitsgemäß.',
                    dir=label, name=rec.name, findings=', '.join(findings),
                ))

    def _handover_message(self, direction):
        """Protokollteil als Chatter-Notiz (spätere Nachvollziehbarkeit am Vorgang).

        Markup ist zwingend: message_post escapt einfache Zeichenketten, sonst stünden
        die <ul>/<li>-Tags als Text im Chatter. Die eingesetzten Werte (u. a. die frei
        erfassten Vermerke) werden von Markup.__mod__ weiterhin escaped.
        """
        self.ensure_one()
        conditions = dict(self._HANDOVER_CONDITIONS)
        condition = self._handover_field(direction, 'condition')
        date = self._handover_field(direction, 'date')
        dash = _('–')
        rows = [
            (_('Datum'), date.strftime('%d.%m.%Y') if date else dash),
            (_('Zustand'), conditions.get(condition, dash)),
        ]
        if direction == 'in':
            rows += [
                (_('Übergeben durch (KJR)'), self.handover_in_user_id.display_name or dash),
                (_('Übernommen durch (Gruppe)'), self.handover_in_received_by or dash),
                (_('Schlüssel übergeben'), str(self.handover_in_keys or 0)),
            ]
        else:
            rows += [
                (_('Zurückgenommen durch (KJR)'), self.handover_out_user_id.display_name or dash),
                (_('Übergeben durch (Gruppe)'), self.handover_out_handed_by or dash),
                (_('Schlüssel zurück'), str(self.handover_out_keys or 0)),
                (_('Gereinigt übergeben'),
                 _('ja') if self.handover_out_cleaning_ok else _('nein')),
            ]
        # Zählerstände nur aufnehmen, wenn tatsächlich abgelesen wurde (0 = nicht erfasst).
        for suffix, meter_label in (
            ('meter_electricity', _('Zählerstand Strom')),
            ('meter_water', _('Zählerstand Wasser')),
            ('meter_gas', _('Zählerstand Gas/Heizung')),
        ):
            value = self._handover_field(direction, suffix)
            if value:
                rows.append((meter_label, '%.2f' % value))
        rows += [
            # Der Chatter hält den TATSÄCHLICHEN Zustand fest (ja/nein), nicht den
            # Prüffortschritt: ein „ja" beim Schaden ist ein gültiges Ergebnis.
            (_('Schaden festgestellt'),
             _('ja') if self._handover_field(direction, 'damage') else _('nein')),
            (_('Schadensbeschreibung'),
             (self._handover_field(direction, 'damage_note') or '').strip() or dash),
            (_('Vermerk'), (self._handover_field(direction, 'note') or '').strip() or dash),
        ]
        items = Markup('').join(
            Markup('<li>%s: %s</li>') % (label, value) for label, value in rows
        )
        head = Markup('%s') % (_(
            'Übergabeprotokoll %s dokumentiert:') % self._handover_label(direction))
        return head + Markup('<ul>%s</ul>') % items

    def action_handover_arrival(self):
        """Anreiseteil des Übergabeprotokolls festschreiben und im Chatter ablegen."""
        for rec in self:
            if not rec.is_booked:
                raise UserError(_(
                    'Das Übergabeprotokoll kann erst ab der verbindlichen Buchung '
                    '(Status „Gebucht") erfasst werden.'))
            rec._check_handover_protocol('in')
            if not rec.handover_in_date:
                rec.handover_in_date = fields.Date.today()
            if not rec.handover_in_user_id:
                rec.handover_in_user_id = self.env.user
            rec.message_post(body=rec._handover_message('in'), subtype_xmlid='mail.mt_note')

    def action_handover_departure(self):
        """Abreiseteil des Übergabeprotokolls festschreiben und im Chatter ablegen.

        Setzt außerdem die Räume der Buchung auf „Zu reinigen" — die Abreise ist der
        Zeitpunkt, ab dem gereinigt werden muss, und der Abschluss der Buchung
        (action_done) kann deutlich später erfolgen. Gesperrte Räume bleiben
        unangetastet, genau wie in action_done; das doppelte Setzen ist unschädlich.
        """
        for rec in self:
            if rec.state not in ('checked_in', 'invoiced', 'done'):
                raise UserError(_(
                    'Das Abreiseprotokoll kann erst nach der Anreise erfasst werden.'))
            rec._check_handover_protocol('out')
            if not rec.handover_out_date:
                rec.handover_out_date = fields.Date.today()
            if not rec.handover_out_user_id:
                rec.handover_out_user_id = self.env.user
            rec.message_post(body=rec._handover_message('out'), subtype_xmlid='mail.mt_note')
            rec.room_ids.filtered(lambda r: r.housekeeping_state != 'blocked').write(
                {'housekeeping_state': 'dirty'})

    def action_print_handover(self):
        self.ensure_one()
        return self.env.ref('kjr_facility.action_report_booking_handover').report_action(self)

    def action_print_contract(self):
        self.ensure_one()
        return self.env.ref('kjr_facility.action_report_booking_contract').report_action(self)

    # ══════════════════════════════════════════════════════════════════════════
    # CRON
    # ══════════════════════════════════════════════════════════════════════════

    def _has_open_activity(self, summary):
        """Dedup-Helfer: prüft, ob bereits eine offene Activity mit gleichem Summary
        an diesem Datensatz hängt (verhindert Cron-Dubletten)."""
        self.ensure_one()
        return bool(self.activity_ids.filtered(lambda a: a.summary == summary))

    # ──────────────────────────────────────────────────────────────────────
    # Sicherung gegen Massenversand beim ersten Cron-Lauf
    #
    # Die Merker-Felder (reminder_sent, contract_followup_sent,
    # deposit_reminder_sent) stehen bei übernommenen bzw. importierten Buchungen
    # auf False. Ohne zusätzliche Bremse würde der erste Lauf nach Go-live den
    # kompletten Bestand anschreiben. Gleiches Muster wie in kjr_event:
    #   • kjr_facility.automation_active_from  – wird beim ERSTEN Lauf selbst
    #     geschrieben; danach zählen nur Buchungen, die NACH diesem Zeitpunkt
    #     angelegt wurden. Soll der Altbestand doch einbezogen werden, kann der
    #     Parameter von Hand auf ein früheres Datum gesetzt werden.
    #   • kjr_facility.automation_batch_limit – technische Obergrenze je Lauf
    #     (Default 50, kein fachlicher Wert). Was übrig bleibt, kommt beim
    #     nächsten Lauf dran.
    # Beides sind bewusst KEINE Seed-Datensätze: der erste Lauf legt sie an.
    # ──────────────────────────────────────────────────────────────────────
    _AUTOMATION_ACTIVE_FROM = 'kjr_facility.automation_active_from'
    _AUTOMATION_BATCH_LIMIT = 'kjr_facility.automation_batch_limit'
    _AUTOMATION_DEFAULT_LIMIT = 50

    @api.model
    def _automation_active_from(self):
        """Zeitpunkt, ab dem angelegte Buchungen automatisiert werden."""
        params = self.env['ir.config_parameter'].sudo()
        raw = params.get_param(self._AUTOMATION_ACTIVE_FROM)
        if raw in (None, False, ''):
            now = fields.Datetime.now()
            params.set_param(self._AUTOMATION_ACTIVE_FROM, fields.Datetime.to_string(now))
            _logger.info(
                'KJR-Einrichtungsautomatik aktiviert: es werden nur Buchungen '
                'berücksichtigt, die nach %s angelegt wurden (%s).',
                now, self._AUTOMATION_ACTIVE_FROM)
            return now
        try:
            active_from = fields.Datetime.to_datetime(raw)
        except (TypeError, ValueError):
            active_from = False
        if not active_from:
            _logger.warning(
                'Systemparameter %s enthält kein gültiges Datum (%r) – Automatik pausiert.',
                self._AUTOMATION_ACTIVE_FROM, raw)
        return active_from

    @api.model
    def _automation_batch_limit(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(self._AUTOMATION_BATCH_LIMIT)
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            limit = 0
        return limit if limit > 0 else self._AUTOMATION_DEFAULT_LIMIT

    @api.model
    def _automation_search(self, domain):
        """Suche für die Automatik: Aktivierungszeitpunkt + Mengenbegrenzung."""
        active_from = self._automation_active_from()
        if not active_from:
            return self.browse()
        return self.search(
            domain + [('create_date', '>=', active_from)],
            limit=self._automation_batch_limit(), order='id')

    @api.model
    def _cron_booking_reminder(self):
        """Erinnerung ~14 Tage vor Anreise an aktive Buchungen.

        F5: Datums-RANGE statt '==' (robust bei Cron-Aussetzern) plus Dedup über
        die Activity-Existenz, damit nicht mehrfach erinnert wird."""
        today = fields.Date.today()
        window_start = today + timedelta(days=13)
        window_end = today + timedelta(days=15)
        bookings = self._automation_search([
            ('state', 'in', ('confirmed', 'deposit', 'checked_in')),
            ('reminder_sent', '=', False),
            ('check_in', '>=', window_start),
            ('check_in', '<=', window_end),
        ])
        count = 0
        for bk in bookings:
            summary = _('Anreise in ca. 14 Tagen: %s') % bk.name
            if not bk._has_open_activity(summary):
                bk.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=bk.check_in,
                    summary=summary,
                    note=_('Die Gruppe "%(grp)s" reist am %(d)s in %(fac)s an.') % {
                        'grp': bk.group_name or bk.partner_id.display_name,
                        'd': bk.check_in.strftime('%d.%m.%Y'),
                        'fac': bk.facility_id.name,
                    },
                )
            bk._send_template('kjr_facility.mail_template_booking_reminder')
            bk.reminder_sent = True
            count += 1
        _logger.info('Einrichtungs-Erinnerung: %d Buchungen', count)

    @api.model
    def _cron_contract_followup(self):
        """F5: Vertrag gesendet, aber nicht unterschrieben und älter als X Tage
        -> Activity + Mahn-Mail (idempotent über Dedup)."""
        followup_days = 10
        cutoff = fields.Date.today() - timedelta(days=followup_days)
        bookings = self._automation_search([
            ('state', 'in', ('confirmed', 'deposit', 'checked_in')),
            ('contract_signed', '=', False),
            ('contract_followup_sent', '=', False),
            ('contract_sent_date', '!=', False),
            ('contract_sent_date', '<=', cutoff),
        ])
        count = 0
        for bk in bookings:
            summary = _('Vertrag offen (unterschrieben?): %s') % bk.name
            if not bk._has_open_activity(summary):
                bk.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=fields.Date.today(),
                    summary=summary,
                    note=_('Der am %(d)s gesendete Vertrag für "%(grp)s" ist noch nicht als '
                           'unterschrieben markiert.') % {
                        'd': bk.contract_sent_date.strftime('%d.%m.%Y'),
                        'grp': bk.group_name or bk.partner_id.display_name,
                    },
                )
            bk._send_template('kjr_facility.mail_template_contract_followup')
            bk.contract_followup_sent = True
            count += 1
        _logger.info('Vertrags-Nachfass: %d Buchungen', count)

    @api.model
    def _cron_deposit_overdue(self):
        """F5: Anzahlung überfällig (deposit_due_date < heute & nicht bezahlt)."""
        today = fields.Date.today()
        bookings = self._automation_search([
            ('state', 'in', ('confirmed', 'deposit', 'checked_in')),
            ('deposit_paid', '=', False),
            ('deposit_reminder_sent', '=', False),
            ('deposit_due_date', '!=', False),
            ('deposit_due_date', '<', today),
        ])
        count = 0
        for bk in bookings:
            summary = _('Anzahlung überfällig: %s') % bk.name
            if not bk._has_open_activity(summary):
                bk.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=today,
                    summary=summary,
                    note=_('Die Anzahlung (%(amt).2f €) für "%(grp)s" war am %(d)s fällig und '
                           'ist noch nicht als erhalten markiert.') % {
                        'amt': bk.deposit_amount,
                        'grp': bk.group_name or bk.partner_id.display_name,
                        'd': bk.deposit_due_date.strftime('%d.%m.%Y'),
                    },
                )
            bk._send_template('kjr_facility.mail_template_booking_deposit')
            bk.deposit_reminder_sent = True
            count += 1
        _logger.info('Anzahlung überfällig: %d Buchungen', count)

    @api.model
    def _cron_reservation_expiry(self):
        """F5: Reservierung abgelaufen (reservation_expiry < heute, state=reserved)
        -> Activity/Hinweis (idempotent)."""
        today = fields.Date.today()
        bookings = self._automation_search([
            ('state', '=', 'reserved'),
            ('reservation_expiry', '!=', False),
            ('reservation_expiry', '<', today),
        ])
        count = 0
        for bk in bookings:
            summary = _('Reservierung abgelaufen: %s') % bk.name
            if bk._has_open_activity(summary):
                continue
            bk.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=today,
                summary=summary,
                note=_('Die Vormerkung für "%(grp)s" ist seit %(d)s abgelaufen. Bitte '
                       'verbindlich buchen oder stornieren.') % {
                    'grp': bk.group_name or bk.partner_id.display_name,
                    'd': bk.reservation_expiry.strftime('%d.%m.%Y'),
                },
            )
            count += 1
        _logger.info('Reservierung abgelaufen: %d Buchungen', count)


    # ══════════════════════════════════════════════════════════════════════════
    # DSGVO — AUFBEWAHRUNG / ANONYMISIERUNG (Befund K5)
    # ══════════════════════════════════════════════════════════════════════════
    #
    # Anonymisieren statt löschen, aus demselben Grund wie in kjr_grant: Belegung,
    # Personenzahlen, Zeitraum und Beträge werden für Auswertung, Belegungsstatistik
    # und Abrechnung weiter gebraucht — die Klarnamen nicht. Minderjährige stehen in
    # diesem Modul ohnehin nur als Zahl (participant_count), betroffen sind die
    # Ansprechperson, deren Kontaktdaten, die Gruppenbezeichnung, die Freitexte und
    # die Namen im Übergabe-/Rücknahmeprotokoll.
    #
    # Zur Frist siehe den Kommentarblock am Modulkopf: sie ist NICHT entschieden,
    # der Auslieferungszustand ist aus.

    # Felder, die beim Ablauf der Frist geleert werden. Bewusst NICHT enthalten und
    # deshalb hier begründet:
    #   • partner_id — Pflichtfeld mit ondelete='restrict' und Klammer zur Rechnung;
    #     der Kontakt selbst gehört nach res.partner, nicht in die Buchung.
    #   • invoice_id und alles an der Rechnung — account.move ist hash-verkettet,
    #     dort wird weder gelöscht noch geändert (siehe _cron_anonymize_expired).
    #   • participant_count, leader_count, visitor_tax_exempt_count, nights,
    #     check_in/check_out, sämtliche Beträge, state, is_grant_funded — Aggregat-,
    #     Zeit- und Abrechnungsdaten ohne Personenbezug.
    #   • Zählerstände, Schlüsselzahlen, Zustands- und Schadenskennzeichen —
    #     Sachangaben zum Objekt; nur die zugehörigen FREITEXTE werden geleert.
    #   • grant_reference — Aktenzeichen des Zuschussvorgangs, kein Klarname; die
    #     Teilnehmerdaten dazu anonymisiert kjr_grant nach eigener Frist.
    _ANONYMIZE_FIELDS = (
        'group_name',                 # Gruppenbezeichnung, kann ein Klarname sein
        'contact_person',             # Ansprechperson der Gruppe
        'contact_email',
        'contact_phone',
        'note',                       # Freitext, laut Audit mittelbar personenbezogen
        'internal_note',
        'equipment_notes',
        'handover_in_received_by',    # Klarname aus dem Übergabeprotokoll (Gruppe)
        'handover_out_handed_by',     # Klarname aus dem Rücknahmeprotokoll (Gruppe)
        'handover_in_note',
        'handover_out_note',
        'handover_in_damage_note',
        'handover_out_damage_note',
        'handover_in_user_id',        # Beschäftigtenbezug: wer hat übergeben
        'handover_out_user_id',       # Beschäftigtenbezug: wer hat zurückgenommen
    )

    # Feldhistorie (mail.tracking.value): Von den getrackten Feldern der Buchung
    # trägt nur partner_id einen Klarnamen — Odoo schreibt bei Many2one den damaligen
    # ANZEIGENAMEN als Text mit. Alle übrigen getrackten Felder (Status, Daten,
    # Zahlen, Zustandskennzeichen) sind sachbezogen; die personenbezogenen Felder
    # oben tragen kein tracking=True und hinterlassen deshalb auch keine Historie.
    # Entfernt wird nur der Trackingwert, die zugehörige mail.message bleibt stehen:
    # dass der Mieter gewechselt wurde und wer das getan hat, bleibt nachweisbar.
    # TODO(DSGVO): Ob die Mieter-Historie überhaupt entfernt werden soll, ist eine
    # Abwägung (Nachweis der Vertragspartnerschaft gegen Speicherbegrenzung) — sie
    # hängt am Schalter KJR_FACILITY_TRACES_PARAM und ist im Auslieferungszustand aus.
    _ANONYMIZE_TRACKED_FIELDS = ('partner_id',)

    @api.model
    def _dsgvo_retention_years(self):
        """Aufbewahrungsfrist in Jahren aus dem Systemparameter; 0 = abgeschaltet.

        Fehlt der Parameter oder ist er nicht als ganze Zahl lesbar, gilt 0 — also
        KEINE Verarbeitung. Das ist die konservative Seite: solange der KJR keine
        Frist festgelegt hat, darf nichts passieren (TODO(KJR) am Modulkopf)."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            KJR_FACILITY_RETENTION_PARAM, '0')
        try:
            years = int(raw)
        except (TypeError, ValueError):
            _logger.warning(
                'DSGVO: Systemparameter %s ist keine ganze Zahl (%r) — die '
                'Anonymisierung der Einrichtungsbuchungen bleibt abgeschaltet.',
                KJR_FACILITY_RETENTION_PARAM, raw)
            return 0
        return years if years > 0 else 0

    @api.model
    def _dsgvo_cutoff_date(self):
        """Stichtag oder None, wenn keine Frist gesetzt ist.

        Jahresend-Anker wie in kjr_grant: gezählt werden volle Kalenderjahre NACH
        dem Jahr der Abreise. Eine Buchung mit Abreise 2027 ist bei einer Frist von
        5 Jahren erst ab dem 01.01.2033 fällig, nicht schon im Laufe des Jahres 2032.
        Bewusst die spätere Variante — zu früh anonymisieren würde eine etwaige
        Aufbewahrungspflicht verletzen."""
        years = self._dsgvo_retention_years()
        if not years:
            return None
        return date(fields.Date.today().year - years, 1, 1)

    @api.model
    def _dsgvo_traces_enabled(self):
        """Sollen auch Chatter, Feldhistorie und Anhänge mitgezogen werden?

        Ebenfalls im Auslieferungszustand AUS. Hintergrund (Audit K6): Chatter und
        abgelegte PDF sind zugleich Nachweis des Verwaltungsvorgangs; ob und wie
        weit sie mit anonymisiert werden, ist eine Abwägung zwischen
        Nachweisinteresse und Speicherbegrenzung und keine Codeentscheidung.
        TODO(DSGVO): Von der Datenschutzbeauftragten entscheiden lassen."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            KJR_FACILITY_TRACES_PARAM, '0')
        return str(raw).strip().lower() in ('1', 'true', 'yes', 'wahr')

    @staticmethod
    def _dsgvo_redact(text, literals):
        """Klartextvorkommen in einem (HTML-)Text durch den Platzhalter ersetzen.

        Gibt (neuer_text, Treffer) zurück. Gesucht wird sowohl die rohe als auch die
        HTML-escapte Schreibweise, weil Chatter-Inhalte escaped gespeichert werden
        ("Müller & Sohn" → "Müller &amp; Sohn"). Zeichenketten unter vier Zeichen
        bleiben außen vor, sonst entstünden im Fließtext falsche Treffer."""
        if not text:
            return text, 0
        result = text
        hits = 0
        for literal in literals:
            literal = (literal or '').strip()
            if len(literal) < 4:
                continue
            for variant in {literal, str(escape(literal))}:
                if variant and variant in result:
                    hits += result.count(variant)
                    result = result.replace(variant, DSGVO_REDACTED)
        return result, hits

    def _dsgvo_personal_literals(self):
        """Die personenbezogenen Zeichenketten dieser Buchung einsammeln.

        Muss VOR dem Leeren der Felder laufen: danach sind die Werte nicht mehr
        rekonstruierbar und im Chatter nicht mehr auffindbar (dieselbe Grenze wie in
        kjr_grant). Die Anzeigenamen der beiden Protokoll-Bearbeitenden kommen mit
        hinein, weil _handover_message sie in die Chatter-Notiz schreibt."""
        self.ensure_one()
        literals = set()
        for fname in self._ANONYMIZE_FIELDS:
            value = self[fname]
            if not value:
                continue
            if isinstance(value, str):
                literals.add(value.strip())
            else:  # Many2one (handover_*_user_id)
                literals.add(value.display_name or '')
        return {lit for lit in literals if lit}

    def _dsgvo_anonymize_chatter(self, literals):
        """Klarnamen in den Chatter-Nachrichten der Buchung schwärzen.

        Abwägung wie in kjr_grant: GELÖSCHT wird nichts. Autor, Zeitpunkt und
        Reihenfolge der Nachrichten dokumentieren den Verwaltungsvorgang (wer hat
        wann übergeben, zurückgenommen, berechnet) und bleiben vollständig erhalten.
        Ersetzt werden nur die personenbezogenen Zeichenketten — und zwar genau die,
        die derselbe Lauf gerade an den Feldern geleert hat.

        Nötig ist das, weil das Übergabe- und Rücknahmeprotokoll zusätzlich als
        Chatter-Notiz gespiegelt wird (_handover_message): ohne diesen Schritt stünde
        derselbe Name unverändert im Chatter und die Anonymisierung liefe ins Leere.

        Grenze, die der Code nicht überwinden kann: Namen aus einem FRÜHEREN Lauf
        sind nicht mehr bekannt und im Chatter nicht mehr erkennbar.
        TODO(KJR): Einmalige manuelle Durchsicht der Altbestände einplanen.

        Idempotent: nach dem Ersetzen findet der nächste Lauf nichts mehr."""
        self.ensure_one()
        if not literals:
            return 0
        messages = self.env['mail.message'].sudo().search([
            ('model', '=', self._name),
            ('res_id', '=', self.id),
        ])
        touched = 0
        for msg in messages:
            new_body, body_hits = self._dsgvo_redact(msg.body or '', literals)
            new_subject, subject_hits = self._dsgvo_redact(msg.subject or '', literals)
            if not (body_hits or subject_hits):
                continue
            vals = {}
            if body_hits:
                vals['body'] = new_body
            if subject_hits:
                vals['subject'] = new_subject
            msg.write(vals)
            touched += 1
        return touched

    def _dsgvo_anonymize_tracking(self):
        """Feldhistorie zu den personenbezogenen Feldern aufräumen.

        mail.tracking.value überlebt jede Anonymisierung des Feldes: der frühere
        Mieter steht nach dem Wechsel weiterhin als Text in der Historie. Entfernt
        wird deshalb der Trackingwert; die zugehörige mail.message bleibt bestehen.

        Idempotent: entfernte Datensätze findet der nächste Lauf nicht mehr."""
        self.ensure_one()
        tracking = self.env['mail.tracking.value'].sudo().search([
            ('mail_message_id.model', '=', self._name),
            ('mail_message_id.res_id', '=', self.id),
            ('field_id.name', 'in', list(self._ANONYMIZE_TRACKED_FIELDS)),
        ])
        count = len(tracking)
        if count:
            tracking.unlink()
        return count

    def _dsgvo_anonymize_attachments(self):
        """Am Vorgang abgelegte PDF durch einen Platzhalter ersetzen.

        Abwägung Löschen vs. Platzhalter — gewählt ist der Platzhalter, wie in
        kjr_grant: Ein unlink() nähme der Buchung den Nachweis, dass Vertrag,
        Reservierungsbestätigung und Übergabeprotokoll überhaupt erzeugt wurden. Der
        Personenbezug steckt im Dateiinhalt (Ansprechperson, Gruppe, Kontaktdaten,
        Protokollnamen), nicht in der Tatsache der Ablage: der Inhalt wird ersetzt,
        die Hülle bleibt.

        NICHT angefasst: Anhänge an der Rechnung (account.move) — die liegen an
        einem anderen res_model und bleiben wegen der Hash-Verkettung unberührt.

        Idempotent über den Marker in ir.attachment.description."""
        self.ensure_one()
        # res_field = False: nur echte Dokumente, keine Binärfeld-Ablagen.
        attachments = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', self._name),
            ('res_id', '=', self.id),
            ('res_field', '=', False),
        ])
        touched = 0
        for att in attachments:
            if DSGVO_ANON_MARKER in (att.description or ''):
                continue  # bereits ersetzt
            if att.type != 'binary':
                continue  # URL-Anhänge tragen keinen Dateiinhalt
            body = _(
                'Der Inhalt dieses Anhangs (%(orig)s) wurde nach Ablauf der vom KJR '
                'festgelegten Aufbewahrungsfrist entfernt. Erhalten bleibt nur die '
                'Tatsache, dass zum Vorgang %(booking)s ein Dokument abgelegt war.'
            ) % {'orig': att.name or '', 'booking': self.name or ''}
            att.write({
                'name': _('Anonymisiert_%s.txt') % (self.name or '').replace('/', '-'),
                'datas': base64.b64encode(body.encode('utf-8')),
                'mimetype': 'text/plain',
                'description': '%s ersetzt am %s' % (
                    DSGVO_ANON_MARKER, fields.Date.today().strftime('%d.%m.%Y')),
            })
            touched += 1
        return touched

    @api.model
    def _cron_anonymize_expired(self):
        """DSGVO (Speicherbegrenzung): personenbezogene Anteile abgelaufener
        Einrichtungsbuchungen anonymisieren statt zu löschen (Befund K5).

        Bezugspunkt ist die ABREISE (check_out), also das Ende der Buchung: ab da ist
        der Vorgang tatsächlich erledigt. Das Anlagedatum wäre der falsche Anker,
        weil Buchungen lange im Voraus erfasst werden.

        Frist über den Systemparameter 'kjr_facility.booking_retention_years'.
        Auslieferungszustand 0 = AUS: der Cron läuft, findet nichts und schreibt
        nichts. Es wird bewusst KEINE Frist vorbelegt (siehe Modulkopf).

        Bewusst NICHT berührt wird die Rechnung: account.move ist hash-verkettet,
        eine nachträgliche Änderung bricht die Kette. Dort stehen der
        Rechnungsempfänger (partner_id) und die Positionstexte; die Positionstexte
        kommen ohne Klarnamen aus (Einrichtung, Nächte, Personenzahl, Beitrag),
        sodass der personenbezogene Rest vollständig über die Buchung anonymisierbar
        ist. Der Rechnungsempfänger selbst ist eine Frage von res.partner und
        account.move, nicht dieses Moduls.
        TODO(DSGVO): Umgang mit dem Rechnungsempfänger im Buchungsbeleg klären.
        """
        cutoff = self._dsgvo_cutoff_date()
        if not cutoff:
            # Auslieferungszustand: keine Frist festgelegt → nichts tun. Bewusst nur
            # auf Debug-Ebene, der Cron läuft monatlich.
            _logger.debug(
                'DSGVO-Anonymisierung (Einrichtung) ausgesetzt: %s ist nicht gesetzt.',
                KJR_FACILITY_RETENTION_PARAM)
            return
        # sudo(): internal_note trägt ein serverseitiges groups= (nur wirksame
        # Zugriffsgrenze in Odoo, readonly wäre keine). Ein Cron-Benutzer ohne diese
        # Gruppe könnte das Feld sonst weder lesen noch leeren.
        stale = self.sudo().search([
            ('data_anonymized', '=', False),
            ('check_out', '<', cutoff),
            # Solange eine Rechnung offen oder erst im Entwurf ist, ist der Vorgang
            # nicht abgeschlossen. Bleibt eine Forderung dauerhaft offen, wird der
            # Vorgang nicht anonymisiert — das ist so gewollt: er muss dann
            # buchhalterisch abgeschlossen werden.
            ('payment_status', 'not in', ('not_paid', 'in_payment', 'partial')),
        # Mengenbegrenzung wie bei der übrigen Automatik, aber bewusst NICHT über
        # _automation_search: dessen Aktivierungszeitpunkt filtert auf junge
        # create_date und würde genau die alten Vorgänge aussparen, um die es hier geht.
        ], limit=self._automation_batch_limit(), order='id')
        if not stale:
            return
        with_traces = self._dsgvo_traces_enabled()
        messages = tracking = attachments = 0
        blank_values = dict.fromkeys(self._ANONYMIZE_FIELDS, False)
        for rec in stale:
            # Erst einsammeln, dann leeren: danach sind die Werte weg.
            literals = rec._dsgvo_personal_literals() if with_traces else set()
            rec.write(dict(blank_values, data_anonymized=True))
            if with_traces:
                messages += rec._dsgvo_anonymize_chatter(literals)
                tracking += rec._dsgvo_anonymize_tracking()
                attachments += rec._dsgvo_anonymize_attachments()
        _logger.info(
            'DSGVO-Anonymisierung (Einrichtung): %d Buchungen anonymisiert '
            '(Stichtag %s, Frist %d Jahre ab Abreise, Jahresend-Anker).',
            len(stale), cutoff, self._dsgvo_retention_years())
        if with_traces:
            _logger.info(
                'DSGVO-Anonymisierung (Einrichtung) Nebenschauplätze: '
                '%d Chatter-Nachrichten geschwärzt, %d Trackingwerte entfernt, '
                '%d Anhänge ersetzt.', messages, tracking, attachments)
        else:
            _logger.warning(
                'DSGVO-Anonymisierung (Einrichtung): Chatter, Feldhistorie und '
                'Anhänge der %d Buchungen wurden NICHT bearbeitet (%s ist aus). '
                'Dort stehen dieselben Namen weiterhin.',
                len(stale), KJR_FACILITY_TRACES_PARAM)
