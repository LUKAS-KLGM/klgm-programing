# -*- coding: utf-8 -*-
"""Standardvorlage der Einwilligung auf die vorbefüllte Vorlage v2 umstellen.

WARUM
─────
19.0.1.1.0 liefert die neue Vorlage ``kjr_event_sign.sign_template_consent_v2``
(Name des Kindes, Veranstaltung mit Zeitraum und Name der/des
Erziehungsberechtigten schreibgeschützt aus der Anmeldung). Die alte Vorlage
``sign_template_consent`` (v1) steht unter noupdate="1", ist auf der Produktion
installiert und wird NICHT verändert oder gelöscht: bereits versendete
Unterschriftsanfragen verweisen auf sie.

WAS GESCHIEHT
─────────────
Post-Migration, also nachdem die Daten des Moduls (auch v2) geladen sind. Die
Logik liegt in ``event.event._kjr_sign_switch_default_template_v2`` (dort auch
getestet):

* Systemparameter ``kjr_event_sign.default_template_id``: auf v2, wenn er leer
  ist oder auf v1 zeigt. Hat die Geschäftsstelle eine eigene Vorlage gewählt,
  bleibt sie.
* Veranstaltungen mit ``kjr_consent_sign_template_id`` = v1: auf v2.
* v1 heißt danach „Einwilligung Erziehungsberechtigte (alt, ohne
  Vorbefüllung)", sofern sie noch den ausgelieferten Namen „… (Standard)"
  trägt (``_kjr_sign_rename_template_v1``); nur der Name ändert sich.
* Versendete Anfragen bleiben unberührt.

Bei einer Neuinstallation läuft dieses Skript nicht; dort ist v2 über die
XML-ID der Rückfall in ``_kjr_consent_sign_template``, und der post_init_hook
benennt v1 um.
Ins Protokoll kommen nur IDs und Zähler.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    result = env['event.event']._kjr_sign_switch_default_template_v2()
    _logger.info('Migration kjr_event_sign 19.0.1.1.0: %s', result)
