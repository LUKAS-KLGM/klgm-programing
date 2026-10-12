# -*- coding: utf-8 -*-
"""Link „Zuschussrichtlinien" im Antragsformular auf das echte Dokument setzen
(19.0.17.0.0, Paket A, Punkt B43).

Checkbox 2 im Antragsformular verlinkt auf ``kjr_grant.guidelines_url``. Ohne
Parameter führt der Link auf den Abschnitt „Zuschussrichtlinien" der Hilfeseite.
Auf der KJR-Instanz liegen die Richtlinien als öffentliches PDF der Website
(Zuschussseite, aus WordPress übernommen). Dieses Skript trägt dessen Adresse
ein, damit der Link ab dem Update direkt auf die Richtlinien zeigt.

Gesetzt wird nur, wenn noch keine eigene Adresse gepflegt ist (Parameter leer
oder auf der Hilfeseite) und ein öffentliches PDF mit „Zuschussrichtlinie" im
Namen existiert (``find_guidelines_attachment_url``). Sonst bleibt alles, wie es
ist, und das Protokoll nennt den Go-live-Schritt. Idempotent. Ins Protokoll
kommen nur IDs.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

MODULE = 'kjr_grant'
VERSION = '19.0.17.0.0'


def migrate(cr, version):
    if not version:
        return  # Neuinstallation: es gibt noch keine Website-Dokumente.
    env = api.Environment(cr, SUPERUSER_ID, {})
    from odoo.addons.kjr_grant.models.res_config_settings_apply import (
        PARAM_GUIDELINES_URL,
        _is_help_page,
        find_guidelines_attachment_url,
    )
    params = env['ir.config_parameter'].sudo()
    current = (params.get_param(PARAM_GUIDELINES_URL) or '').strip()
    if current and not _is_help_page(current):
        _logger.info('Migration %s %s: Link zu den Zuschussrichtlinien ist bereits '
                     'gepflegt - übersprungen.', MODULE, VERSION)
        return
    url = find_guidelines_attachment_url(env)
    if not url:
        _logger.warning(
            'Migration %s %s: Kein öffentliches PDF „Zuschussrichtlinien" gefunden. '
            'Go-live-Schritt: Einstellungen > KJR > „Link zu den Zuschussrichtlinien" '
            'pflegen; bis dahin führt der Link auf die Hilfeseite.', MODULE, VERSION)
        return
    params.set_param(PARAM_GUIDELINES_URL, url)
    _logger.info('Migration %s %s: Link zu den Zuschussrichtlinien auf Anhang %s gesetzt.',
                 MODULE, VERSION, url.split('/')[3])
