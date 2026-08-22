# -*- coding: utf-8 -*-
"""Aufräumen der Portalseite „Mein Konto" als aufrufbare Modellmethode.

Die eigentliche Logik steht in kjr_grant/hooks.py, weil sie auch der
post_init_hook und das Migrationsskript brauchen. Hier liegt nur der Einstieg
für die Server-Aktion.

WARUM ÜBERHAUPT DIESE DATEI: Der Code eines ir.actions.server läuft in Odoos
safe_eval, und das verbietet die Opcodes IMPORT_NAME und IMPORT_FROM. Ein
'from odoo.addons.kjr_grant.hooks import ...' direkt im Aktions-Code lässt die
Datendatei beim Laden mit einem ParseError scheitern — und damit das gesamte
Modul-Update. Genau das ist am 22.08.2026 auf der Kundeninstanz passiert.
In der Aktion steht deshalb nur noch 'action = model.kjr_cleanup_portal_home()';
'model' und 'env' sind in safe_eval verfügbar, Importe nicht.
"""
from odoo import _, api, models

from ..hooks import cleanup_portal_home


class IrUiView(models.Model):
    _inherit = 'ir.ui.view'

    @api.model
    def kjr_cleanup_portal_home(self):
        """Nicht benötigte Standardrubriken auf /my ausblenden.

        Aufrufbar über die Server-Aktion „Portalseite Mein Konto aufräumen"
        (Einstellungen ▸ Technisch ▸ Aktionen). Der einzige Weg, der auf einer
        bereits installierten Instanz funktioniert: der post_init_hook läuft nur
        bei einer Neuinstallation, das Migrationsskript nur beim Versionssprung.

        Gibt eine Benachrichtigung zurück, damit die Geschäftsstelle sieht, ob
        etwas passiert ist — eine Aktion ohne Rückmeldung lässt den Anwender im
        Unklaren, ob sie überhaupt gelaufen ist.
        """
        count = cleanup_portal_home(self.env)
        if count:
            message = _('%d nicht benötigte Rubrik(en) ausgeblendet.', count)
        else:
            message = _('Es gab nichts auszublenden.')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Portalseite „Mein Konto"'),
                'message': message,
                'type': 'success',
                'sticky': False,
            },
        }
