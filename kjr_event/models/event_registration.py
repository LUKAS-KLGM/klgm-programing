# -*- coding: utf-8 -*-
"""KJR-Erweiterung der Veranstaltungsanmeldung: Minderjährige, Einwilligung, Juleica."""
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class EventRegistration(models.Model):
    _inherit = 'event.registration'

    birthdate = fields.Date(string='Geburtsdatum')
    has_birthdate = fields.Boolean(
        string='Geburtsdatum erfasst', compute='_compute_kjr_age', store=True,
        help='Hilfsflag, um den Sonderfall Alter 0 (z. B. Säugling) korrekt von '
             '"kein Geburtsdatum" zu unterscheiden.',
    )
    kjr_age = fields.Integer(string='Alter (bei Beginn)', compute='_compute_kjr_age', store=True)
    is_minor = fields.Boolean(string='Minderjährig', compute='_compute_kjr_age', store=True)
    parental_consent = fields.Boolean(string='Einwilligung Erziehungsberechtigte')
    guardian_name = fields.Char(string='Erziehungsberechtigte/r')
    guardian_phone = fields.Char(string='Telefon Erziehungsberechtigte/r')
    emergency_contact = fields.Char(string='Notfallkontakt')

    # E1/E3 – Ernährung & Bemerkungen
    dietary_requirements = fields.Selection([
        ('none', 'Keine besonderen'),
        ('vegetarian', 'Vegetarisch'),
        ('vegan', 'Vegan'),
        ('halal', 'Halal'),
        ('kosher', 'Koscher'),
        ('allergy', 'Allergie/Unverträglichkeit'),
        ('other', 'Sonstiges'),
    ], string='Ernährung')
    dietary_note = fields.Char(string='Ernährung – Hinweis')
    notes = fields.Text(string='Bemerkungen')

    consent_missing = fields.Boolean(
        string='Einwilligung fehlt', compute='_compute_consent_missing',
        store=True, search='_search_consent_missing')
    age_out_of_range = fields.Boolean(
        string='Außerhalb Altersgruppe', compute='_compute_consent_missing',
        store=True, search='_search_age_out_of_range')

    event_payment_required = fields.Boolean(related='event_id.payment_required')

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
                    'name': _('%(event)s – Teilnahme %(name)s',
                              event=rec.event_id.name, name=rec.name or ''),
                    'quantity': 1.0,
                    'price_unit': product.lst_price,
                })],
            })
            rec.kjr_training_invoice_id = move.id
            invoices |= move
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
