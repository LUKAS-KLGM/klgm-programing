# -*- coding: utf-8 -*-
"""Ausleihvorgang mit Workflow und Verfügbarkeitsprüfung."""
import base64
import logging
from datetime import date

from markupsafe import Markup, escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)

# ── DSGVO: Aufbewahrung / Anonymisierung (Befund K5, Audit vom 21.08.2026) ───
# Aufbau und Begründungsstil bewusst übernommen von kjr_grant
# (kjr.grant.participant._cron_anonymize_expired und die Nebenschauplätze in
# kjr_grant_application.py) und identisch zu kjr_facility, damit alle Module
# gleich zu prüfen und zu pflegen sind. Eine Modulabhängigkeit zu kjr_grant
# besteht nicht und soll nicht entstehen — die wenigen Helfer sind deshalb
# bewusst dupliziert.
#
# WICHTIG: Für Ausleihen ist KEINE Aufbewahrungsfrist entschieden. Die Parameter
# sind im Auslieferungszustand NICHT gesetzt; der Code liest dann '0', und '0'
# bedeutet: es passiert GAR NICHTS. Erst ein vom KJR eingetragener Wert > 0
# schaltet die Verarbeitung ein.
#
# Anhaltspunkte aus dem Projektvault — ausschließlich Entscheidungshilfe für den
# KJR, bewusst NICHT als Default gesetzt und hier ausdrücklich keine Rechtsaussage:
#   • Buchungsbelege: 8 Jahre (§ 147 AO, § 257 HGB)
#   • Verwendungsnachweise: 5 Jahre (ANBest-P Nr. 6.6)
#   • "1 Jahr Ferienprogramm" ist eine selbstdefinierte Policy des KJR und
#     ausdrücklich keine gesetzliche Frist.
# TODO(KJR): Frist festlegen und KJR_RENTAL_RETENTION_PARAM setzen.
# TODO(DSGVO): Festlegung und Verfahren von der Datenschutzbeauftragten
# bestätigen lassen, insbesondere den Umgang mit Chatter und Feldhistorie.
KJR_RENTAL_RETENTION_PARAM = 'kjr_rental.order_retention_years'
KJR_RENTAL_TRACES_PARAM = 'kjr_rental.order_anonymize_traces'
# Technische Obergrenze je Lauf, kein fachlicher Wert: was übrig bleibt, kommt
# beim nächsten Lauf dran (der Cron läuft monatlich).
KJR_RENTAL_BATCH_PARAM = 'kjr_rental.order_anonymize_batch_limit'
KJR_RENTAL_BATCH_DEFAULT = 200

# Platzhalter und Idempotenz-Marker (Schreibweise wie in kjr_grant/kjr_facility).
# ir.attachment.description ist ein freies Textfeld; ein eigenes Feld auf
# ir.attachment wird bewusst nicht angelegt (Fremdmodell).
DSGVO_REDACTED = '(anonymisiert)'
DSGVO_ANON_MARKER = '[DSGVO-anonymisiert]'


