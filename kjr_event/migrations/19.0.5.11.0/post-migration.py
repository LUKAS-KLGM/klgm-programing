# -*- coding: utf-8 -*-
"""19.0.5.11.0 (Termin 13.10.2026): Filter "Zielgruppe" auf der
Veranstaltungsübersicht entfernen.

Der Filter ist kein Code, sondern die veröffentlichte Schlagwort-Kategorie
"Zielgruppe" (event.tag.category). Sie wird nur unveröffentlicht, nicht
gelöscht: Schlagwörter und Zuordnungen bleiben erhalten, der KJR kann die
Kategorien danach selbst neu ordnen (Veranstaltungen → Konfiguration →
Schlagwort-Kategorien, "Auf der Website veröffentlicht").
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Category = env['event.tag.category'].with_context(active_test=False)
    if 'is_published' not in Category._fields:
        return
    categories = Category.search([('is_published', '=', True)]).filtered(
        lambda c: (c.with_context(lang='de_DE').name or '').strip().lower() == 'zielgruppe'
        or (c.with_context(lang='en_US').name or '').strip().lower() == 'zielgruppe')
    if categories:
        categories.write({'is_published': False})
        _logger.info('kjr_event 19.0.5.11.0: Schlagwort-Kategorie "Zielgruppe" (%s) auf der '
                     'Website ausgeblendet.', categories.ids)
