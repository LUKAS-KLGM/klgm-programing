# -*- coding: utf-8 -*-
"""Anrede und Gendern in ausgelieferten Texten (19.0.18.0.0).

Entscheidung des KJR vom 13.10.2026: Anrede „Sie“, Gendern mit Doppelpunkt und
Kleinbuchstabe (Antragsteller:in). Mailvorlagen und Förderarten liegen unter
noupdate="1"; die Textänderungen in den XML-Dateien erreichen Bestandsinstanzen
deshalb nur über dieses Skript.

Ersetzt werden ausschließlich die genau so ausgelieferten Teilstücke
(REPLACEMENTS). Hat die Geschäftsstelle einen Text im Backend umformuliert,
findet das Skript das Teilstück nicht und lässt den Text stehen. Mailvorlagen
werden in jeder gespeicherten Sprachfassung (jsonb) einzeln bearbeitet.
Idempotent. Ins Protokoll kommen nur IDs und Zähler.
"""
import json
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

MODULE = 'kjr_grant'
VERSION = '19.0.18.0.0'

MAIL_TEMPLATE_XMLIDS = (
    'kjr_grant.mail_template_grant_submitted',
    'kjr_grant.mail_template_grant_approved',
    'kjr_grant.mail_template_grant_rejected',
    'kjr_grant.mail_template_affiliation_approved',
)
MAIL_REPLACEMENTS = (
    ('Sehr geehrte/r ', 'Guten Tag '),
    ("'Antragsteller/in'", "'Antragsteller:in'"),
    ('als Delegierte/r von', 'als Delegierte:r von'),
)

GRANT_TYPE_REPLACEMENTS = {
    'kjr_grant.grant_type_4_1a': (
        ('5 € pro Teilnehmer,', '5 € pro Teilnehmer:in,'),
    ),
    'kjr_grant.grant_type_4_9': (
        ('Jeder stimmberechtigte Delegierte, der zur KJR-Vollversammlung anreist, erhält',
         'Alle stimmberechtigten Delegierten, die zur KJR-Vollversammlung anreisen, erhalten'),
        ('je Mitfahrer/in;', 'je Mitfahrer:in;'),
        ('auf das Konto des/der Delegierten', 'auf das Konto der delegierten Person'),
    ),
}


def ersetze(text, replacements):
    """Reine Textfunktion. Rückgabe: (neuer Text, Anzahl ersetzter Teilstücke)."""
    if not text:
        return text, 0
    count = 0
    for old, new in replacements:
        if old in text:
            count += text.count(old)
            text = text.replace(old, new)
    return text, count


def _mail_templates(env):
    env.flush_all()  # gelesen wird roh per SQL
    for xmlid in MAIL_TEMPLATE_XMLIDS:
        template = env.ref(xmlid, raise_if_not_found=False)
        if not template:
            _logger.info('Migration %s %s: %s nicht gefunden - übersprungen.', MODULE, VERSION, xmlid)
            continue
        env.cr.execute('SELECT body_html FROM mail_template WHERE id = %s', (template.id,))
        raw = env.cr.fetchone()[0] or {}
        if isinstance(raw, str):
            raw = json.loads(raw)
        total = 0
        for lang, body in list(raw.items()):
            raw[lang], count = ersetze(body, MAIL_REPLACEMENTS)
            total += count
        if total:
            env.cr.execute('UPDATE mail_template SET body_html = %s::jsonb WHERE id = %s',
                           (json.dumps(raw), template.id))
            template.invalidate_recordset(['body_html'])
        _logger.info('Migration %s %s: Mailvorlage id %s, %s Stelle(n) angepasst.',
                     MODULE, VERSION, template.id, total)


def _grant_types(env):
    for xmlid, replacements in GRANT_TYPE_REPLACEMENTS.items():
        grant_type = env.ref(xmlid, raise_if_not_found=False)
        if not grant_type:
            _logger.info('Migration %s %s: %s nicht gefunden - übersprungen.', MODULE, VERSION, xmlid)
            continue
        new_text, count = ersetze(grant_type.description, replacements)
        if count:
            grant_type.description = new_text
        _logger.info('Migration %s %s: Förderart id %s, %s Stelle(n) angepasst.',
                     MODULE, VERSION, grant_type.id, count)


def migrate(cr, version):
    if not version:
        return  # Neuinstallation: die XML liefert bereits den neuen Stand.
    env = api.Environment(cr, SUPERUSER_ID, {})
    _mail_templates(env)
    _grant_types(env)
