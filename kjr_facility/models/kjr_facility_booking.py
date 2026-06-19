# -*- coding: utf-8 -*-
"""Einrichtungsbuchung mit Workflow, Preis-/Steuerberechnung und Rechnungsstellung."""
import base64
import logging
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


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
    amount_meals = fields.Monetary(string='Verpflegung', compute='_compute_amounts', store=True)
    amount_equipment = fields.Monetary(string='Ausstattung', compute='_compute_amounts', store=True)
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

    @api.depends(
        'nights', 'participant_count', 'meal_option', 'tariff_id',
        'tariff_id.price_per_person_night', 'tariff_id.price_flat_per_night',
        'tariff_id.meal_breakfast', 'tariff_id.meal_half', 'tariff_id.meal_full',
        'tariff_id.tax_id', 'equipment_ids', 'equipment_ids.price_per_day',
        'company_id', 'company_id.currency_id',
    )
    def _compute_amounts(self):
        for rec in self:
            t = rec.tariff_id
            nights = rec.nights or 0
            pax = rec.participant_count or 0
            accommodation = nights * (pax * (t.price_per_person_night if t else 0.0)
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
            rec.amount_accommodation = accommodation
            rec.amount_meals = meals
            rec.amount_equipment = equipment
            # Steuer positionsweise berechnen, damit die Buchungsbeträge exakt mit der
            # später erzeugten Rechnung (Rundung je Position) übereinstimmen.
            currency = rec.company_id.currency_id or self.env.company.currency_id
            taxes = t.tax_id if t else self.env['account.tax']
            untaxed = tax = 0.0
            for component in (accommodation, meals, equipment):
                if not component:
                    continue
                res = taxes.compute_all(component, currency=currency, quantity=1.0)
                untaxed += res['total_excluded']
                tax += res['total_included'] - res['total_excluded']
            rec.amount_untaxed = untaxed
            rec.amount_tax = tax
            rec.amount_total = untaxed + tax

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

    @api.constrains('room_ids', 'check_in', 'check_out', 'state')
    def _check_double_booking(self):
        for rec in self:
            if rec.state == 'cancelled' or not rec.room_ids or not (rec.check_in and rec.check_out):
                continue
            conflicting = self.search([
                ('id', '!=', rec.id),
                ('state', '!=', 'cancelled'),
                ('room_ids', 'in', rec.room_ids.ids),
                ('check_in', '<', rec.check_out),
                ('check_out', '>', rec.check_in),
            ], limit=1)
            if conflicting:
                raise ValidationError(_(
                    'Raum-Doppelbelegung: Mindestens ein gewählter Raum ist im Zeitraum '
                    'bereits durch Buchung %(other)s belegt.',
                    other=conflicting.name,
                ))

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
            lines.append((0, 0, {
                'name': _('Unterkunft %(fac)s, %(n)d Nächte, %(p)d Pers. (%(ci)s–%(co)s)') % {
                    'fac': self.facility_id.name, 'n': self.nights, 'p': self.participant_count,
                    'ci': self.check_in, 'co': self.check_out,
                },
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
            rec.state = 'done'
            # Belegte Räume zur Reinigung markieren.
            rec.room_ids.filtered(lambda r: r.housekeeping_state != 'blocked').write(
                {'housekeeping_state': 'dirty'})

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

    @api.model
    def _cron_booking_reminder(self):
        """Erinnerung ~14 Tage vor Anreise an aktive Buchungen.

        F5: Datums-RANGE statt '==' (robust bei Cron-Aussetzern) plus Dedup über
        die Activity-Existenz, damit nicht mehrfach erinnert wird."""
        today = fields.Date.today()
        window_start = today + timedelta(days=13)
        window_end = today + timedelta(days=15)
        bookings = self.search([
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
        bookings = self.search([
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
        bookings = self.search([
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
        bookings = self.search([
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
