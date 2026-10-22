# -*- coding: utf-8 -*-
"""19.0.5.11.1 (Prüfbericht 22.10.2026): deutsche Fassung der Mailvorlagen.

Die Vorlagen stehen unter noupdate="1" und wurden beim Installieren nur unter
en_US gespeichert (deutscher Text, aber englischer Sprachschlüssel). Ergänzt
wird die de_DE-Fassung als Kopie, nur wo sie fehlt; bereits gepflegte deutsche
Texte bleiben unverändert (Begründung in kjr_event/lang_fill.py).
"""
from odoo import SUPERUSER_ID, api

from odoo.addons.kjr_event.lang_fill import fill_module_templates


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    fill_module_templates(env, 'kjr_event')
