# -*- coding: utf-8 -*-
from . import controllers, models


def post_init_hook(env):
    """Bestehende Ueberweisungs-Anbieter bekommen sofort die vollstaendige
    Bankverbindung (Kontoinhaber, IBAN, BIC, Bank) im Hinweistext."""
    env['payment.provider'].search([
        ('code', '=', 'custom'), ('custom_mode', '=', 'wire_transfer'),
    ]).action_recompute_pending_msg()
    # Prüfbericht 22.10.2026: Mailvorlagen zusätzlich mit de_DE-Fassung.
    from odoo.addons.kjr_event.lang_fill import fill_module_templates
    fill_module_templates(env, 'kjr_event_shop')
