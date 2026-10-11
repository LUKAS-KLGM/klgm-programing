# -*- coding: utf-8 -*-
"""KJR-Erweiterung der Veranstaltungsanmeldung: Minderjährige, Einwilligung, Juleica."""
import logging
from collections import defaultdict

from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)

# Status, in denen eine Anmeldung als bestaetigt gilt und eine automatische
# Rechnung entstehen darf: 'open' (registriert) und 'done' (teilgenommen).
# Der Entwurf ('draft') loest bewusst NICHTS aus - dort parkt dieses Modul auch
# die Wartelistenplaetze (siehe _kjr_waitlist_state).
KJR_AUTO_INVOICE_STATES = ('open', 'done')

# ---------------------------------------------------------------------------
# K3 (Datenschutz-Audit vom 21.08.2026) - Feldschutz auf den sensibelsten
# Angaben dieses Moduls.
#
# Odoo 19 wertet ``groups=`` am Feld SERVERSEITIG aus: die Pruefung
# ``_has_field_access``/``_check_field_access`` greift beim Lesen einzelner
# Felder, beim Schreiben und bei der Domain-Auswertung
# (odoo/orm/models.py, odoo/orm/domains.py). ``readonly=True`` oder ein
# ``invisible`` in der Ansicht ist dagegen NUR Oberflaeche und schuetzt nicht
# gegen einen direkten RPC-Aufruf.
#
# Wirkung im Betrieb:
#  * Wer die Gruppe nicht hat, bekommt die Felder in Formular und Liste gar
#    nicht mehr ausgeliefert (Odoo entfernt die Feldknoten beim Aufbereiten der
#    Ansicht) und laeuft bei direktem Lesen/Schreiben/Suchen in einen
#    AccessError.
#  * ``sudo()`` umgeht den Schutz. Gewollt ist das an genau einer Stelle: die
#    oeffentliche Online-Anmeldung schreibt diese Felder ueber ein
#    sudo-Recordset (``controllers/website_event.py``) - ohne das koennte
#    niemand von aussen eine Anmeldung absenden. LESENDE Stellen duerfen
#    deshalb nicht auf ``sudo()`` ausweichen (siehe ``controllers/portal.py``).
#  * Gespeicherte Compute-Felder rechnet Odoo als Superuser
#    (``compute_sudo`` folgt ``store``, odoo/orm/fields.py). ``has_birthdate``,
#    ``kjr_age`` und ``is_minor`` werden deshalb weiterhin korrekt berechnet,
#    obwohl ``birthdate`` geschuetzt ist. Sie bleiben bewusst ungeschuetzt: die
#    Geschaeftsstelle braucht Alter und Minderjaehrigkeit fuer Platzvergabe,
#    Einwilligungspruefung und die rein aggregierte Statistik - das
#    Geburtsdatum selbst braucht sie dafuer nicht (Datenminimierung).
#
# Wer in der Gruppe ist, entscheidet der KJR (Berechtigungskonzept, im Audit
# als offene Festlegung gefuehrt). Die Gruppe wird in
# ``security/kjr_event_security.xml`` angelegt; ``event.group_event_manager``
# schliesst sie ein, damit die Geschaeftsstelle nichts verliert.
# ---------------------------------------------------------------------------
KJR_SENSITIVE_DATA_GROUP = 'kjr_event.group_kjr_event_care'


