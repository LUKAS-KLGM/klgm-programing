# -*- coding: utf-8 -*-
"""Dachverband und Delegierte bei der Vereinsregistrierung (19.0.17.0.0).

Die Mailvorlage „KJR: Vereinszugehörigkeit bestätigt“
(kjr_grant.mail_template_affiliation_approved) liegt unter noupdate="1". Der
neue Absatz zur Aufnahme als Delegierte/r erreicht Bestandsinstanzen deshalb
nur über dieses Skript.

Eingefügt wird nur, wenn die Vorlage den Absatz noch nicht hat und die
ausgelieferte Grußzeile („Mit freundlichen Grüßen“) noch enthält; sonst bleibt
der gepflegte Text unangetastet und das Protokoll sagt es. Idempotent.

Einladungsvorlage zur Vollversammlung
(kjr_grant.mail_template_assembly_invitation): ausgeliefert jetzt mit
auto_delete=False, damit die versandte Mail als Nachweis im Verlauf der
Einladung bleibt. Die Vorlage ist neu in dieser Version; eine Bestandsinstanz
mit auto_delete=True gibt es nur bei einem Zwischenstand. Dort stellt dieses
Skript den Schalter um (nur diesen, der Text bleibt). Idempotent. Außerdem
ergänzt es dort den Absatz für Einladungen, die zusätzlich an die
Verbandsadresse gehen, weil nicht alle Delegierten eine E-Mail-Adresse haben
(recipient_type 'delegates_member'); gleiche Regeln wie oben (nur einfügen,
wenn der Absatz fehlt und die Grußzeile noch steht). Idempotent.

Neue Datensätze (Einladungsvorlage, Löschfrist und Cron der Anmeldungen, neue
Modelle) legt das Modulupdate selbst an. Ins Protokoll kommen nur IDs und
Zähler.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

MODULE = 'kjr_grant'
VERSION = '19.0.17.0.0'
XMLID_APPROVED = 'kjr_grant.mail_template_affiliation_approved'
XMLID_ASSEMBLY_INVITATION = 'kjr_grant.mail_template_assembly_invitation'
MARKER = 'object.delegate_partner_id'
ANCHOR = '<p>Mit freundlichen Grüßen'
DELEGATE_PARAGRAPH = (
    '<p t-if="object.delegate_partner_id">Außerdem sind Sie jetzt als Delegierte/r von '
    '<strong><t t-out="object.delegate_partner_id.name or \'\'"/></strong> für die '
    'Vollversammlung eingetragen. Die Einladungen zur Vollversammlung erhalten Sie per '
    'E-Mail.</p>\n    '
)


MARKER_INVITATION = "'delegates_member'"
INVITATION_PARAGRAPH = (
    '<p t-if="object.recipient_type == \'delegates_member\'">Diese Einladung geht auch an '
    'die Kontaktadresse Ihres Verbands, weil nicht für alle Delegierten eine '
    'E-Mail-Adresse hinterlegt ist. Bitte leiten Sie sie an diese Delegierten weiter und '
    'ergänzen Sie die E-Mail-Adressen im Portal unter „Mein Verband“.</p>\n    '
)


def _ergaenze_absatz(body, marker, paragraph):
    """Absatz vor der Grußzeile einfügen. Rückgabe: (neuer Rumpf, geändert?)."""
    if marker in body:
        return body, False
    pos = body.find(ANCHOR)
    if pos < 0:
        return body, False
    return body[:pos] + paragraph + body[pos:], True


def _ergaenze_delegiertenabsatz(body):
    """Absatz vor der Grußzeile einfügen. Rückgabe: (neuer Rumpf, geändert?)."""
    return _ergaenze_absatz(body, MARKER, DELEGATE_PARAGRAPH)


def _ziehe_genehmigungsmail_nach(env):
    template = env.ref(XMLID_APPROVED, raise_if_not_found=False)
    if not template or not template.exists():
        _logger.info('Migration %s %s: Vorlage %s nicht gefunden - übersprungen.',
                     MODULE, VERSION, XMLID_APPROVED)
        return False
    body = str(template.body_html or '')
    new_body, changed = _ergaenze_delegiertenabsatz(body)
    if not changed:
        _logger.info(
            'Migration %s %s: Vorlage id %s bereits angepasst oder gepflegt '
            '(Grußzeile nicht gefunden) - übersprungen.', MODULE, VERSION, template.id)
        return False
    template.body_html = new_body
    _logger.info('Migration %s %s: Vorlage id %s um den Delegiertenabsatz ergänzt.',
                 MODULE, VERSION, template.id)
    return True


def _behalte_einladungsmails(env):
    """auto_delete der Einladungsvorlage abschalten (Nachweis im Verlauf)."""
    template = env.ref(XMLID_ASSEMBLY_INVITATION, raise_if_not_found=False)
    if not template or not template.exists():
        _logger.info('Migration %s %s: Vorlage %s nicht gefunden - übersprungen.',
                     MODULE, VERSION, XMLID_ASSEMBLY_INVITATION)
        return False
    if not template.auto_delete:
        return False
    template.auto_delete = False
    _logger.info('Migration %s %s: Vorlage id %s behält versandte Mails (auto_delete aus).',
                 MODULE, VERSION, template.id)
    return True


def _ergaenze_einladungsabsatz(env):
    """Absatz „auch an die Verbandsadresse“ in die Einladungsvorlage einfügen."""
    template = env.ref(XMLID_ASSEMBLY_INVITATION, raise_if_not_found=False)
    if not template or not template.exists():
        _logger.info('Migration %s %s: Vorlage %s nicht gefunden - übersprungen.',
                     MODULE, VERSION, XMLID_ASSEMBLY_INVITATION)
        return False
    new_body, changed = _ergaenze_absatz(
        str(template.body_html or ''), MARKER_INVITATION, INVITATION_PARAGRAPH)
    if not changed:
        _logger.info(
            'Migration %s %s: Vorlage id %s bereits angepasst oder gepflegt '
            '(Grußzeile nicht gefunden) - übersprungen.', MODULE, VERSION, template.id)
        return False
    template.body_html = new_body
    _logger.info('Migration %s %s: Vorlage id %s um den Absatz zur Verbandsadresse ergänzt.',
                 MODULE, VERSION, template.id)
    return True


def migrate(cr, version):
    if not version:
        return  # Neuinstallation: die XML liefert bereits den neuen Stand.
    env = api.Environment(cr, SUPERUSER_ID, {})
    _ziehe_genehmigungsmail_nach(env)
    _behalte_einladungsmails(env)
    _ergaenze_einladungsabsatz(env)
