# -*- coding: utf-8 -*-
"""Portalseite „Mein Konto" auch auf BESTEHENDEN Instanzen aufräumen.

Die Bereinigung hing bisher ausschließlich am post_init_hook — der läuft nur bei
einer Neuinstallation. Auf der Kundeninstanz waren die Module längst installiert,
der Hook hat deshalb nie gefeuert und alle Odoo-Standardrubriken standen weiter
auf /my (gemeldet am 21.08.2026).

Dieses Skript holt das beim Versionssprung nach. Zusätzlich gibt es die
Server-Aktion „Portalseite Mein Konto aufräumen", mit der sich die Bereinigung
jederzeit von Hand anstoßen lässt — auch dann, wenn die Modulversion schon
stimmt und dieses Skript nicht mehr läuft.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return  # Neuinstallation: der post_init_hook erledigt es.
    env = api.Environment(cr, SUPERUSER_ID, {})
    from odoo.addons.kjr_grant.hooks import cleanup_portal_home
    count = cleanup_portal_home(env)
    _logger.info('Migration 19.0.14.0.0: %d Portalrubrik(en) ausgeblendet.', count)
