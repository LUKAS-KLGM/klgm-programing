# -*- coding: utf-8 -*-
import logging

from . import models

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Prüft nach der Installation die Standardvorlage und den Absender.

    Ändert KEINE Daten. Das Ergebnis steht nur im Protokoll, damit beim
    Rollout sofort sichtbar ist, ob die Brücke einsatzbereit wäre. Aktiv wird
    sie erst über die Einstellungen (kjr_event_sign.enabled).
    Ins Protokoll kommen nur IDs und Ja/Nein, keine Namen oder Adressen.
    """
    template = env.ref('kjr_event_sign.sign_template_consent', raise_if_not_found=False)
    template_ok = bool(template) and env['event.event']._kjr_consent_template_ok(
        template, log=True)
    _logger.info(
        'KJR Einwilligung (Sign): Standardvorlage %s ist %s.',
        template.id if template else '-',
        'gültig' if template_ok else 'NICHT gültig')
    sender = env['event.registration']._kjr_sign_sender_candidates()
    _logger.info(
        'KJR Einwilligung (Sign): Absender mit E-Mail-Adresse %s (Benutzer %s). '
        'Die Brücke bleibt aus, bis sie in den Einstellungen eingeschaltet wird.',
        'vorhanden' if sender else 'FEHLT', sender.id if sender else '-')
