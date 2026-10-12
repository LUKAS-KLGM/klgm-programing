# -*- coding: utf-8 -*-
"""Bestandskonten unter Mitgliedsverbänden als genehmigte Vereinsregistrierung
übernehmen (19.0.16.0.0).

Seit dieser Version entsteht die Zuordnung einer neu registrierten Person zu
einem Verband erst durch die Genehmigung der Geschäftsstelle. Wer schon heute
als aktiver Portalzugang unter einem KJR-Mitgliedsverband hängt, gilt als
genehmigt und bekommt einen Nachweis mit Herkunft „Bestandsübernahme“. Maßstab
wie für die Rechte (Mitgliedsverband im Teilbaum des commercial partners, also
auch unter einem Dachverband ohne eigene Mitgliedschaft).
Ins Protokoll kommen nur Zähler.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return  # Neuinstallation: der post_init_hook erledigt es.
    env = api.Environment(cr, SUPERUSER_ID, {})
    from odoo.addons.kjr_grant.hooks import backfill_affiliation_requests
    _logger.info('Migration 19.0.16.0.0: %d Bestandskonto(en) als genehmigt übernommen.',
                 backfill_affiliation_requests(env))
