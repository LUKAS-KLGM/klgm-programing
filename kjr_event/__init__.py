# -*- coding: utf-8 -*-
from . import models
from . import controllers
from . import wizard


def post_init_hook(env):
    """Neuinstallation: Mailvorlagen bekommen zusätzlich die de_DE-Fassung
    (Prüfbericht 22.10.2026, Begründung in lang_fill.py)."""
    from .lang_fill import fill_module_templates
    fill_module_templates(env, 'kjr_event')