class KjrRentalOrder(models.Model):
    _name = 'kjr.rental.order'
    _description = 'KJR Ausleihe'
    _order = 'date_from desc, name desc'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']

    name = fields.Char(
        string='Ausleihnummer', required=True, copy=False, readonly=True,
        default=lambda self: _('Neu'), tracking=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Gesellschaft', required=True, index=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(related='company_id.currency_id')
    partner_id = fields.Many2one('res.partner', string='Entleiher', required=True, ondelete='restrict', tracking=True)
    contact_email = fields.Char(string='E-Mail')
    contact_phone = fields.Char(string='Telefon')
    # R2: Mitgliedstarif wird aus dem Kontakt abgeleitet, statt ihn bei jeder
    # Online-Anfrage manuell nachzuziehen. store=True/readonly=False, damit die
    # Geschäftsstelle im Einzelfall übersteuern kann (siehe _compute_is_member).
    is_member = fields.Boolean(
        string='KJR-Mitglied (Tarif)', tracking=True,
        compute='_compute_is_member', store=True, readonly=False,
        help='Wird aus dem Kennzeichen "KJR-Mitgliedsverband" des Entleihers '
             'übernommen und bestimmt den Tagespreis der Positionen. Der Wert kann '
             'hier im Einzelfall übersteuert werden; die Übersteuerung bleibt '
             'erhalten, solange der Entleiher nicht gewechselt wird. Ab Status '
             '"Ausgegeben" wird nicht mehr automatisch nachgezogen.',
    )
    state = fields.Selection([
        ('draft', 'Anfrage'),
        ('reserved', 'Reserviert'),
        ('issued', 'Ausgegeben'),
        ('returned', 'Zurückgegeben'),
        ('cancelled', 'Storniert'),
    ], string='Status', default='draft', required=True, tracking=True, index=True)
    date_from = fields.Date(string='Von', required=True, tracking=True)
    date_to = fields.Date(string='Bis', required=True, tracking=True)
    rental_days = fields.Integer(string='Tage', compute='_compute_rental_days', store=True)
    line_ids = fields.One2many('kjr.rental.order.line', 'order_id', string='Positionen')
    amount_total = fields.Monetary(string='Gebühr gesamt', compute='_compute_amounts', store=True)
    deposit_total = fields.Monetary(string='Kaution gesamt', compute='_compute_amounts', store=True)
    deposit_paid = fields.Boolean(string='Kaution erhalten', tracking=True)
    invoice_id = fields.Many2one('account.move', string='Rechnung', readonly=True, copy=False)
    # B-cross-2: Zahlungsstatus der Rechnung gespiegelt (store für Filter/Gruppierung)
    invoice_payment_state = fields.Selection(
        related='invoice_id.payment_state', string='Zahlungsstatus',
        store=True, tracking=True,
    )
    # B-cross-3: Kaution als eigener Lebenszyklus
    deposit_state = fields.Selection([
        ('none', 'Keine / offen'),
        ('received', 'Erhalten'),
        ('refunded', 'Erstattet'),
        ('withheld', 'Einbehalten'),
    ], string='Kautionsstatus', default='none', required=True, tracking=True)
    deposit_received_date = fields.Date(string='Kaution erhalten am', tracking=True)
    deposit_refund_date = fields.Date(string='Kaution erstattet/einbehalten am', tracking=True)
    note = fields.Text(string='Anmerkungen')

    # ------------------------------------------------------------------
    # R2: Zweckbindung und Nutzungshinweise
    # ------------------------------------------------------------------
    purpose = fields.Text(
        string='Zweck der Nutzung',
        help='Wofür wird das Material eingesetzt (Veranstaltung, Gruppe, Anlass)? '
             'Der Verleih ist an die Jugendarbeit nach SGB VIII gebunden: ohne '
             'dokumentierten Zweck ist weder die Nutzungsberechtigung nachweisbar '
             'noch die steuerliche Einordnung des Vorgangs (Zweckbetrieb bzw. '
             'Vermögensverwaltung) begründbar. Im Online-Formular ist die Angabe '
             'Pflicht; im Backend bleibt sie erfassbar-optional, damit die '
             'Geschäftsstelle auch unvollständige Vorgänge aufnehmen kann.',
    )
    usage_terms_accepted = fields.Boolean(
        string='Nutzungshinweise bestätigt', readonly=True, copy=False, tracking=True,
        help='Nachweis, dass der Entleiher die Nutzungshinweise zu den ausgeliehenen '
             'Artikeln bestätigt hat (Haftung, Aufsicht, Rückgabezustand). Wird beim '
             'Absenden des Online-Formulars gesetzt und ist deshalb kein Eingabefeld — '
             'der Zeitpunkt der Bestätigung steht im Chatter.',
    )

    # ------------------------------------------------------------------
    # R2: Dokumentierter Rückgabeprozess
    # ------------------------------------------------------------------
    return_checked_complete = fields.Boolean(
        string='Vollständig zurückgegeben', tracking=True,
        help='Alle Positionen inklusive Zubehör wurden bei der Rücknahme gezählt und '
             'sind vollständig. Das Häkchen dokumentiert den festgestellten Zustand — '
             'es ist KEINE Freigabebedingung: bleibt es leer, ist die Rücknahme '
             'trotzdem abschließbar, dann aber mit Rückgabevermerk.',
    )
    return_checked_clean = fields.Boolean(
        string='Gereinigt zurückgegeben', tracking=True,
        help='Das Material wurde in gereinigtem, wieder verleihbarem Zustand '
             'zurückgegeben. Auch dieses Häkchen dokumentiert nur den Zustand; kommt '
             'das Material verschmutzt zurück, bleibt es leer und der Rückgabevermerk '
             'beschreibt den Mangel.',
    )
    return_damage = fields.Boolean(
        string='Schaden festgestellt', tracking=True,
        help='Bei der Rücknahme wurde ein Schaden oder Verlust festgestellt. Wie bei '
             'jeder anderen Abweichung ist dann ein Rückgabevermerk zwingend — er ist '
             'die dokumentierte Feststellung und zugleich eine mögliche Begründung für '
             'einen Kautionseinbehalt.',
    )
    return_note = fields.Text(
        string='Rückgabevermerk',
        help='Beschreibung des Zustands bei der Rücknahme: was fehlt, was ist beschädigt, '
             'was wurde vereinbart. Pflicht, sobald eine Abweichung vorliegt '
             '(unvollständig, nicht gereinigt oder Schaden). Dient außerdem als '
             'Begründung für einen Einbehalt der Kaution — ein Einbehalt setzt eine '
             'Begründung voraus, aber nicht zwingend einen Schaden (z. B. verspätete '
             'Rückgabe oder Nichtabholung).',
    )

    # DSGVO: Merker für die Anonymisierung nach Ablauf der Aufbewahrungsfrist
    # (siehe _cron_anonymize_expired). Gleiches Muster wie kjr.grant.participant:
    # der Merker macht den Lauf idempotent, damit ein zweiter Durchlauf einen
    # bereits anonymisierten Vorgang nicht erneut anfasst.
    data_anonymized = fields.Boolean(
        string='Anonymisiert (DSGVO)', default=False, readonly=True, copy=False,
        help='Die personenbezogenen Angaben dieser Ausleihe (E-Mail, Telefon, '
             'Zweckbeschreibung, Anmerkungen und der Rückgabevermerk) wurden nach '
             'Ablauf der Aufbewahrungsfrist maschinell geleert. Zeitraum, Positionen, '
             'Gebühren und Kautionsverlauf bleiben für Auswertung und Abrechnung '
             'erhalten.',
    )

    @api.depends('partner_id', 'partner_id.is_kjr_member')
    def _compute_is_member(self):
        """Mitgliedstarif aus dem Entleiher-Kontakt ableiten.

        Die Übersteuerung durch die Geschäftsstelle bleibt erhalten: Odoo ruft den
        Compute eines gespeicherten, schreibbaren Feldes nur dann erneut auf, wenn
        sich eine Abhängigkeit ändert (hier: der Entleiher oder dessen Kennzeichen).
        Ein Wechsel des Entleihers SOLL den Tarif neu bestimmen — ab Status
        'Ausgegeben' bleibt der einmal abgerechnete Tarif dagegen eingefroren
        (analog zu KjrRentalOrderLine._compute_price).
        """
        for rec in self:
            if rec.state in ('issued', 'returned', 'cancelled'):
                # Laufende/abgeschlossene Vorgänge nicht nachträglich umtarifieren.
                # Selbstzuweisung, damit im Loop JEDEM Record ein Wert zugewiesen ist.
                rec.is_member = rec.is_member
                continue
            rec.is_member = bool(rec.partner_id.is_kjr_member)

    @api.depends('date_from', 'date_to')
    def _compute_rental_days(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_to >= rec.date_from:
                rec.rental_days = (rec.date_to - rec.date_from).days + 1
            else:
                rec.rental_days = 0

    @api.depends('line_ids.subtotal', 'line_ids.deposit_subtotal')
    def _compute_amounts(self):
        for rec in self:
            rec.amount_total = sum(rec.line_ids.mapped('subtotal'))
            rec.deposit_total = sum(rec.line_ids.mapped('deposit_subtotal'))

    def _compute_access_url(self):
        super()._compute_access_url()
        for rec in self:
            rec.access_url = f'/my/ausleihen/{rec.id}'

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_to < rec.date_from:
                raise ValidationError(_('Das Rückgabedatum darf nicht vor dem Ausleihdatum liegen.'))

    @api.model
    def _to_bool(self, value):
        """Checkbox-Werte aus dem Website-Formular robust nach Boolean wandeln.

        Ein HTML-Formular liefert 'on'/'1'/'ja' (oder das Feld fehlt ganz).
        @api.onchange feuert im Controller nicht, deshalb wird der Wert hier
        beim Schreiben normalisiert statt auf eine Onchange zu bauen.
        """
        if isinstance(value, str):
            return value.strip().lower() in ('1', 'true', 'yes', 'on', 'ja', 'checked')
        return bool(value)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('Neu'):
                vals['name'] = self.env['ir.sequence'].next_by_code('kjr.rental.order') or _('Neu')
            # usage_terms_accepted ist readonly (Nachweis, kein Eingabefeld) — über
            # create() aus dem Controller ist es dennoch setzbar; readonly wirkt nur
            # in der Oberfläche.
            if 'usage_terms_accepted' in vals:
                vals['usage_terms_accepted'] = self._to_bool(vals['usage_terms_accepted'])
        orders = super().create(vals_list)
        for order in orders:
            if order.usage_terms_accepted:
                # Bestätigung mit Zeitstempel im Chatter festhalten (Nachweischarakter).
                order.message_post(
                    body=_('Der Entleiher hat die Nutzungshinweise beim Absenden der '
                           'Anfrage bestätigt.'),
                    subtype_xmlid='mail.mt_note')
        return orders

    def write(self, vals):
        if 'usage_terms_accepted' in vals:
            vals['usage_terms_accepted'] = self._to_bool(vals['usage_terms_accepted'])
        res = super().write(vals)
        # Bei Änderung von Zeitraum/Positionen aktive Ausleihen erneut auf Verfügbarkeit prüfen,
        # damit reservierte/ausgegebene Vorgänge nicht nachträglich überbucht werden.
        if {'date_from', 'date_to', 'line_ids'} & set(vals):
            self.filtered(lambda r: r.state in ('reserved', 'issued'))._check_availability()
        return res

    def _check_availability(self):
        """Stellt sicher, dass der Gesamtbedarf je Artikel (über alle Positionen) im Zeitraum
        verfügbar ist."""
        for rec in self:
            demand = {}
            for line in rec.line_ids:
                demand[line.item_id] = demand.get(line.item_id, 0) + line.quantity
            for item, qty in demand.items():
                avail = item.quantity_available(rec.date_from, rec.date_to, exclude_order=rec)
                if qty > avail:
                    raise UserError(_(
                        'Nicht genügend verfügbar: "%(item)s" – angefragt %(req)d, verfügbar %(av)d '
                        'im Zeitraum %(df)s–%(dt)s.',
                        item=item.name, req=qty, av=avail,
                        df=rec.date_from, dt=rec.date_to,
                    ))

    def action_reserve(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Nur Anfragen können reserviert werden.'))
            if not rec.line_ids:
                raise UserError(_('Bitte mindestens eine Position hinzufügen.'))
            rec._check_availability()
            rec.state = 'reserved'

    def action_issue(self):
        for rec in self:
            if rec.state != 'reserved':
                raise UserError(_('Nur reservierte Ausleihen können ausgegeben werden.'))
            rec._check_availability()
            rec.state = 'issued'

    def _return_findings(self):
        """Abweichungen der Rücknahme als Liste von Klartexten (leer = alles in Ordnung)."""
        self.ensure_one()
        findings = []
        if not self.return_checked_complete:
            findings.append(_('nicht vollständig zurückgegeben'))
        if not self.return_checked_clean:
            findings.append(_('nicht gereinigt zurückgegeben'))
        if self.return_damage:
            findings.append(_('Schaden festgestellt'))
        return findings

    def _check_return_checklist(self):
        """R2: Die Rückgabeprüfung dokumentiert den ZUSTAND — sie ist keine Freigabe.

        Verschmutztes, unvollständiges oder beschädigtes Material muss zurückgenommen
        werden können; genau dafür ist die Rücknahme da. Würde der Abschluss gesetzte
        Häkchen voraussetzen, müsste das Personal "vollständig"/"gereinigt"
        wahrheitswidrig ankreuzen — die Checkliste verlöre den Nachweiswert, für den
        sie gebaut wurde. Verlangt wird deshalb nur: jede Abweichung braucht einen
        Rückgabevermerk, der sie beschreibt.
        """
        for rec in self:
            findings = rec._return_findings()
            if findings and not (rec.return_note or '').strip():
                raise UserError(_(
                    'Die Rücknahme von %(name)s weist Abweichungen auf (%(findings)s). '
                    'Bitte den Rückgabevermerk im Reiter "Rückgabe" ausfüllen: was fehlt, '
                    'was ist beschädigt, was wurde vereinbart. Der Vermerk ist die '
                    'dokumentierte Feststellung und zugleich die Begründung für einen '
                    'möglichen Einbehalt der Kaution. Die Häkchen bitte NICHT '
                    'wahrheitswidrig setzen, um den Abschluss zu erzwingen — sie halten '
                    'den tatsächlichen Zustand fest.',
                    name=rec.name, findings=', '.join(findings),
                ))

    def _return_check_message(self):
        """Ergebnis der Rückgabeprüfung als Chatter-Notiz (spätere Nachvollziehbarkeit)."""
        self.ensure_one()
        note = (self.return_note or '').strip()
        # Markup: message_post escapt einfache Zeichenketten, HTML muss ausdrücklich
        # als Markup übergeben werden – sonst stünden die <ul>/<li>-Tags als Text im
        # Chatter. Die eingesetzten Werte (u. a. der frei erfasste Rückgabevermerk)
        # werden von Markup.__mod__ weiterhin escaped.
        return Markup(_(
            'Rückgabeprüfung dokumentiert:'
            '<ul>'
            '<li>Vollständig zurückgegeben: %(complete)s</li>'
            '<li>Gereinigt zurückgegeben: %(clean)s</li>'
            '<li>Schaden festgestellt: %(damage)s</li>'
            '<li>Rückgabevermerk: %(note)s</li>'
            '</ul>'
        )) % {
            # Der Chatter hält den TATSÄCHLICHEN Zustand fest (ja/nein), nicht den
            # Prüffortschritt: ein "nein" ist ein gültiges Ergebnis der Rücknahme.
            'complete': _('ja') if self.return_checked_complete else _('nein'),
            'clean': _('ja') if self.return_checked_clean else _('nein'),
            'damage': _('ja') if self.return_damage else _('nein'),
            'note': note or _('–'),
        }

    def action_return(self):
        # B-cross-1: optionaler Auto-Rechnungs-Schalter via Systemparameter
        auto_invoice = str(self.env['ir.config_parameter'].sudo().get_param(
            'kjr_rental.auto_invoice_on_return', default='False')).lower() in ('1', 'true', 'yes')
        for rec in self:
            if rec.state != 'issued':
                raise UserError(_('Nur ausgegebene Ausleihen können zurückgenommen werden.'))
            # R2: erst prüfen, dann Status setzen. Geprüft wird nur, ob jede
            # festgestellte Abweichung auch beschrieben ist — der Zustand selbst
            # (unvollständig/verschmutzt/beschädigt) hindert die Rücknahme nicht.
            rec._check_return_checklist()
            findings = rec._return_findings()
            rec.state = 'returned'
            rec.message_post(body=rec._return_check_message(), subtype_xmlid='mail.mt_note')
            if findings and rec.deposit_state == 'received':
                # Bewusst KEIN automatischer Einbehalt: ob und in welcher Höhe die
                # Kaution einbehalten wird, entscheidet die Geschäftsstelle. Der
                # Rückgabevermerk dient dabei als Begründung (action_withhold_deposit).
                # Der Hinweis hängt an JEDER Abweichung, nicht nur am Schaden — auch
                # fehlende oder ungereinigte Rückgaben können einen Einbehalt tragen.
                # TODO Kundenentscheidung KJR: Soll bei Abweichungen (insbesondere
                # "Schaden festgestellt") die Kaution automatisch einbehalten werden?
                # Bis zur Klärung bleibt die konservative Variante (Hinweis +
                # manuelle Entscheidung).
                rec.message_post(
                    body=_('Abweichung dokumentiert (%(findings)s): Bitte über die '
                           'erhaltene Kaution (%(amount).2f) entscheiden — '
                           '"Kaution einbehalten" übernimmt den Rückgabevermerk als '
                           'Begründung, "Kaution erstatten" schließt den Vorgang ohne '
                           'Einbehalt ab.',
                           findings=', '.join(findings), amount=rec.deposit_total),
                    subtype_xmlid='mail.mt_note')
            # R4: Kilometerpreise lassen sich erst mit dem abgelesenen Stand bilden.
            # PROJEKTSTANDARD: im Backend nur ein Hinweis, KEINE harte Sperre — die
            # Geschäftsstelle muss eine Rücknahme auch dann abschließen können, wenn
            # der Kilometerstand nachgereicht wird.
            km_missing = rec.line_ids.filtered(
                lambda l: l.item_id.pricing_model == 'per_km' and not l.distance_km)
            if km_missing:
                rec.message_post(
                    body=_('Bei folgenden Positionen wird nach Kilometern abgerechnet, es '
                           'sind aber noch keine gefahrenen Kilometer erfasst: %(items)s. '
                           'Bitte den abgelesenen Stand in der Position nachtragen — sonst '
                           'enthält die Rechnung nur die Grundgebühr.',
                           items=', '.join(km_missing.mapped('item_id.name'))),
                    subtype_xmlid='mail.mt_note')
            if auto_invoice and km_missing and not rec.invoice_id:
                # Eine automatische Rechnung ohne erfassten Kilometerstand wäre
                # nachweislich zu niedrig und müsste storniert werden. Deshalb hier
                # bewusst zurückgestellt — die Rechnung bleibt jederzeit manuell über
                # "Rechnung erstellen" auslösbar.
                rec.message_post(
                    body=_('Die automatische Rechnung wurde zurückgestellt, weil bei '
                           'kilometerabhängigen Positionen noch keine gefahrenen '
                           'Kilometer erfasst sind. Nach dem Nachtragen bitte '
                           '"Rechnung erstellen" verwenden.'),
                    subtype_xmlid='mail.mt_note')
            elif auto_invoice and not rec.invoice_id and rec.amount_total > 0:
                # Auto-Rechnung darf die Rückgabe nicht blockieren: schlägt das Buchen fehl
                # (z. B. fehlende Kontenfindung), bleibt die Rechnung als Entwurf bestehen
                # und die Rücknahme ist trotzdem abgeschlossen.
                try:
                    rec._create_invoice(post=True)
                except Exception as exc:  # noqa: BLE001 - bewusst breit, Rückgabe schützen
                    rec.message_post(
                        body=_('Automatische Rechnung konnte nicht gebucht werden (%s). '
                               'Bitte die Rechnung manuell erstellen/buchen.') % exc,
                        subtype_xmlid='mail.mt_note')

    def action_cancel(self):
        for rec in self:
            if rec.state == 'returned':
                raise UserError(_('Zurückgegebene Ausleihen können nicht storniert werden.'))
            rec.state = 'cancelled'

    def action_reset_draft(self):
        for rec in self:
            if rec.state == 'returned':
                raise UserError(_('Zurückgegebene Ausleihen können nicht zurückgesetzt werden.'))
            rec.state = 'draft'

    def _get_fee_product(self):
        """Service-Produkt 'Verleihgebühr' (für korrekte Steuer-/Kontenfindung)."""
        return self.env.ref('kjr_rental.product_rental_fee', raise_if_not_found=False)

    def _create_invoice(self, post=False):
        """B-cross-1/BUG: Rechnung mit Service-Produkt je Position erstellen.

        Jede Position bekommt das Service-Produkt 'Verleihgebühr'; quantity*price_unit
        ergibt den Positionsbetrag, sodass Steuer- und Kontenfindung über das Produkt
        greifen (statt einer Zeile ohne product_id/Steuer).

        R4: Die Menge der Rechnungszeile folgt dem Preismodell des Artikels
        (Tage, Nächte, Stück/Pauschale, Staffel). Für 'Pro Tag' — und damit für alle
        Bestandsdaten — ergibt das unverändert Menge × Tage zum Zeilen-Grundpreis.
        Der Kilometeranteil bekommt eine EIGENE Rechnungszeile, damit auf der Rechnung
        erkennbar ist, was Grundgebühr und was Fahrleistung ist; in Summe entspricht
        beides zusammen weiterhin genau line.subtotal.
        """
        self.ensure_one()
        if self.invoice_id:
            return self.invoice_id
        if self.amount_total <= 0:
            raise UserError(_('Keine berechenbare Gebühr vorhanden.'))
        fee_product = self._get_fee_product()
        line_vals = []
        for line in self.line_ids:
            if not line.subtotal:
                continue
            units = line._billable_units()
            base_amount = line.price_unit_effective * line.quantity * units
            if base_amount:
                vals = {
                    'name': line._invoice_line_name(units),
                    'quantity': float(line.quantity) * float(units or 1),
                    'price_unit': line.price_unit_effective,
                }
                if fee_product:
                    vals['product_id'] = fee_product.id
                line_vals.append((0, 0, vals))
            km_amount = line._km_amount()
            if km_amount:
                vals = {
                    'name': _('%(item)s (gefahrene Kilometer: %(km).1f)') % {
                        'item': line.item_id.name, 'km': line.distance_km},
                    'quantity': line.distance_km,
                    'price_unit': line.price_per_km,
                }
                if fee_product:
                    vals['product_id'] = fee_product.id
                line_vals.append((0, 0, vals))
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'invoice_origin': self.name,
            'invoice_line_ids': line_vals,
        })
        self.invoice_id = move.id
        if post:
            move.action_post()
        self.message_post(body=_('Rechnung zur Ausleihe %s erstellt.') % self.name, subtype_xmlid='mail.mt_note')
        return move

    def action_create_invoice(self):
        self.ensure_one()
        if self.invoice_id:
            return self.action_view_invoice()
        self._create_invoice(post=False)
        return self.action_view_invoice()

    def action_view_invoice(self):
        self.ensure_one()
        if not self.invoice_id:
            return False
        return {
            'type': 'ir.actions.act_window', 'res_model': 'account.move',
            'res_id': self.invoice_id.id, 'view_mode': 'form', 'name': _('Rechnung'),
        }

    def action_register_deposit(self):
        """B-cross-3: Kaution als erhalten verbuchen."""
        for rec in self:
            if rec.deposit_total <= 0:
                raise UserError(_('Für diese Ausleihe ist keine Kaution vorgesehen.'))
            if rec.deposit_state != 'none':
                raise UserError(_('Die Kaution ist bereits erfasst (Status: %s).') % rec.deposit_state)
            rec.deposit_state = 'received'
            rec.deposit_paid = True
            rec.deposit_received_date = fields.Date.context_today(rec)
            rec.message_post(
                body=_('Kaution (%.2f) als erhalten verbucht.') % rec.deposit_total,
                subtype_xmlid='mail.mt_note')

    def action_refund_deposit(self):
        """B-cross-3: Kaution erstatten (Standard) – Einbehalt erfolgt manuell über das Feld."""
        for rec in self:
            if rec.deposit_state != 'received':
                raise UserError(_('Es ist keine erhaltene Kaution vorhanden, die erstattet werden kann.'))
            rec.deposit_state = 'refunded'
            rec.deposit_paid = False
            rec.deposit_refund_date = fields.Date.context_today(rec)
            rec.message_post(
                body=_('Kaution (%.2f) erstattet.') % rec.deposit_total,
                subtype_xmlid='mail.mt_note')

    def action_withhold_deposit(self, reason=None):
        """B-cross-3: Kaution einbehalten.

        R2: Der Einbehalt braucht eine dokumentierte Begründung — aber NICHT
        zwingend einen Schaden. Auch eine verspätete Rückgabe, eine Nichtabholung
        oder unvollständig/ungereinigt zurückgegebenes Material kann einen Einbehalt
        tragen. Statt einer zweiten Begründungslogik wird der Rückgabevermerk
        (return_note) verwendet, der jede dieser Feststellungen aufnehmen kann; ein
        optionaler `reason` (z. B. aus einem Aufruf im Code) hat Vorrang.

        Voraussetzung dafür ist, dass der Rückgabevermerk in der Oberfläche auch
        ohne angekreuzten Schaden erfassbar ist — siehe Hinweis in der Formularsicht
        (Reiter "Rückgabe").
        """
        for rec in self:
            if rec.deposit_state != 'received':
                raise UserError(_('Es ist keine erhaltene Kaution vorhanden, die einbehalten werden kann.'))
            justification = (reason or rec.return_note or '').strip()
            if not justification:
                raise UserError(_(
                    'Der Einbehalt der Kaution von %(name)s muss begründet sein. Bitte '
                    'den Grund im Rückgabevermerk (Reiter "Rückgabe") festhalten und '
                    'den Einbehalt danach erneut auslösen. Ein Schaden ist dafür keine '
                    'Voraussetzung — auch eine verspätete Rückgabe, eine Nichtabholung '
                    'oder unvollständig bzw. ungereinigt zurückgegebenes Material ist '
                    'eine tragfähige Begründung, sie muss nur dokumentiert sein.',
                    name=rec.name))
            rec.deposit_state = 'withheld'
            rec.deposit_paid = False
            rec.deposit_refund_date = fields.Date.context_today(rec)
            rec.message_post(
                body=_('Kaution (%(amount).2f) einbehalten. Begründung: %(reason)s',
                       amount=rec.deposit_total, reason=justification),
                subtype_xmlid='mail.mt_note')

    def action_print_contract(self):
        self.ensure_one()
        return self.env.ref('kjr_rental.action_report_rental_contract').report_action(self)


    # ══════════════════════════════════════════════════════════════════════════
    # DSGVO — AUFBEWAHRUNG / ANONYMISIERUNG (Befund K5)
    # ══════════════════════════════════════════════════════════════════════════
    #
    # Anonymisieren statt löschen, aus demselben Grund wie in kjr_grant und
    # kjr_facility: Zeitraum, Positionen, Gebühren und Kautionsverlauf werden für
    # Auswertung und Abrechnung weiter gebraucht — die Kontaktdaten und Freitexte
    # nicht. Minderjährige stehen in diesem Modul ohnehin nur als Zahl.
    #
    # Zur Frist siehe den Kommentarblock am Modulkopf: sie ist NICHT entschieden,
    # der Auslieferungszustand ist aus.

    # Felder, die beim Ablauf der Frist geleert werden. Bewusst NICHT enthalten und
    # deshalb hier begründet:
    #   • partner_id — Pflichtfeld mit ondelete='restrict' und Klammer zur Rechnung;
    #     der Entleiher-Kontakt gehört nach res.partner, nicht in die Ausleihe.
    #   • invoice_id und alles an der Rechnung — account.move ist hash-verkettet,
    #     dort wird weder gelöscht noch geändert (siehe _cron_anonymize_expired).
    #   • date_from/date_to, Positionen, Beträge, Kautionsstatus und -daten, state,
    #     is_member, usage_terms_accepted — Abrechnungs-, Zeit- und Nachweisdaten
    #     ohne Personenbezug (usage_terms_accepted ist ein reines Ja/Nein).
    #   • return_checked_complete/-clean, return_damage — Zustandskennzeichen zum
    #     Material; nur der zugehörige FREITEXT wird geleert.
    _ANONYMIZE_FIELDS = (
        'contact_email',
        'contact_phone',
        'note',          # Anmerkungen, Freitext
        'purpose',       # Zweckbeschreibung, laut Audit mittelbar personenbezogen
        'return_note',   # Rückgabevermerk, kann Klarnamen enthalten
    )

    # Feldhistorie (mail.tracking.value): Von den getrackten Feldern der Ausleihe
    # trägt nur partner_id einen Klarnamen — Odoo schreibt bei Many2one den damaligen
    # ANZEIGENAMEN als Text mit. Alle übrigen getrackten Felder (Status, Daten,
    # Kaution, Zustandskennzeichen) sind sachbezogen; die personenbezogenen Felder
    # oben tragen kein tracking=True und hinterlassen deshalb keine Historie.
    # Entfernt wird nur der Trackingwert, die zugehörige mail.message bleibt stehen.
    # TODO(DSGVO): Ob die Entleiher-Historie entfernt werden soll, ist eine Abwägung
    # (Nachweis, wem das Material überlassen war, gegen Speicherbegrenzung) — sie
    # hängt am Schalter KJR_RENTAL_TRACES_PARAM und ist im Auslieferungszustand aus.
    _ANONYMIZE_TRACKED_FIELDS = ('partner_id',)

    @api.model
    def _dsgvo_retention_years(self):
        """Aufbewahrungsfrist in Jahren aus dem Systemparameter; 0 = abgeschaltet.

        Fehlt der Parameter oder ist er nicht als ganze Zahl lesbar, gilt 0 — also
        KEINE Verarbeitung. Das ist die konservative Seite: solange der KJR keine
        Frist festgelegt hat, darf nichts passieren (TODO(KJR) am Modulkopf)."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            KJR_RENTAL_RETENTION_PARAM, '0')
        try:
            years = int(raw)
        except (TypeError, ValueError):
            _logger.warning(
                'DSGVO: Systemparameter %s ist keine ganze Zahl (%r) — die '
                'Anonymisierung der Ausleihen bleibt abgeschaltet.',
                KJR_RENTAL_RETENTION_PARAM, raw)
            return 0
        return years if years > 0 else 0

    @api.model
    def _dsgvo_cutoff_date(self):
        """Stichtag oder None, wenn keine Frist gesetzt ist.

        Jahresend-Anker wie in kjr_grant: gezählt werden volle Kalenderjahre NACH
        dem Jahr der Rückgabe. Eine Ausleihe mit Rückgabe 2027 ist bei einer Frist
        von 5 Jahren erst ab dem 01.01.2033 fällig, nicht schon im Laufe des Jahres
        2032. Bewusst die spätere Variante — zu früh anonymisieren würde eine
        etwaige Aufbewahrungspflicht verletzen."""
        years = self._dsgvo_retention_years()
        if not years:
            return None
        return date(fields.Date.today().year - years, 1, 1)

    @api.model
    def _dsgvo_batch_limit(self):
        """Technische Obergrenze je Lauf (kein fachlicher Wert)."""
        raw = self.env['ir.config_parameter'].sudo().get_param(KJR_RENTAL_BATCH_PARAM)
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            limit = 0
        return limit if limit > 0 else KJR_RENTAL_BATCH_DEFAULT

    @api.model
    def _dsgvo_traces_enabled(self):
        """Sollen auch Chatter, Feldhistorie und Anhänge mitgezogen werden?

        Ebenfalls im Auslieferungszustand AUS. Hintergrund (Audit K6): der Chatter
        ist zugleich Nachweis des Vorgangs (Rückgabeprüfung, Kautionsentscheidung);
        ob und wie weit er mit anonymisiert wird, ist eine Abwägung zwischen
        Nachweisinteresse und Speicherbegrenzung und keine Codeentscheidung.
        TODO(DSGVO): Von der Datenschutzbeauftragten entscheiden lassen."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            KJR_RENTAL_TRACES_PARAM, '0')
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
        """Die personenbezogenen Zeichenketten dieser Ausleihe einsammeln.

        Muss VOR dem Leeren der Felder laufen: danach sind die Werte nicht mehr
        rekonstruierbar und im Chatter nicht mehr auffindbar (dieselbe Grenze wie in
        kjr_grant)."""
        self.ensure_one()
        literals = set()
        for fname in self._ANONYMIZE_FIELDS:
            value = self[fname]
            if value and isinstance(value, str):
                literals.add(value.strip())
        return {lit for lit in literals if lit}

    def _dsgvo_anonymize_chatter(self, literals):
        """Klarnamen und Freitexte in den Chatter-Nachrichten schwärzen.

        Abwägung wie in kjr_grant: GELÖSCHT wird nichts. Autor, Zeitpunkt und
        Reihenfolge der Nachrichten dokumentieren den Vorgang (Ausgabe, Rücknahme,
        Kautionsentscheidung) und bleiben vollständig erhalten. Ersetzt werden nur
        die personenbezogenen Zeichenketten — und zwar genau die, die derselbe Lauf
        gerade an den Feldern geleert hat.

        Nötig ist das, weil die Rückgabeprüfung samt Rückgabevermerk zusätzlich als
        Chatter-Notiz gespiegelt wird (_return_check_message) und die Begründung des
        Kautionseinbehalts denselben Text noch einmal enthält
        (action_withhold_deposit). Ohne diesen Schritt liefe die Anonymisierung dort
        ins Leere.

        Grenze, die der Code nicht überwinden kann: Werte aus einem FRÜHEREN Lauf
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
        Entleiher steht nach einem Wechsel weiterhin als Text in der Historie.
        Entfernt wird deshalb der Trackingwert; die zugehörige mail.message bleibt
        bestehen.

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
        """Am Vorgang hängende Dateien durch einen Platzhalter ersetzen.

        kjr_rental legt derzeit selbst kein PDF am Vorgang ab (der Leihvertrag wird
        über action_print_contract nur gedruckt). Anhänge entstehen aber über den
        Chatter — z. B. ein abfotografiertes Rückgabeprotokoll oder ein Schadensfoto.
        Behandelt werden sie wie in kjr_grant: Platzhalter statt unlink(), damit der
        Nachweis erhalten bleibt, DASS etwas abgelegt war; der Personenbezug steckt
        im Inhalt und im Dateinamen, und beides wird ersetzt.

        NICHT angefasst: Anhänge an der Rechnung (account.move) — anderes res_model,
        wegen der Hash-Verkettung unberührt.

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
                'Tatsache, dass zur Ausleihe %(order)s ein Dokument abgelegt war.'
            ) % {'orig': att.name or '', 'order': self.name or ''}
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
        Ausleihen anonymisieren statt zu löschen (Befund K5).

        Bezugspunkt ist das Ende des Ausleihzeitraums (date_to) — die Rückgabe. Ein
        eigenes Rückgabedatum führt das Modell nicht; date_to ist der vertraglich
        vereinbarte Rückgabetag und damit der nächstliegende belastbare Anker. Das
        Anlagedatum wäre falsch, weil Ausleihen im Voraus erfasst werden.
        TODO(KJR): Falls das TATSÄCHLICHE Rückgabedatum als Anker gewünscht ist,
        muss dafür erst ein Feld erfasst werden — das ist eine Fachentscheidung und
        wird hier nicht unterstellt.

        Nicht erfasst werden Vorgänge im Status "Ausgegeben": ist der Rückgabetag
        lange vorbei und das Material nicht zurück, ist der Vorgang offen und die
        Erforderlichkeit besteht fort.

        Frist über den Systemparameter 'kjr_rental.order_retention_years'.
        Auslieferungszustand 0 = AUS: der Cron läuft, findet nichts und schreibt
        nichts. Es wird bewusst KEINE Frist vorbelegt (siehe Modulkopf).

        Bewusst NICHT berührt wird die Rechnung: account.move ist hash-verkettet,
        eine nachträgliche Änderung bricht die Kette. Dort stehen der
        Rechnungsempfänger (partner_id) und die Positionstexte; die Positionstexte
        kommen ohne Klarnamen aus (Artikel, Menge, Zeitraum, Kilometer), sodass der
        personenbezogene Rest vollständig über die Ausleihe anonymisierbar ist. Der
        Rechnungsempfänger selbst ist eine Frage von res.partner und account.move,
        nicht dieses Moduls.
        TODO(DSGVO): Umgang mit dem Rechnungsempfänger im Buchungsbeleg klären.
        """
        cutoff = self._dsgvo_cutoff_date()
        if not cutoff:
            # Auslieferungszustand: keine Frist festgelegt → nichts tun. Bewusst nur
            # auf Debug-Ebene, der Cron läuft monatlich.
            _logger.debug(
                'DSGVO-Anonymisierung (Verleih) ausgesetzt: %s ist nicht gesetzt.',
                KJR_RENTAL_RETENTION_PARAM)
            return
        stale = self.sudo().search([
            ('data_anonymized', '=', False),
            ('date_to', '<', cutoff),
            ('state', '!=', 'issued'),
            # Solange eine Rechnung offen oder erst im Entwurf ist, ist der Vorgang
            # nicht abgeschlossen. Ohne Rechnung greift die Bedingung nicht — deshalb
            # ausdrücklich als ODER formuliert statt über die NULL-Behandlung eines
            # 'not in' auf einem related-Feld.
            '|', ('invoice_id', '=', False),
            ('invoice_payment_state', 'not in', ('not_paid', 'in_payment', 'partial')),
        ], limit=self._dsgvo_batch_limit(), order='id')
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
            'DSGVO-Anonymisierung (Verleih): %d Ausleihen anonymisiert '
            '(Stichtag %s, Frist %d Jahre ab Rückgabe, Jahresend-Anker).',
            len(stale), cutoff, self._dsgvo_retention_years())
        if with_traces:
            _logger.info(
                'DSGVO-Anonymisierung (Verleih) Nebenschauplätze: '
                '%d Chatter-Nachrichten geschwärzt, %d Trackingwerte entfernt, '
                '%d Anhänge ersetzt.', messages, tracking, attachments)
        else:
            _logger.warning(
                'DSGVO-Anonymisierung (Verleih): Chatter, Feldhistorie und Anhänge '
                'der %d Ausleihen wurden NICHT bearbeitet (%s ist aus). Dort stehen '
                'dieselben Angaben weiterhin.',
                len(stale), KJR_RENTAL_TRACES_PARAM)


class KjrRentalOrderLine(models.Model):
    _name = 'kjr.rental.order.line'
    _description = 'Ausleihposition'
    _order = 'order_id, sequence, id'

    order_id = fields.Many2one('kjr.rental.order', string='Ausleihe', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    item_id = fields.Many2one('kjr.rental.item', string='Artikel', required=True)
    quantity = fields.Integer(string='Menge', default=1)
    price_per_day = fields.Float(
        string='Grundpreis je Einheit (€)', digits=(8, 2),
        compute='_compute_price', store=True, readonly=False,
        help='Grundpreis, der beim Anlegen der Position aus dem Artikel übernommen und '
             'ab Rechnung/Ausgabe eingefroren wird. Die Bezugsgröße (Tag, Nacht, Stück, '
             'Grundgebühr) ergibt sich aus dem Preismodell des Artikels. Der Feldname '
             'bleibt aus Bestandsgründen price_per_day.',
    )
    deposit_unit = fields.Float(string='Kaution/Stück (€)', digits=(8, 2), compute='_compute_price', store=True, readonly=False)
    # R4: Preismodell des Artikels als related-Feld, damit Formular- und Listensichten
    # die kilometer-/staffelspezifischen Spalten ein- und ausblenden können, ohne den
    # Artikel nachzuladen. Nicht gespeichert — die Wahrheit steht am Artikel.
    pricing_model = fields.Selection(
        related='item_id.pricing_model', string='Preismodell', readonly=True)
    price_per_km = fields.Float(
        string='Kilometerpreis (€/km)', digits=(8, 2),
        compute='_compute_price', store=True, readonly=False,
        help='Kilometersatz, der beim Anlegen der Position aus dem Artikel übernommen '
             'wird (0,00 € bei allen anderen Preismodellen). Wie der Grundpreis ab '
             'Rechnung/Ausgabe eingefroren.',
    )
    distance_km = fields.Float(
        string='Gefahrene Kilometer', digits=(10, 1),
        help='Nur beim Preismodell "Grundgebühr + Kilometerpreis": die bei DIESER '
             'Position insgesamt gefahrenen Kilometer über alle Stück, abgelesen bei '
             'der Rückgabe. Der Kilometeranteil wird deshalb NICHT zusätzlich mit der '
             'Menge multipliziert. Nachtragen ist auch nach der Rücknahme möglich — '
             'nach einer bereits erstellten Rechnung erscheint dazu ein Hinweis im '
             'Protokoll.',
    )
    price_unit_effective = fields.Float(
        string='Effektivpreis je Einheit (€)', digits=(8, 2),
        compute='_compute_price_unit_effective', store=True,
        help='Tatsächlich berechneter Preis je Einheit. Entspricht dem Grundpreis der '
             'Position; nur beim Preismodell "Mengenstaffel" tritt der mengenabhängige '
             'Staffelpreis an dessen Stelle.',
    )
    billable_units = fields.Integer(
        string='Berechnete Einheiten', compute='_compute_billable_units', store=False,
        help='Zahl der berechneten Tage, Nächte bzw. Pauschalen laut Preismodell des '
             'Artikels. Bei "Pro Tag" sind das die angefangenen Tage des Zeitraums.',
    )
    currency_id = fields.Many2one(related='order_id.currency_id')
    subtotal = fields.Monetary(string='Zwischensumme', compute='_compute_subtotal', store=True)
    deposit_subtotal = fields.Monetary(string='Kaution', compute='_compute_subtotal', store=True)
    # R2: Live-Verfügbarkeit im Zeitraum (today/Reservierungs-abhängig => NICHT store)
    available_in_period = fields.Integer(
        string='Verfügbar im Zeitraum', compute='_compute_available_in_period', store=False)

    @api.depends('item_id', 'order_id.date_from', 'order_id.date_to')
    def _compute_available_in_period(self):
        for rec in self:
            if rec.item_id and rec.order_id.date_from and rec.order_id.date_to:
                rec.available_in_period = rec.item_id.quantity_available(
                    rec.order_id.date_from, rec.order_id.date_to, exclude_order=rec.order_id)
            else:
                rec.available_in_period = 0

    # R2: Die Kette bleibt geschlossen, obwohl is_member jetzt selbst ein
    # gespeichertes Compute-Feld ist: ändert sich der Entleiher (oder dessen
    # Kennzeichen), rechnet Odoo erst order.is_member und dadurch auch die
    # abhängigen Zeilenpreise neu. Gleiches gilt beim manuellen Übersteuern,
    # weil auch dieser Schreibvorgang auf is_member die Abhängigen anstößt.
    #
    # B2: Der Einfrier-Schutz hängt zusätzlich an der Rechnung, nicht nur am Status.
    # Eine Rechnung kann entstehen, BEVOR/OHNE dass der Vorgang dauerhaft in einem
    # eingefrorenen Status steht: action_create_invoice prüft den Status gar nicht,
    # und ein Manager darf eine bereits fakturierte Ausleihe über action_reset_draft
    # aus 'issued' zurück auf 'Anfrage' setzen. Dort wären die Zeilenpreise wieder
    # frei — Rechnung und Auftrag liefen unbemerkt auseinander. Sobald invoice_id
    # gesetzt ist, sind die Preise deshalb ebenfalls eingefroren.
    # 'order_id.invoice_id' gehört damit in die depends-Kette; 'order_id.state'
    # bewusst NICHT: ein Statuswechsel soll keine Neuberechnung anstoßen, die von
    # der Geschäftsstelle manuell gesetzte Preise (readonly=False) überschreibt.
    # Der Status wird im Guard trotzdem gelesen — er kann nur strenger machen.
    @api.depends('item_id', 'order_id.is_member', 'order_id.invoice_id')
    def _compute_price(self):
        for rec in self:
            # Preise fakturierter bzw. ausgegebener/zurückgegebener/stornierter
            # Vorgänge nicht überschreiben (auch nicht bei programmatischen Writes
            # auf item_id/is_member).
            # ABER nur für bereits erfasste Positionen (rec._origin): eine NEU
            # hinzugefügte Zeile hat noch keinen abgerechneten Preis. Ohne Zuweisung
            # fällt Odoo bei ihr auf den Nullwert zurück – die Position stünde dann
            # still mit 0,00 € Tagespreis und 0,00 € Kaution in Rechnung und Vertrag.
            frozen = rec._prices_frozen()
            if frozen and rec._origin:
                # Selbstzuweisung statt blankem 'continue': so ist JEDEM Record im
                # Loop ein Wert zugewiesen (Odoo-Vorgabe für Compute-Methoden), und
                # der bestehende Preis bleibt erhalten.
                rec.price_per_day = rec.price_per_day
                rec.deposit_unit = rec.deposit_unit
                rec.price_per_km = rec.price_per_km
                continue
            if rec.item_id:
                rec.price_per_day = rec.item_id.price_for(rec.order_id.is_member)
                rec.deposit_unit = rec.item_id.deposit
                # Der Kilometersatz wird NUR beim Kilometermodell übernommen: ein am
                # Artikel gepflegter, aber nicht aktivierter Satz darf keine zusätzliche
                # Gebühr erzeugen. Für alle Bestandsartikel bleibt der Wert damit 0,00 €.
                rec.price_per_km = (
                    rec.item_id.price_km_for(rec.order_id.is_member)
                    if rec.item_id.pricing_model == 'per_km' else 0.0)
            else:
                rec.price_per_day = 0.0
                rec.deposit_unit = 0.0
                rec.price_per_km = 0.0

    def _prices_frozen(self):
        """Sind die Preise dieser Position eingefroren?

        Unverändert die bisherige Regel (B2): sobald eine Rechnung existiert ODER der
        Vorgang ausgegeben/zurückgegeben/storniert ist, dürfen sich übernommene Preise
        nicht mehr nachträglich ändern. Als eigene Methode, damit die neuen Computes
        exakt dieselbe Regel verwenden statt sie zu kopieren.
        """
        self.ensure_one()
        return bool(self.order_id.invoice_id) or self.order_id.state in (
            'issued', 'returned', 'cancelled')

    # R4: Der Staffelpreis hängt an der MENGE — 'quantity' gehört deshalb in die
    # depends dieses Feldes, nicht in die von _compute_price. Käme die Menge dort
    # hinein, würde jede Mengenänderung auch bei ganz normalen Tagespreis-Positionen
    # den (readonly=False) von Hand übersteuerten Zeilenpreis überschreiben — genau
    # das Verhalten, das sich für Bestandsdaten NICHT ändern darf.
    @api.depends('price_per_day', 'quantity', 'order_id.is_member',
                 'item_id.pricing_model', 'item_id.price_per_day',
                 'item_id.price_member_per_day', 'item_id.has_member_price',
                 'item_id.tier_ids.min_quantity', 'item_id.tier_ids.price',
                 'item_id.tier_ids.price_member')
    def _compute_price_unit_effective(self):
        for rec in self:
            item = rec.item_id
            if not item or item.pricing_model != 'tiered':
                # Alle übrigen Modelle (und damit sämtliche Bestandsdaten): der
                # Effektivpreis IST der Zeilen-Grundpreis, inklusive Einfrierschutz und
                # manueller Übersteuerung, die beide an price_per_day hängen.
                rec.price_unit_effective = rec.price_per_day
                continue
            # Eingefrorene Staffelposition: bereits berechneten Preis behalten.
            # Die zusätzliche Prüfung auf einen vorhandenen Wert ist wichtig, weil das
            # Feld beim Modul-Upgrade neu befüllt wird — ohne sie blieben eingefrorene
            # Altpositionen mit 0,00 € stehen.
            if rec._prices_frozen() and rec._origin and rec.price_unit_effective:
                rec.price_unit_effective = rec.price_unit_effective
                continue
            base = item.price_for(rec.order_id.is_member)
            if float_compare(rec.price_per_day, base, precision_digits=2) != 0:
                # Von Hand gesetzter Zeilenpreis hat Vorrang vor der Staffel.
                rec.price_unit_effective = rec.price_per_day
                continue
            rec.price_unit_effective = item.unit_price_for(
                rec.quantity, rec.order_id.is_member)

    def _billable_units(self):
        """Berechnete Einheiten laut Preismodell (Tage, Nächte, Pauschale)."""
        self.ensure_one()
        days = self.order_id.rental_days or 0
        if not self.item_id:
            return days
        return self.item_id.billable_units(days)

    def _km_amount(self):
        """Kilometeranteil der Position (0,00 € außerhalb des Kilometermodells).

        Bewusst OHNE Multiplikation mit der Menge: distance_km ist der insgesamt für
        diese Position gefahrene Weg (siehe Feldhilfe).
        """
        self.ensure_one()
        if not self.item_id or self.item_id.pricing_model != 'per_km':
            return 0.0
        return (self.price_per_km or 0.0) * (self.distance_km or 0.0)

    @api.depends('item_id.pricing_model', 'item_id.price_time_basis',
                 'item_id.min_billable_units', 'order_id.rental_days')
    def _compute_billable_units(self):
        for rec in self:
            rec.billable_units = rec._billable_units()

    @api.depends('price_unit_effective', 'quantity', 'deposit_unit',
                 'order_id.rental_days', 'item_id.pricing_model',
                 'item_id.price_time_basis', 'item_id.min_billable_units',
                 'price_per_km', 'distance_km')
    def _compute_subtotal(self):
        """Zwischensumme = Effektivpreis × Menge × berechnete Einheiten + Kilometeranteil.

        Für das Modell 'Pro Tag' (Default und damit alle Bestandsartikel) ist das
        rechnerisch identisch zur bisherigen Formel Tagespreis × Menge × Tage:
        price_unit_effective entspricht dort dem Zeilen-Grundpreis, billable_units den
        angefangenen Tagen und der Kilometeranteil ist 0,00 €.
        """
        for rec in self:
            units = rec._billable_units()
            rec.subtotal = rec.price_unit_effective * rec.quantity * units + rec._km_amount()
            rec.deposit_subtotal = rec.deposit_unit * rec.quantity

    def _invoice_line_name(self, units=None):
        """Bezeichnung der Rechnungszeile passend zum Preismodell."""
        self.ensure_one()
        if units is None:
            units = self._billable_units()
        item = self.item_id
        model = item.pricing_model or 'per_day'
        unit_word = (item.unit_label or '').strip() or _('Stück')
        values = {'item': item.name, 'q': self.quantity, 'u': units, 'unit': unit_word}
        if model == 'per_day':
            # Wortlaut unverändert zur bisherigen Fassung.
            return _('%(item)s (%(q)d × %(u)d Tage)') % values
        if model == 'per_night':
            return _('%(item)s (%(q)d × %(u)d Nächte)') % values
        if model == 'per_unit':
            return _('%(item)s (%(q)d %(unit)s, Pauschale)') % values
        values['kind'] = _('Grundgebühr') if model == 'per_km' else _('Mengenstaffel')
        basis = item.price_time_basis or 'flat'
        if basis == 'day':
            return _('%(item)s – %(kind)s (%(q)d × %(u)d Tage)') % values
        if basis == 'night':
            return _('%(item)s – %(kind)s (%(q)d × %(u)d Nächte)') % values
        return _('%(item)s – %(kind)s (%(q)d %(unit)s)') % values

    def write(self, vals):
        res = super().write(vals)
        if 'distance_km' in vals:
            # Der Kilometerstand wird typischerweise bei der Rücknahme nachgetragen —
            # also möglicherweise NACH einer bereits erstellten Rechnung. Die
            # Zwischensumme ändert sich dann, die Rechnung nicht. Kein harter Guard
            # (die Erfassung muss möglich bleiben), aber ein Protokolleintrag, damit
            # die Abweichung nicht unbemerkt bleibt.
            for rec in self:
                if rec.order_id.invoice_id:
                    rec.order_id.message_post(
                        body=_('Gefahrene Kilometer der Position "%(item)s" wurden nach '
                               'der Rechnungsstellung auf %(km).1f km geändert. Bitte '
                               'prüfen, ob die Rechnung angepasst werden muss.',
                               item=rec.item_id.name, km=rec.distance_km or 0.0),
                        subtype_xmlid='mail.mt_note')
        return res

    @api.constrains('quantity')
    def _check_quantity(self):
        for rec in self:
            if rec.quantity <= 0:
                raise ValidationError(_('Die Menge muss größer als 0 sein.'))
