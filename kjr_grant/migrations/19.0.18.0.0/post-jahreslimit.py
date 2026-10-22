# -*- coding: utf-8 -*-
"""Gemeinsames Jahreslimit § 4.1 nachziehen (19.0.18.0.0).

Die Förderarten liegen unter noupdate="1". Das Feld year_limit_group kam nach
der Erstinstallation dazu und blieb auf Bestandsinstanzen leer; damit zählten
Anträge nach 4.1a und 4.1b nicht gemeinsam gegen die Höchstzahl pro Jahr.
Gesetzt wird 'freizeit_4_1' nur, wenn das Feld leer ist (gepflegte Werte
bleiben). Idempotent.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

GROUP = 'freizeit_4_1'
XMLIDS = ('kjr_grant.grant_type_4_1a', 'kjr_grant.grant_type_4_1b')


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    for xmlid in XMLIDS:
        grant_type = env.ref(xmlid, raise_if_not_found=False)
        if not grant_type:
            _logger.info('Migration kjr_grant 19.0.18.0.0: %s nicht gefunden.', xmlid)
            continue
        if grant_type.year_limit_group:
            _logger.info('Migration kjr_grant 19.0.18.0.0: Förderart id %s hat bereits '
                         'eine Jahreslimit-Gruppe - unverändert.', grant_type.id)
            continue
        grant_type.year_limit_group = GROUP
        _logger.info('Migration kjr_grant 19.0.18.0.0: Förderart id %s Jahreslimit-Gruppe '
                     'gesetzt.', grant_type.id)
