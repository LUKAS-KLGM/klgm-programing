# -*- coding: utf-8 -*-
"""Einrichtung: digitale Vertragsunterschrift je Einrichtung abschaltbar."""
from odoo import fields, models


class KjrFacility(models.Model):
    _inherit = 'kjr.facility'

    # Negativform: nach der Installation steht der Wert für alle Einrichtungen
    # auf False, es ist keine Datenpflege nötig (Muster invoice_auto_post).
    kjr_sign_disabled = fields.Boolean(
        string='Vertrag nicht digital unterschreiben', default=False,
        help='Nur wirksam, wenn in den Einstellungen „Vertrag digital unterschreiben“ '
             'eingeschaltet ist. Ein: Für diese Einrichtung geht der Vertrag wie bisher '
             'als PDF per Mail.')
