# -*- coding: utf-8 -*-
import logging

from . import models

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Prüft nach der Installation die Standardvorlage und den Absender.

    Einzige Datenänderung (seit 19.0.1.1.0): die alte Vorlage v1 bekommt den
    Namen "… (alt, ohne Vorbefüllung)", damit sie in den Auswahllisten nicht
    als Standard erscheint (bei einem Update erledigt das die Migration
    19.0.1.1.0). Sonst steht das Ergebnis nur im Protokoll, damit beim
    Rollout sofort sichtbar ist, ob die Brücke einsatzbereit wäre. Aktiv wird
    sie erst über die Einstellungen (kjr_event_sign.enabled).
    Ins Protokoll kommen nur IDs und Ja/Nein, keine Namen oder Adressen.
    """
    env['event.event']._kjr_sign_rename_template_v1()
    # Standardvorlage seit 19.0.1.1.0: die vorbefüllte Vorlage v2.
    template = env.ref('kjr_event_sign.sign_template_consent_v2', raise_if_not_found=False)
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
