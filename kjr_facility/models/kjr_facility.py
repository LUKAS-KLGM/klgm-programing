# -*- coding: utf-8 -*-
"""Stammdaten der KJR-Einrichtungen (Häuser/Zeltplätze), Räume und Ausstattung."""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


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
    # F1: Buchungsregeln je Einrichtung. Die eigentliche Prüfung passiert in der
    # Buchung bzw. im Website-Formular — hier stehen nur die Stammdaten.
    # TODO KJR: Die konkreten Werte je Einrichtung (Diepolz: 20 Personen / 2 Nächte /
    # nur organisierte Gruppen; Naturfreundehaus Sonthofen "NiSo": noch offen) sind
    # vom KJR schriftlich zu bestätigen und danach in data/kjr_facility_data.xml zu
    # hinterlegen. Bis dahin bleiben die Defaults bewusst auf 0 = keine Prüfung.
    max_advance_months = fields.Integer(
        string='Max. Buchungsvorlauf (Monate)', default=18,
        help='Vorstandsbeschluss vom 21.07.2026: Buchungen werden höchstens 18 Monate '
             'im Voraus angenommen. Der Wert begrenzt, wie weit das Anreisedatum in der '
             'Zukunft liegen darf. 0 = unbegrenzt (keine Prüfung).')
    min_persons = fields.Integer(
        string='Mindestbelegung (Personen)', default=0,
        help='Kleinste Gruppengröße, die die Einrichtung aufnimmt (Diepolz laut '
             'öffentlicher Ausschreibung: ab 20 Personen). Gezählt werden Teilnehmer '
             'und Betreuer zusammen. 0 = keine Prüfung.')
    min_nights = fields.Integer(
        string='Mindestaufenthalt (Nächte)', default=0,
        help='Kleinste Aufenthaltsdauer in Nächten (Diepolz laut öffentlicher '
             'Ausschreibung: mindestens 2 Nächte). 0 = keine Prüfung.')
    requires_organized_group = fields.Boolean(
        string='Nur organisierte Jugend-/Bildungsgruppen', default=False,
        help='Wenn aktiv, wird die Einrichtung ausschließlich an organisierte Jugend-, '
             'Schul- und Bildungsgruppen vergeben (kein privater Familien- oder '
             'Vereinsausflug). Die Buchung erfasst dazu das Kennzeichen '
             '"Organisierte Jugend-/Bildungsgruppe".')
    room_ids = fields.One2many('kjr.facility.room', 'facility_id', string='Räume')
    equipment_ids = fields.One2many('kjr.facility.equipment', 'facility_id', string='Ausstattung')
    bed_total = fields.Integer(string='Betten gesamt', compute='_compute_bed_total')
    # Ein Zeltplatz hat keine Betten. Ohne diese Unterscheidung warb NiSo auf der
    # Website mit „40 Betten" (Befund Marvin Gutknecht, 17.08.2026). Die Zahl stimmt,
    # nur die Beschriftung war falsch.
    capacity_label = fields.Char(
        string='Bezeichnung der Kapazität', compute='_compute_capacity_label',
        help='„Betten" bei Häusern, „Plätze" bei Zeltplätzen — für Website und Listen.',
    )
    booking_count = fields.Integer(string='Buchungen', compute='_compute_booking_count')
    website_published = fields.Boolean(string='Auf Website veröffentlicht', default=True)

    @api.depends('facility_type')
    def _compute_capacity_label(self):
        for rec in self:
            rec.capacity_label = _('Plätze') if rec.facility_type == 'campsite' else _('Betten')

    # Die Abhängigkeit gehört an DIESE Methode: gestapelte @api.depends überschreiben
    # sich gegenseitig (attrsetter '_depends'), dadurch hing 'room_ids.capacity'
    # fälschlich an _compute_capacity_label und 'bed_total' wurde bei einer
    # Kapazitätsänderung nicht neu berechnet.
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

    @api.constrains('max_advance_months', 'min_persons', 'min_nights', 'capacity')
    def _check_booking_rules(self):
        """Buchungsregeln dürfen nie negativ sein — 0 ist der Aus-Schalter."""
        for rec in self:
            if rec.max_advance_months < 0:
                raise ValidationError(_(
                    'Der maximale Buchungsvorlauf darf nicht negativ sein '
                    '(0 = unbegrenzt).'))
            if rec.min_persons < 0:
                raise ValidationError(_(
                    'Die Mindestbelegung darf nicht negativ sein (0 = keine Prüfung).'))
            if rec.min_nights < 0:
                raise ValidationError(_(
                    'Der Mindestaufenthalt darf nicht negativ sein (0 = keine Prüfung).'))
            if rec.capacity and rec.min_persons > rec.capacity:
                raise ValidationError(_(
                    'Die Mindestbelegung (%(min)s) ist größer als die maximale '
                    'Personenzahl (%(max)s) der Einrichtung "%(name)s". '
                    'So kann keine Buchung mehr angelegt werden.',
                    min=rec.min_persons, max=rec.capacity, name=rec.name or ''))

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
