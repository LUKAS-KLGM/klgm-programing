# -*- coding: utf-8 -*-
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    kjr_activity_popup_enabled = fields.Boolean(
        string='Erinnerungen als Popup',
        default=True,
        help='Fällige und überfällige Aktivitäten (und Aufgaben-Fristen) '
             'erscheinen im Backend als großes Popup-Fenster – beim Öffnen '
             'von Odoo und danach regelmäßig, je Eintrag höchstens einmal '
             'pro Tag. Ausschalten, wenn nur die Anzeige oben in der Leiste '
             'gewünscht ist.',
    )

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + ['kjr_activity_popup_enabled']

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + ['kjr_activity_popup_enabled']
