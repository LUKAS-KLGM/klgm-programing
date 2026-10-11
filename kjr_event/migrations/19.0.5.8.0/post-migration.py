# -*- coding: utf-8 -*-
"""Nachzug der Betreffkorrektur an der Einwilligungs-Erinnerung.

WARUM DIESES SKRIPT NÖTIG IST
─────────────────────────────
``data/mail_templates.xml`` steht seit 19.0.5.8.0 unter ``<data noupdate="1">``
(Begründung im Kopf der Datei: die Geschäftsstelle pflegt Betreff und Rumpf im
Backend, ein Modul-Update darf diese Pflege nicht stillschweigend
zurückschreiben). Odoo überspringt solche Datensätze im Update-Modus
vollständig — ``odoo/tools/convert.py``: ``if self.noupdate and self.mode !=
'init':`` mit anschließendem ``return None``. Die in 19.0.5.7.0 vorgenommene
Textkorrektur am Betreff der Einwilligungs-Erinnerung erreicht bestehende
Datenbanken damit NICHT mehr von allein.

WARUM DER ORDNER DIE NEUE MANIFESTVERSION TRÄGT
───────────────────────────────────────────────
``odoo/modules/migration.py`` führt ein Skript nur aus, wenn seine Ordnerversion
STRIKT GRÖSSER als die installierte und kleiner/gleich der neuen
Manifestversion ist. Ein Ordner mit der bereits installierten Nummer läuft nie.
Wird das Manifest später erneut angehoben, wandert dieser Ordner mit.

WARUM NICHT EINFACH DEN AUSLIEFERUNGSWERT ZURÜCKSCHREIBEN
─────────────────────────────────────────────────────────
Weil genau das der Fehler wäre, gegen den ``noupdate`` schützt. Geschrieben wird
deshalb nur, wenn im Feld noch WÖRTLICH der alte Auslieferungswert steht (Muster
aus ``kjr_grant/migrations/19.0.15.7.0/post-migration.py``). Hat die
Geschäftsstelle den Betreff selbst angepasst, bleibt er unangetastet und das
Protokoll sagt es.

Idempotent: ein zweiter Lauf findet den alten Wert nicht mehr und ändert nichts.

WAS DIE KORREKTUR INHALTLICH IST
────────────────────────────────
Der Betreff enthielt einen Halbgeviertstrich (–). Betreffzeilen sind
kundensichtbarer Text; der Projektstandard lässt dort nur Binde- und
Satzzeichen zu. Ersetzt wird er durch das Wort „zu", der Satzbau bleibt.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

XMLID = 'kjr_event.mail_template_consent_reminder'

# Auslieferungsstand bis einschließlich 19.0.5.6.1 -> neuer Betreff.
SUBJECT_ALT = 'Erinnerung: Einwilligung erforderlich – {{ object.event_id.name }}'
SUBJECT_NEU = 'Erinnerung: Einwilligung erforderlich zu {{ object.event_id.name }}'


def migrate(cr, version):
    """Betreff der Einwilligungs-Erinnerung nachziehen, ohne Pflege zu überschreiben."""
    if not version:
        # Neuinstallation: die XML-Daten tragen den neuen Wert schon.
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    template = env.ref(XMLID, raise_if_not_found=False)
    if not template:
        _logger.info('Mailvorlage %s nicht vorhanden, nichts nachzuziehen.', XMLID)
        return
    if template.subject == SUBJECT_NEU:
        _logger.info('Betreff von %s ist bereits korrigiert.', XMLID)
        return
    if template.subject != SUBJECT_ALT:
        _logger.info(
            'Betreff von %s wurde selbst gepflegt und bleibt unverändert. Der '
            'Halbgeviertstrich ist dort gegebenenfalls von Hand zu ersetzen.', XMLID)
        return
    template.subject = SUBJECT_NEU
    _logger.info('Betreff von %s auf den korrigierten Auslieferungstext gesetzt.', XMLID)
