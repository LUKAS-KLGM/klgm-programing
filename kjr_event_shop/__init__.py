# -*- coding: utf-8 -*-
from . import models


def post_init_hook(env):
    """Bestehende Ueberweisungs-Anbieter bekommen sofort die vollstaendige
    Bankverbindung (Kontoinhaber, IBAN, BIC, Bank) im Hinweistext."""
    env['payment.provider'].search([
        ('code', '=', 'custom'), ('custom_mode', '=', 'wire_transfer'),
    ]).action_recompute_pending_msg()
