# -*- coding: utf-8 -*-
"""KJR-spezifische Erweiterung der Veranstaltung (Ferienprogramm, Schulungen)."""
from odoo import api, fields, models


class EventEvent(models.Model):
    _inherit = 'event.event'

    is_kjr = fields.Boolean(string='KJR-Veranstaltung')
    kjr_event_type = fields.Selection([
        ('ferienprogramm', 'Ferienprogramm'),
        ('juleica_course', 'Juleica-Schulung'),
        ('rescue_course', 'Rettungsschwimmer-Kurs'),
        ('other', 'Sonstige'),
    ], string='KJR-Art')
    kjr_min_age = fields.Integer(string='Mindestalter', help='0 = keine Prüfung.')
    kjr_max_age = fields.Integer(string='Höchstalter', help='0 = keine Obergrenze.')
    kjr_enforce_age_range = fields.Boolean(
        string='Altersgruppe erzwingen',
        help='Wenn aktiv, wird eine Anmeldung außerhalb der Altersgruppe hart abgewiesen '
             '(Constraint). Andernfalls wird sie nur als Warnung markiert.',
    )
    requires_parental_consent = fields.Boolean(
        string='Einwilligung Erziehungsberechtigter erforderlich',
        help='Bei Maßnahmen für Minderjährige: Einwilligung der Erziehungsberechtigten ist Pflicht. '
             'Erfassung auf der Website am besten über Veranstaltungs-Fragen (event.question) abbilden.',
    )
    is_juleica_course = fields.Boolean(string='Juleica-Ausbildung', compute='_compute_is_juleica', store=True)

    # E5/E6 – Zahlung
    payment_required = fields.Boolean(
        string='Zahlungspflichtig',
        help='Wenn aktiv, gilt die Veranstaltung als zahlungspflichtig; Anmeldungen erhalten '
             'einen offenen Zahlungsstatus statt "nicht erforderlich".',
    )

    # E9 – Schulungsanmeldung -> Rechnung
    training_product_id = fields.Many2one(
        'product.product',
        string='Schulungsprodukt (Rechnung)',
        help='Produkt, das bei zahlungspflichtigen Schulungsanmeldungen zur Rechnungserzeugung '
             'verwendet wird, wenn keine Ticket-/Verkaufslogik (event_sale) greift.',
    )

    # E4 – Kooperationspartner
    cooperation_partner_id = fields.Many2one(
        'res.partner',
        string='Kooperationspartner',
        help='Externer Partner (z. B. Verein/Schule), der über das Portal die Teilnehmerliste '
             'dieser Veranstaltung einsehen darf.',
    )
    cooperation_user_ids = fields.Many2many(
        'res.users',
        'kjr_event_cooperation_user_rel',
        'event_id',
        'user_id',
        string='Kooperations-Benutzer',
        help='Weitere Portalbenutzer mit Lesezugriff auf die Teilnehmerliste dieser Veranstaltung.',
    )

    @api.depends('kjr_event_type')
    def _compute_is_juleica(self):
        for rec in self:
            rec.is_juleica_course = rec.kjr_event_type == 'juleica_course'
