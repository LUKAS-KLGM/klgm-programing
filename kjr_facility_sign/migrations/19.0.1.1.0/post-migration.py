# -*- coding: utf-8 -*-
"""Rollenname „Mieter/in“ auf „Mieter:in“ umstellen (Gendern mit Doppelpunkt).

Der Satz steht in data/sign_item_role_data.xml unter noupdate="1" und erreicht
Bestandsinstanzen deshalb nicht von selbst. Geändert wird nur der exakte alte
Auslieferungswert; einen von Hand gepflegten Namen lässt das Skript stehen.
Idempotent.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    role = env.ref('kjr_facility_sign.sign_item_role_tenant', raise_if_not_found=False)
    if not role:
        return
    # name ist übersetzbar: jede Sprachfassung einzeln prüfen.
    for lang in ('en_US', 'de_DE'):
        rec = role.with_context(lang=lang)
        if rec.name == 'Mieter/in':
            rec.name = 'Mieter:in'
            _logger.info('Sign-Rolle %s (%s) in "Mieter:in" umbenannt.', role.id, lang)
