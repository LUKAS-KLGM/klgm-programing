# -*- coding: utf-8 -*-
"""Stammdaten der KJR-Einrichtungen (Häuser/Zeltplätze), Räume und Ausstattung."""
from odoo import api, fields, models, _


class KjrFacility(models.Model):
    _name = 'kjr.facility'
    _description = 'KJR Einrichtung'
    _order = 'sequence, name'
    _inherit = ['mail.thread']

    name = fields.Char(string='Bezeichnung', required=True, tracking=True)
    code = fields.Char(string='Kürzel')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    facility_type = fields.Selection([
        ('house', 'Jugend-/Tagungshaus'),
        ('campsite', 'Zeltplatz'),
        ('other', 'Sonstige'),
    ], string='Art', default='house', required=True)
    color = fields.Integer(string='Kalenderfarbe')
    description_short = fields.Char(string='Kurzbeschreibung')
    description = fields.Html(string='Beschreibung')
    image_1920 = fields.Image(string='Bild', max_width=1920, max_height=1920)
    capacity = fields.Integer(string='Max. Personen', default=0)
    supervision_ratio = fields.Integer(
        string='Betreuungsschlüssel (TN je Betreuer)', default=6,
        help='Empfohlene Betreuung: 1 Betreuer je N Teilnehmer.',
    )
    street = fields.Char(string='Straße')
    zip = fields.Char(string='PLZ')
    city = fields.Char(string='Ort')
    responsible_user_id = fields.Many2one('res.users', string='Verantwortlich', tracking=True)
    # F7: Standard-Uhrzeiten als Stammdaten (Default für neue Buchungen).
    check_in_default_time = fields.Float(
        string='Standard-Anreisezeit', help='Default-Anreisezeit (HH:MM) für neue Buchungen.')
    check_out_default_time = fields.Float(
        string='Standard-Abreisezeit', help='Default-Abreisezeit (HH:MM) für neue Buchungen.')
    # F8: Frei konfigurierbarer Hinweis-Text für die Mail-Templates.
    mail_hint = fields.Html(
        string='Mail-Hinweis',
        help='Optionaler Hinweistext, der in den E-Mails an die Gruppe ausgegeben wird '
             '(z. B. Anfahrt, Schlüsselübergabe, Hausordnung).')
    # B-cross: optionaler Auto-Post-Schalter für erzeugte Rechnungen.
    invoice_auto_post = fields.Boolean(
        string='Rechnung automatisch buchen',
        help='Wenn aktiv, wird die aus einer Buchung erzeugte Rechnung direkt gebucht (validiert).')
    room_ids = fields.One2many('kjr.facility.room', 'facility_id', string='Räume')
    equipment_ids = fields.One2many('kjr.facility.equipment', 'facility_id', string='Ausstattung')
    bed_total = fields.Integer(string='Betten gesamt', compute='_compute_bed_total')
    booking_count = fields.Integer(string='Buchungen', compute='_compute_booking_count')
    website_published = fields.Boolean(string='Auf Website veröffentlicht', default=True)

    @api.depends('room_ids.capacity')
    def _compute_bed_total(self):
        for rec in self:
            rec.bed_total = sum(rec.room_ids.mapped('capacity'))

    def _compute_booking_count(self):
        data = self.env['kjr.facility.booking']._read_group(
            [('facility_id', 'in', self.ids)], groupby=['facility_id'], aggregates=['__count'],
        )
        mapped = {f.id: c for f, c in data}
        for rec in self:
            rec.booking_count = mapped.get(rec.id, 0)

    def action_view_bookings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Buchungen'),
            'res_model': 'kjr.facility.booking',
            'view_mode': 'list,calendar,form',
            'domain': [('facility_id', '=', self.id)],
            'context': {'default_facility_id': self.id},
        }


class KjrFacilityRoom(models.Model):
    _name = 'kjr.facility.room'
    _description = 'Raum / Bettenkontingent'
    _order = 'facility_id, sequence, name'

    facility_id = fields.Many2one('kjr.facility', string='Einrichtung', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Raum', required=True)
    capacity = fields.Integer(string='Betten', default=0)
    active = fields.Boolean(default=True)
    housekeeping_state = fields.Selection([
        ('clean', 'Gereinigt'),
        ('dirty', 'Zu reinigen'),
        ('in_progress', 'In Reinigung'),
        ('blocked', 'Gesperrt'),
    ], string='Reinigungsstatus', default='clean')


class KjrFacilityEquipment(models.Model):
    _name = 'kjr.facility.equipment'
    _description = 'Ausstattung / Zusatzleistung'
    _order = 'facility_id, sequence, name'

    facility_id = fields.Many2one('kjr.facility', string='Einrichtung', ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Bezeichnung', required=True)
    category = fields.Char(string='Kategorie')
    quantity = fields.Integer(string='Bestand', default=0)
    price_per_day = fields.Float(string='Preis/Tag (€)', digits=(8, 2))
    icon = fields.Char(string='FontAwesome-Icon', help='z. B. fa-wifi, fa-fire')