class EventRegistration(models.Model):
    _inherit = 'event.registration'

    # Alle Felder mit KJR_SENSITIVE_DATA_GROUP sind serverseitig geschützt
    # (Befund K3) – siehe Erläuterung am Kopf der Datei.
    birthdate = fields.Date(
        string='Geburtsdatum',
        groups=KJR_SENSITIVE_DATA_GROUP,
        help='Nur für die Betreuung/Leitung der Freizeiten sichtbar. Das daraus '
             'abgeleitete Alter (Feld "Alter (bei Beginn)") bleibt für alle '
             'Veranstaltungs-Benutzer/innen sichtbar.',
    )
    has_birthdate = fields.Boolean(
        string='Geburtsdatum erfasst', compute='_compute_kjr_age', store=True,
        help='Hilfsflag, um den Sonderfall Alter 0 (z. B. Säugling) korrekt von '
             '"kein Geburtsdatum" zu unterscheiden.',
    )
    kjr_age = fields.Integer(string='Alter (bei Beginn)', compute='_compute_kjr_age', store=True)
    is_minor = fields.Boolean(string='Minderjährig', compute='_compute_kjr_age', store=True)
    # E2c (Arbeitsliste 2026-10-11) – Merkmal Geschlecht für die Meldung an das
    # Landesamt. Stufen wie im Vorbild kjr.grant.participant.gender, zusätzlich
    # 'keine Angabe', damit die bewusste Nicht-Angabe von der gar nicht erfassten
    # Angabe unterscheidbar bleibt.
    #
    # BEWUSST OHNE Feldschutz (``groups=``), anders als die übrigen Zusatzangaben
    # dieses Moduls - gleiche Begründung wie bei kjr_age/is_minor (siehe Kopf der
    # Datei): der Statistik-Assistent läuft als event.group_event_user
    # (security/ir.model.access.csv) und würde das Feld sonst nicht lesen können,
    # sondern in einen AccessError laufen. Das Merkmal wird ausschließlich
    # aggregiert gezählt, ist freiwillig, hat eine Stufe "keine Angabe" und ist
    # kein Datum nach Art. 9 DSGVO (im Unterschied zu den Ernährungs- und
    # Notfallangaben). Nicht erforderlich, kein Vorbelegungswert.
    kjr_gender = fields.Selection([
        ('male', 'männlich'),
        ('female', 'weiblich'),
        ('diverse', 'divers'),
        ('no_answer', 'keine Angabe'),
    ], string='Geschlecht',
        help='Freiwillige Angabe. Sie wird ausschließlich für die aggregierte '
             'Meldung an das Landesamt gezählt und nie einzeln ausgewiesen. '
             '"keine Angabe" bedeutet: bewusst nicht angegeben; ein leeres Feld '
             'bedeutet: nicht erfasst.',
    )
    # Bewusst OHNE Feldschutz: der Stand der Einwilligung ist ein Vorgangsmerkmal,
    # das die Geschäftsstelle für Nachfassen und Platzvergabe braucht; er enthält
    # selbst keine Gesundheits- oder Kontaktdaten.
    parental_consent = fields.Boolean(string='Einwilligung Erziehungsberechtigte')
    guardian_name = fields.Char(
        string='Erziehungsberechtigte/r',
        groups=KJR_SENSITIVE_DATA_GROUP,
        help='Kontaktdaten der Erziehungsberechtigten, nur für die Betreuung/Leitung '
             'der Freizeiten sichtbar.',
    )
    guardian_phone = fields.Char(
        string='Telefon Erziehungsberechtigte/r',
        groups=KJR_SENSITIVE_DATA_GROUP,
        help='Kontaktdaten der Erziehungsberechtigten, nur für die Betreuung/Leitung '
             'der Freizeiten sichtbar.',
    )
    emergency_contact = fields.Char(
        string='Notfallkontakt',
        groups=KJR_SENSITIVE_DATA_GROUP,
        help='Nur für die Betreuung/Leitung der Freizeiten sichtbar; wird ausschließlich '
             'für den Notfall während der Maßnahme benötigt.',
    )

    # E1/E3 – Ernährung & Bemerkungen
    # Ernährungsangabe und Freitext können Gesundheits- und Religionsdaten
    # enthalten (Allergie, halal, koscher) und sind namentlich zugeordnet –
    # deshalb ebenfalls feldgeschützt.
    dietary_requirements = fields.Selection([
        ('none', 'Keine besonderen'),
        ('vegetarian', 'Vegetarisch'),
        ('vegan', 'Vegan'),
        ('halal', 'Halal'),
        ('kosher', 'Koscher'),
        ('allergy', 'Allergie/Unverträglichkeit'),
        ('other', 'Sonstiges'),
    ], string='Ernährung',
        groups=KJR_SENSITIVE_DATA_GROUP,
        help='Nur für die Betreuung/Leitung der Freizeiten sichtbar.',
    )
    dietary_note = fields.Char(
        string='Ernährung: Hinweis',
        groups=KJR_SENSITIVE_DATA_GROUP,
        help='Freitext, in dem regelmäßig Allergien und Unverträglichkeiten stehen. '
             'Nur für die Betreuung/Leitung der Freizeiten sichtbar.',
    )
    notes = fields.Text(
        string='Bemerkungen',
        groups=KJR_SENSITIVE_DATA_GROUP,
        help='Unstrukturierter Freitext, in dem erfahrungsgemäß auch Gesundheits- und '
             'Familienangaben landen. Nur für die Betreuung/Leitung der Freizeiten sichtbar.',
    )

    consent_missing = fields.Boolean(
        string='Einwilligung fehlt', compute='_compute_consent_missing',
        store=True, search='_search_consent_missing')
    age_out_of_range = fields.Boolean(
        string='Außerhalb Altersgruppe', compute='_compute_consent_missing',
        store=True, search='_search_age_out_of_range')

    event_payment_required = fields.Boolean(related='event_id.payment_required')

    # E14 – Warteliste
    kjr_is_waitlist = fields.Boolean(
        string='Warteliste',
        help='Diese Anmeldung steht auf der Warteliste und belegt KEINEN regulären Platz. '
             'Sie wird dazu im unbestätigten Status gehalten, damit sie nicht auf die '
             'belegten Plätze (seats_taken) zählt. Das Nachrücken löst die Geschäftsstelle '
             'bewusst manuell aus (Schaltfläche "Von Warteliste nachrücken").',
    )
    kjr_waitlist_position = fields.Integer(
        string='Wartelistenplatz',
        compute='_compute_kjr_waitlist_position',
        help='Position auf der Warteliste der Veranstaltung, lückenlos ab 1 nach '
             'Anmeldezeitpunkt. 0 = steht nicht auf der Warteliste.',
    )
    event_waitlist_enabled = fields.Boolean(
        related='event_id.kjr_waitlist_enabled', string='Warteliste am Event aktiv')

    # Juleica-Ausstellung (nur bei Juleica-Schulungen)
    event_is_juleica = fields.Boolean(related='event_id.is_juleica_course')
    juleica_issued = fields.Boolean(string='Juleica ausgestellt')
    juleica_valid_until = fields.Date(
        string='Juleica gültig bis', compute='_compute_juleica_valid_until',
        store=True, readonly=False,
        help='Standardmäßig Ausstellung + 3 Jahre, kann überschrieben werden.')

    # E9 – Verknüpfte Schulungsrechnung (Dedup: keine Doppelfakturierung)
    kjr_training_invoice_id = fields.Many2one(
        'account.move', string='Schulungsrechnung', readonly=True, copy=False)

    # E5/E6 – Zahlung je Anmeldung
    kjr_payment_state = fields.Selection([
        ('not_required', 'Nicht erforderlich'),
        ('open', 'Offen'),
        ('partial', 'Teilbezahlt'),
        ('paid', 'Bezahlt'),
        ('refunded', 'Erstattet'),
    ], string='Zahlungsstatus', default='not_required',
        compute='_compute_kjr_payment_state', store=True, readonly=False)
    amount_due = fields.Monetary(string='Offener Betrag', currency_field='kjr_currency_id')
    amount_paid = fields.Monetary(string='Bezahlt', currency_field='kjr_currency_id')
    payment_date = fields.Date(string='Zahlungsdatum')
    kjr_currency_id = fields.Many2one(
        'res.currency', string='Währung',
        default=lambda self: self.env.company.currency_id.id)

    # ------------------------------------------------------------------
    # DSGVO – Merker für die Anonymisierung (Befund K5 des Audits vom 21.08.2026)
    #
    # Reines Protokollfeld: es hält fest, DASS die Anonymisierung gelaufen ist,
    # damit der Lauf idempotent bleibt (``models/event_event.py``:
    # ``_kjr_anonymize_expired_registrations`` /
    # ``_cron_kjr_anonymize_expired_registrations``
    # setzen und durchsuchen es). Das Feld trifft KEINE Aussage über eine Frist
    # und löst von sich aus nichts aus – ob und wann anonymisiert wird, steuert
    # ausschließlich der Systemparameter ``kjr_event.registration_retention_years``,
    # der im Auslieferungszustand auf 0 (= keine automatische Anonymisierung)
    # steht. Die Frist selbst ist eine offene Festlegung des KJR bzw. der
    # Datenschutzbeauftragten (TODO(KJR)/TODO(DSGVO) dort).
    #
    # Bewusst OHNE Feldschutz (``groups=``): der Merker enthält keine
    # personenbezogene Angabe, und die Geschäftsstelle muss ohne Sonderrecht
    # erkennen können, dass ein Datensatz bereits anonymisiert wurde.
    # ------------------------------------------------------------------
    kjr_data_anonymized = fields.Boolean(
        string='Daten anonymisiert', readonly=True, copy=False, index=True,
        help='Kennzeichnet, dass die personenbezogenen Angaben dieser Anmeldung '
             'nach Ablauf der vom KJR festgelegten Aufbewahrungsfrist geleert '
             'wurden. Wird ausschließlich von der Anonymisierungsroutine gesetzt; '
             'ein Zurücksetzen stellt die Daten nicht wieder her, sondern führt '
             'nur zu einem erneuten Durchlauf.')

    @api.depends('birthdate', 'event_id.date_begin')
    def _compute_kjr_age(self):
        for rec in self:
            rec.has_birthdate = bool(rec.birthdate)
            if rec.birthdate and rec.event_id.date_begin:
                start = rec.event_id.date_begin.date()
                bd = rec.birthdate
                age = start.year - bd.year - ((start.month, start.day) < (bd.month, bd.day))
                rec.kjr_age = age
                rec.is_minor = age < 18
            else:
                rec.kjr_age = 0
                rec.is_minor = False

    @api.depends('parental_consent', 'is_minor', 'kjr_age', 'has_birthdate', 'birthdate',
                 'event_id.requires_parental_consent', 'event_id.kjr_min_age', 'event_id.kjr_max_age')
    def _compute_consent_missing(self):
        for rec in self:
            ev = rec.event_id
            rec.consent_missing = bool(
                ev.requires_parental_consent and rec.is_minor and not rec.parental_consent
            )
            out = False
            if rec.has_birthdate:  # Alter 0 ist gültig – nicht auf kjr_age (falsy bei 0) prüfen
                if ev.kjr_min_age and rec.kjr_age < ev.kjr_min_age:
                    out = True
                elif ev.kjr_max_age and rec.kjr_age > ev.kjr_max_age:
                    out = True
            rec.age_out_of_range = out

    def _search_consent_missing(self, operator, value):
        # stored compute -> Standard-Suche reicht; expliziter Search-Hook für Robustheit.
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise UserError(_('Ungültige Suche auf "Einwilligung fehlt".'))
        domain_true = [
            ('event_id.requires_parental_consent', '=', True),
            ('is_minor', '=', True),
            ('parental_consent', '=', False),
        ]
        positive = (operator == '=' and value) or (operator == '!=' and not value)
        if positive:
            return domain_true
        return ['!', '&', '&'] + domain_true

    def _search_age_out_of_range(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise UserError(_('Ungültige Suche auf "Außerhalb Altersgruppe".'))
        positive = (operator == '=' and value) or (operator == '!=' and not value)
        # gestützt auf den gespeicherten Compute-Wert
        return [('age_out_of_range', '=', positive)]

    @api.depends('juleica_issued', 'event_id.date_begin')
    def _compute_juleica_valid_until(self):
        for rec in self:
            if rec.juleica_issued:
                if not rec.juleica_valid_until:
                    base = (rec.event_id.date_begin.date()
                            if rec.event_id.date_begin else fields.Date.context_today(rec))
                    rec.juleica_valid_until = base + relativedelta(years=3)
                else:
                    # Manuell gesetztes Datum unverändert lassen. Selbstzuweisung statt
                    # leerem Zweig, damit im Loop JEDEM Record ein Wert zugewiesen ist
                    # (Odoo-Vorgabe für Compute-Methoden).
                    rec.juleica_valid_until = rec.juleica_valid_until
            else:
                # Keine ausgestellte Juleica -> kein Gültigkeitsdatum (verhindert Geisterwert
                # in Report/Mail, wenn die Ausstellung wieder zurückgenommen wird).
                rec.juleica_valid_until = False

    # Hinweis: sale_order_id (aus event_sale) wird im Rumpf optional/defensiv gelesen,
    # steht aber NICHT in @api.depends, damit das Modul auch OHNE installiertes event_sale
    # lädt (sonst Registry-Fehler "Invalid field 'sale_order_id'"). Mit event_sale wird der
    # Status über amount_due/amount_paid mitgeführt.
    @api.depends('event_id.payment_required', 'amount_due', 'amount_paid')
    def _compute_kjr_payment_state(self):
        for rec in self:
            # Wenn der Status bereits manuell gesetzt wurde (z. B. erstattet), nicht überschreiben.
            if rec.kjr_payment_state == 'refunded':
                continue
            if not rec.event_id.payment_required:
                rec.kjr_payment_state = 'not_required'
                continue
            so = rec.sale_order_id if 'sale_order_id' in rec._fields else False
            if so:
                inv_states = so.invoice_ids.mapped('payment_state') if so.invoice_ids else []
                if inv_states and all(s in ('paid', 'in_payment', 'reversed') for s in inv_states):
                    rec.kjr_payment_state = 'paid'
                elif 'partial' in inv_states:
                    rec.kjr_payment_state = 'partial'
                else:
                    rec.kjr_payment_state = 'open'
                continue
            # Manuelle Logik anhand der erfassten Beträge.
            if rec.amount_paid <= 0:
                rec.kjr_payment_state = 'open'
            elif rec.amount_due > 0:
                rec.kjr_payment_state = 'partial'
            else:
                rec.kjr_payment_state = 'paid'

    @api.constrains('birthdate', 'event_id')
    def _check_age_range(self):
        for rec in self:
            ev = rec.event_id
            if not ev.kjr_enforce_age_range or not rec.has_birthdate:
                continue
            if ev.kjr_min_age and rec.kjr_age < ev.kjr_min_age:
                raise ValidationError(_(
                    'Teilnehmer/in "%(name)s" ist mit %(age)s Jahren jünger als das Mindestalter '
                    '(%(min)s) der Veranstaltung "%(event)s".',
                    name=rec.name or '', age=rec.kjr_age, min=ev.kjr_min_age, event=ev.name))
            if ev.kjr_max_age and rec.kjr_age > ev.kjr_max_age:
                raise ValidationError(_(
                    'Teilnehmer/in "%(name)s" ist mit %(age)s Jahren älter als das Höchstalter '
                    '(%(max)s) der Veranstaltung "%(event)s".',
                    name=rec.name or '', age=rec.kjr_age, max=ev.kjr_max_age, event=ev.name))

    # ------------------------------------------------------------------
    # E10 – Nachweis/Bescheinigung per Mail versenden
    # ------------------------------------------------------------------
    def action_send_certificate(self):
        """Versendet die Teilnahmebescheinigung als PDF per Mail-Vorlage."""
        template = self.env.ref('kjr_event.mail_template_certificate', raise_if_not_found=False)
        if not template:
            raise UserError(_('Die Mail-Vorlage für die Bescheinigung wurde nicht gefunden.'))
        for rec in self:
            template.send_mail(rec.id, force_send=False)
        return True

    # ------------------------------------------------------------------
    # E9 – Rechnung aus Schulungsanmeldung erzeugen
    # ------------------------------------------------------------------
    def action_create_training_invoice(self):
        """Erzeugt für zahlungspflichtige Schulungsanmeldungen eine Kundenrechnung.

        Wenn eine event_sale-Verkaufslogik (sale_order_id) vorhanden ist, sollte die
        Standard-Rechnungserzeugung über den Verkaufsauftrag genutzt werden; diese Methode
        deckt den modulseitigen Fall ohne Ticket-/Verkaufslogik ab (training_product_id).
        """
        invoices = self.env['account.move']
        for rec in self:
            if not rec.event_id.payment_required:
                continue
            if rec.kjr_training_invoice_id:
                # Bereits fakturiert -> keine Doppelrechnung.
                invoices |= rec.kjr_training_invoice_id
                continue
            if 'sale_order_id' in rec._fields and rec.sale_order_id:
                # Standardweg (event_sale) bevorzugen – hier nicht doppelt fakturieren.
                continue
            product = rec.event_id.training_product_id
            if not product:
                raise UserError(_(
                    'Für die Veranstaltung "%s" ist kein Schulungsprodukt hinterlegt.',
                    rec.event_id.name))
            partner = rec.partner_id
            if not partner:
                raise UserError(_(
                    'Anmeldung "%s" hat keinen Kontakt für die Rechnung.', rec.name or rec.id))
            move = self.env['account.move'].create({
                'move_type': 'out_invoice',
                'partner_id': partner.id,
                'invoice_origin': rec.event_id.name,
                'invoice_line_ids': [(0, 0, {
                    'product_id': product.id,
                    'name': _('%(event)s: Teilnahme %(name)s',
                              event=rec.event_id.name, name=rec.name or ''),
                    'quantity': 1.0,
                    'price_unit': product.lst_price,
                })],
            })
            rec.kjr_training_invoice_id = move.id
            invoices |= move
            # Doppelmail-Schutz: dieselbe Vorlage versendet
            # ``action_kjr_send_registration_confirm()`` ohne Merkerfeld auch von
            # Hand. Eine AUTOMATISCH ausgeloeste Rechnung darf deshalb keine Mail
            # nach sich ziehen - sonst entsteht genau der Doppelversand, der in
            # diesem Projekt schon einmal aufgetreten ist. Der Automatikpfad
            # (_kjr_auto_invoice) setzt den Kontextschluessel; Handaktion und
            # Sammelaktion verhalten sich unveraendert.
            if self.env.context.get('kjr_skip_registration_confirm_mail'):
                continue
            template = self.env.ref('kjr_event.mail_template_registration_confirm',
                                    raise_if_not_found=False)
            if template:
                template.send_mail(rec.id, force_send=False)
        if not invoices:
            return True
        return {
            'type': 'ir.actions.act_window',
            'name': _('Rechnungen'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', invoices.ids)],
        }

    # ------------------------------------------------------------------
    # E14 – Warteliste
    # ------------------------------------------------------------------
    def _kjr_waitlist_state(self):
        """Status, in dem Wartelisten-Anmeldungen gehalten werden (oder ``None``).

        Odoo 19 rechnet die Platzbelegung (seats_taken -> seats_available) nur über
        registrierte ('open') und erschienene ('done') Anmeldungen; der unbestätigte
        Status ('draft') zählt NICHT mit. Genau dort werden Wartelistenplätze geparkt –
        so blockieren sie weder sich gegenseitig noch reguläre Anmeldungen, und die
        Kern-Platzprüfung (Constraint auf den verfügbaren Plätzen) schlägt gar nicht
        erst an. Wir umgehen die Kernlogik damit nicht, sondern nutzen sie.

        Der Status wird zur Laufzeit aus der Selection gelesen: fehlt 'draft' in einer
        Odoo-Variante, wird der Status nicht angefasst (Fallback ``None``).
        """
        # TODO(KJR): Gegen den Community-Quellcode von `event` (Odoo 19) gegenprüfen –
        # der Klon unter ~/odoo-src enthält nur odoo/ und die Enterprise-Module, das
        # Community-Addon `event` liegt lokal nicht vor. Sollte Odoo 19 die belegten
        # Plätze anders zählen (z. B. unbestätigte Anmeldungen mitzählen), muss hier ein
        # anderer Status bzw. eine Erweiterung von _compute_seats gewählt werden.
        selection = self._fields['state'].selection
        if isinstance(selection, str):
            selection = getattr(self, selection)()
        elif callable(selection):
            selection = selection(self)
        keys = [key for key, _label in selection or []]
        return 'draft' if 'draft' in keys else None

    def _kjr_dispatch_waitlist(self, vals_list):
        """Verteilt neue Anmeldungen auf reguläre Plätze bzw. auf die Warteliste.

        Läuft VOR ``super().create()``: Ist die Veranstaltung voll und die Warteliste
        aktiv, wird die Anmeldung als Wartelistenplatz im unbestätigten Status angelegt,
        statt an der Platzprüfung des Kerns zu scheitern. Ohne aktive Warteliste bleibt
        der Odoo-Standard unverändert (Abweisung bzw. keine Bestätigung).
        """
        waitlist_state = self._kjr_waitlist_state()
        by_event = defaultdict(list)
        for vals in vals_list:
            if vals.get('state') == 'cancel':
                continue  # abgesagte Anmeldungen belegen keinen Platz
            if vals.get('kjr_is_waitlist'):
                # Manuell als Warteliste angelegt -> ebenfalls keinen Platz belegen.
                if waitlist_state:
                    vals['state'] = waitlist_state
                continue
            if vals.get('event_id'):
                by_event[vals['event_id']].append(vals)
        for event in self.env['event.event'].browse(list(by_event)).exists():
            if not event.kjr_waitlist_enabled:
                continue
            free = event._kjr_free_seats()
            if free is None:
                continue  # unbegrenzte Plätze -> keine Warteliste nötig
            for vals in by_event[event.id]:
                if free > 0:
                    free -= 1
                    continue
                vals['kjr_is_waitlist'] = True
                if waitlist_state:
                    vals['state'] = waitlist_state
        return vals_list

    @api.model_create_multi
    def create(self, vals_list):
        self._kjr_dispatch_waitlist(vals_list)
        registrations = super().create(vals_list)
        # Sicherheitsnetz: Odoo bestätigt neue Anmeldungen je nach Konfiguration
        # automatisch. Wartelistenplätze dürfen danach keinen Platz belegen.
        waitlist_state = self._kjr_waitlist_state()
        if waitlist_state:
            wrong = registrations.filtered(
                lambda r: r.kjr_is_waitlist and r.state not in ('cancel', waitlist_state))
            if wrong:
                wrong.write({'state': waitlist_state})
        # E1: Anmeldungen, die bereits bestätigt angelegt werden (Auto-Bestätigung
        # der Veranstaltung, Website, Backend), erreichen write() nie mit einem
        # Statuswechsel - deshalb hier derselbe Aufruf. Wartelistenplätze und
        # Entwürfe fallen in _kjr_auto_invoice_candidates heraus.
        registrations._kjr_auto_invoice()
        return registrations

    def write(self, vals):
        if vals.get('state') == 'open' and 'kjr_is_waitlist' not in vals:
            # Wer regulär registriert wird, belegt einen echten Platz und ist damit
            # kein Wartelistenplatz mehr (sonst würde seats_taken doppeldeutig).
            vals = dict(vals, kjr_is_waitlist=False)
        elif vals.get('kjr_is_waitlist') and 'state' not in vals:
            # Zurück auf die Warteliste -> Platz sofort wieder freigeben.
            waitlist_state = self._kjr_waitlist_state()
            if waitlist_state:
                vals = dict(vals, state=waitlist_state)
        # E1: Status VOR dem Schreiben festhalten, um den ÜBERGANG nach
        # bestätigt/teilgenommen zu erkennen. Nur wenn der Status überhaupt
        # geschrieben wird - im Normalbetrieb (Pflege einzelner Felder) entsteht
        # damit kein Mehraufwand.
        states_before = {rec.id: rec.state for rec in self} if 'state' in vals else None
        result = super().write(vals)
        if states_before is not None:
            switched = self.filtered(
                lambda r: r.state in KJR_AUTO_INVOICE_STATES
                and states_before.get(r.id) not in KJR_AUTO_INVOICE_STATES)
            switched._kjr_auto_invoice()
        return result

    # ------------------------------------------------------------------
    # E1 (Arbeitsliste 2026-10-11) – Rechnung automatisch bei Bestätigung
    #
    # AUSLÖSER: ``create()`` und ``write()``. Beide sind in dieser Datei schon
    # überschrieben, und jeder Statuswechsel einer Anmeldung läuft zwingend durch
    # sie (odoo/orm/models.py). Die naheliegenderen Kernmethoden
    # (``action_confirm`` / ``_action_set_*`` in addons/event) sind hier NICHT
    # verifizierbar: das Community-Addon ``event`` liegt auf dieser Maschine nicht
    # vor (dasselbe TODO steht bei ``_kjr_waitlist_state``). Statt zu raten wird
    # der verifizierbare Durchgangspunkt genommen - auf derselben Annahme ruht
    # seit E14 auch die Wartelistenlogik. Vor dem Go-live an einer echten Instanz
    # gegenprüfen.
    #
    # ERZEUGEN JA, VERSENDEN NEIN: die Rechnung entsteht als Entwurf. Versendet
    # wird weiterhin nur bewusst über ``action_kjr_send_training_invoice()``, und
    # auch der Parameter ``kjr_event.invoice_auto_send`` wird auf diesem Pfad
    # nicht ausgewertet (``allow_send=False``). Eine Rechnung, die ohne Zutun das
    # Haus verlässt, wäre eine andere Zusage als "Rechnung automatisch erzeugen".
    # Aus demselben Grund bleibt ``kjr_event.invoice_auto_post`` hier ebenfalls
    # unausgewertet (``allow_post=False``): eine gebuchte Rechnung trägt eine
    # Nummer der Rechnungssequenz, ist nicht mehr löschbar und nur über eine
    # Gutschrift zurückzudrehen. Beide Parameter gelten allein für die von Hand
    # ausgelöste Sammelaktion.
    # ------------------------------------------------------------------
    def _kjr_auto_invoice_candidates(self):
        """Anmeldungen, für die jetzt automatisch eine Rechnung entstehen darf.

        Die Bedingungen sind absichtlich eng: lieber keine Rechnung als eine
        falsche. Geprüft werden Status, Warteliste, der Schalter an der
        Veranstaltung, die Zahlungspflicht, die Freiheit von Doppelfakturierung,
        der Vorrang des Verkaufsauftrags (event_sale) sowie Produkt mit Preis
        über 0 und ein Kontakt für die Rechnung.
        """
        return self.filtered(
            lambda r: r.state in KJR_AUTO_INVOICE_STATES
            and not r.kjr_is_waitlist
            and r.event_id.kjr_auto_invoice
            and r.event_id.payment_required
            and not r.kjr_training_invoice_id
            and not ('sale_order_id' in r._fields and r.sale_order_id)
            and r.event_id.training_product_id
            and r.event_id.training_product_id.lst_price > 0
            and r.partner_id)

    def _kjr_auto_invoice(self):
        """Erzeugt die Schulungsrechnung automatisch; versendet sie NICHT.

        IDEMPOTENZ, dreifach abgesichert:
          (a) eine Anmeldung mit gesetztem ``kjr_training_invoice_id`` fällt aus
              ``_kjr_auto_invoice_candidates`` heraus;
          (b) ``_kjr_create_training_invoices`` prüft denselben Fall ein zweites
              Mal (models/kjr_event_document.py);
          (c) in ``write()`` feuert nur der ÜBERGANG nach bestätigt/teilgenommen,
              nicht jeder weitere Schreibvorgang mit demselben Status.
        Ein mehrfacher Statuswechsel kann damit keine zweite Rechnung erzeugen.

        ROBUSTHEIT: eine fehlgeschlagene Rechnungserzeugung darf die ANMELDUNG
        nicht mitnehmen. Jede Anmeldung läuft deshalb in ihrem eigenen Savepoint
        (odoo/sql_db.py: flushender Savepoint, der bei Rollback auch den
        ORM-Cache leert) - ohne ihn würde ein Fehler die ganze
        Anmeldetransaktion unbrauchbar machen, und eine Online-Anmeldung wäre
        wegen eines Buchhaltungsproblems verloren. Der Fehler wird protokolliert
        und als Notiz in den Chatter geschrieben; die Anmeldung bleibt bestehen.

        Zwei Feinheiten, die dafür nötig sind:

        * Der Savepoint wird AUSSERHALB des ``try`` geöffnet.
          ``cr.savepoint()`` liefert einen ``_FlushingSavepoint``, dessen
          ``__init__`` ZUERST ``cr.flush()`` ausführt und erst DANACH
          ``SAVEPOINT`` absetzt (odoo/sql_db.py). Scheitert schon dieser Flush
          an offenen ORM-Schreibvorgängen, gibt es gar keinen Savepoint, auf den
          zurückgerollt werden könnte - die Transaktion ist dann ohnehin
          abgebrochen. Läge der Aufruf im ``try``, würde der Fehlerzweig auf
          dieser abgebrochenen Transaktion weiterschreiben und den
          ursprünglichen Fehler hinter einem "current transaction is aborted"
          verstecken.
        * Die Rechnungserzeugung läuft mit ``sudo()`` und mit der Firma der
          Veranstaltung. ``_kjr_auto_invoice`` wird auch auf dem Website-Pfad
          ausgelöst, dort also möglicherweise von einem Portal- oder
          öffentlichen Benutzer ohne Schreibrecht auf ``account.move``. Ohne
          die Erhöhung scheitert ``account.move.create`` mit ``AccessError``,
          der Fehlerzweig fängt das ab - und es entstünde still keine Rechnung.
          Erhöht wird nur die Erzeugung, nicht die Anmeldung selbst.
        * Die Notiz im Chatter wird ebenfalls mit ``sudo()`` geschrieben. Ein
          Fehlschlag beim Schreiben der Notiz darf die Anmeldung nicht kippen -
          er wird nur protokolliert.
        """
        if self.env.context.get('kjr_auto_invoice_running'):
            return  # Rekursionsschutz: die Erzeugung schreibt selbst an der Anmeldung
        for reg in self._kjr_auto_invoice_candidates():
            # Rechte: Die Erzeugung laeuft bewusst mit Systemrechten. Ausgeloest
            # wird sie auch auf dem Website-Pfad, also moeglicherweise von einem
            # Portal- oder oeffentlichen Benutzer, der auf account.move kein
            # Schreibrecht hat - ohne sudo() scheitert account.move.create mit
            # AccessError, der Fehlerzweig unten faengt das ab und es entstuende
            # STILL KEINE Rechnung. Die Erhoehung ist auf die Rechnungserzeugung
            # begrenzt: die Anmeldung selbst wurde schon im Benutzerkontext
            # geschrieben. Die Firma kommt aus der Veranstaltung und nicht aus
            # dem Benutzer, damit die Rechnung in der richtigen Firma landet.
            reg_company = reg.event_id.company_id or reg.company_id or self.env.company
            reg_ctx = reg.sudo().with_company(reg_company).with_context(
                kjr_auto_invoice_running=True,
                kjr_skip_registration_confirm_mail=True)
            # Savepoint bewusst VOR dem try (Begründung im Docstring).
            savepoint = self.env.cr.savepoint()
            try:
                with savepoint:
                    reg_ctx._kjr_create_training_invoices(
                        allow_send=False, allow_post=False)
            except Exception as e:  # noqa: BLE001 - die Anmeldung hat Vorrang
                _logger.exception(
                    'Automatische Schulungsrechnung für Anmeldung %s (Veranstaltung %s) '
                    'fehlgeschlagen; die Anmeldung bleibt bestehen.',
                    reg.id, reg.event_id.id)
                try:
                    reg.sudo().message_post(
                        body=Markup('<p>%s</p>') % _(
                            'Die Rechnung konnte nicht automatisch erzeugt werden: '
                            '%(fehler)s. Die Anmeldung bleibt bestehen; die Rechnung '
                            'bitte von Hand erzeugen (Schaltfläche "Rechnung erstellen").',
                            fehler=str(e)),
                        subtype_xmlid='mail.mt_note')
                except Exception:  # noqa: BLE001 - die Notiz ist Nebensache
                    _logger.exception(
                        'Die Fehlernotiz zur automatischen Schulungsrechnung konnte für '
                        'Anmeldung %s nicht geschrieben werden; der Fehler steht oben im '
                        'Protokoll. Die Anmeldung bleibt bestehen.', reg.id)

    @api.depends('kjr_is_waitlist', 'state', 'event_id', 'create_date')
    def _compute_kjr_waitlist_position(self):
        """Lückenlose Position je Veranstaltung nach Anmeldezeitpunkt (FIFO).

        Bewusst nicht gespeichert: die Position verschiebt sich, sobald jemand
        nachrückt oder absagt – ein gespeicherter Wert wäre reihenweise veraltet.
        """
        positions = {}
        events = self.mapped('event_id')._origin
        if events:
            # Eine Abfrage für alle betroffenen Veranstaltungen, danach je
            # Veranstaltung lückenlos durchnummerieren.
            waiting = self.env['event.registration'].search(
                [('event_id', 'in', events.ids),
                 ('kjr_is_waitlist', '=', True),
                 ('state', '!=', 'cancel')],
                order='create_date asc, id asc',
            )
            counters = defaultdict(int)
            for reg in waiting:
                counters[reg.event_id.id] += 1
                positions[reg.id] = counters[reg.event_id.id]
        for rec in self:
            # Noch nicht gespeicherte Anmeldungen (NewId) haben keine Position.
            rec.kjr_waitlist_position = positions.get(rec._origin.id, 0) if rec.kjr_is_waitlist else 0

    def action_kjr_promote_waitlist(self):
        """Rückt die gewählte Wartelisten-Anmeldung auf einen freien Platz nach.

        Bewusst manuell: die Geschäftsstelle entscheidet, wer nachrückt (siehe
        ``event.event.action_kjr_promote_from_waitlist``).
        """
        # TODO(KJR): Mailvorlage `mail_template_waitlist_promoted` wird von der
        # Vorlagen-/Website-Zuständigkeit angelegt. Offen ist außerdem, ob Nachrücker
        # eine Zusagefrist erhalten sollen (KJR-Entscheidung, keine Zahl erfunden).
        template = self.env.ref('kjr_event.mail_template_waitlist_promoted',
                                raise_if_not_found=False)
        for rec in self:
            if not rec.kjr_is_waitlist:
                raise UserError(_(
                    'Die Anmeldung "%s" steht nicht auf der Warteliste.',
                    rec.name or rec.display_name))
            free = rec.event_id._kjr_free_seats()
            if free is not None and free <= 0:
                raise UserError(_(
                    'Für "%s" ist derzeit kein regulärer Platz frei. Bitte zuerst einen Platz '
                    'freigeben (Anmeldung absagen) oder die maximale Teilnehmerzahl erhöhen.',
                    rec.event_id.name))
            # kjr_is_waitlist und Status gemeinsam schreiben, damit die Sonderlogik in
            # write() nicht greift und der Platz sauber belegt wird.
            rec.write({'kjr_is_waitlist': False, 'state': 'open'})
            rec.message_post(body=Markup('<p>%s</p>') % _(
                'Von der Warteliste auf einen regulären Platz nachgerückt.'))
            if template:
                # Die Mailvorlage wird von der Geschäftsstelle gepflegt; fehlt sie,
                # wird nur protokolliert (kein harter Fehler beim Nachrücken).
                template.send_mail(rec.id, force_send=False)
        return True
