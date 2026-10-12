# -*- coding: utf-8 -*-
"""Link-Block für die digitale Einwilligung in der Einwilligungs-Erinnerung.

WARUM DIESES SKRIPT NÖTIG IST
─────────────────────────────
``data/mail_templates.xml`` steht unter ``<data noupdate="1">`` (Begründung im
Kopf der Datei und in ``migrations/19.0.5.8.0/post-migration.py``). Odoo
überspringt solche Datensätze im Update-Modus vollständig; der neue Absatz mit
dem Signierlink (``object.kjr_consent_action_url``) erreicht bestehende
Datenbanken deshalb nicht von allein.

WAS GESCHRIEBEN WIRD
────────────────────
Der Auslieferungsabsatz ``<p>Bitte reichen Sie diese rechtzeitig vor Beginn
nach.</p>`` wird durch den Link-Block ersetzt (Text identisch mit
``data/mail_templates.xml``): mit Signierlink erscheint ein Knopf zum
Unterschreiben, ohne Link bleibt der bisherige Satz stehen. Dazu kommt der Satz,
dass die Anmeldung erst mit der Einwilligung verbindlich ist (nur bei gesperrten
Anmeldungen).

Der Link wird nur gelesen, wenn die Vorlage unter sudo gerendert wird
(``object.env.su``, so in der Aktion und im Cron). Im Mail-Composer, in der
Vorschau oder in Automatisierungen rendert Odoo im Benutzerkontext; das
feldgeschützte ``kjr_consent_action_url`` würde dort für Benutzer ohne die
Gruppe ``kjr_event.group_kjr_event_care`` einen AccessError auslösen. Mit der
Bedingung erscheint dort der Text ohne Link.

WIE VORSICHTIG
──────────────
* Je installierter Sprache wird ``body_html`` in dieser Sprache gelesen und nur
  geschrieben, wenn der Altabsatz WÖRTLICH enthalten ist (Leerraum-tolerant)
  und der Link-Block noch fehlt.
* Hat die Geschäftsstelle die Vorlage so umgestaltet, dass der Absatz nicht mehr
  vorkommt, bleibt sie unangetastet; das Protokoll sagt es (Link-Block dann von
  Hand ergänzen).
* Idempotent: ein zweiter Lauf findet den Link-Block und ändert nichts.
  Schreibt eine Sprache die Struktur bereits für die übrigen Sprachen mit
  (übersetzbares HTML-Feld), gilt die nächste Sprache als erledigt.

EMPFÄNGER DER ERINNERUNG
────────────────────────
Zusätzlich wird ``use_default_to`` der Vorlage auf False gesetzt (wie in
``data/mail_templates.xml``). Mit dem Odoo-19-Standard True ignoriert send_mail
``email_to`` und schickt an die Standard-Empfänger der Anmeldung, also an deren
Kontakt. Der Signierlink soll aber nur die Erziehungsberechtigten erreichen. Der
Versandcode verwirft die Standard-Empfänger ohnehin
(``models/kjr_event_document.py``, ``_kjr_send_template`` mit detach); die
Vorlage soll trotzdem dieselbe Einstellung tragen. Idempotent: nur wenn der Wert
noch True ist.

Die neuen Felder dieser Version (kjr_consent_hold, kjr_consent_source,
guardian_email) brauchen keinen Nachzug: leer bzw. False ist für den Bestand
der richtige Wert.

WARUM DER ORDNER DIE NEUE MANIFESTVERSION TRÄGT
───────────────────────────────────────────────
``odoo/modules/migration.py`` führt ein Skript nur aus, wenn seine
Ordnerversion strikt größer als die installierte und kleiner oder gleich der
neuen Manifestversion ist.
"""
import logging
import re

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

XMLID = 'kjr_event.mail_template_consent_reminder'
MARKER = 'kjr_consent_action_url'

# Altabsatz bis einschließlich 19.0.5.8.1, tolerant gegenüber Leerraum und
# Zeilenumbrüchen innerhalb des Absatzes.
ALT_ABSATZ = re.compile(
    r'<p>\s*Bitte\s+reichen\s+Sie\s+diese\s+rechtzeitig\s+vor\s+Beginn\s+nach\.\s*</p>')

NEU_BLOCK = (
    '<t t-if="object.env.su and object.kjr_consent_action_url">'
    '<p>Sie können die Einwilligung direkt online unterschreiben:</p>'
    '<p><a t-att-href="object.kjr_consent_action_url" '
    'style="display:inline-block;padding:8px 16px;background-color:#1B3A6B;'
    'color:#ffffff;text-decoration:none;border-radius:4px;">'
    'Einwilligung jetzt unterschreiben</a></p></t>'
    '<t t-else=""><p>Bitte reichen Sie diese rechtzeitig vor Beginn nach.</p></t>'
    '<p t-if="object.kjr_consent_hold">Erst wenn die Einwilligung vorliegt, ist die '
    'Anmeldung verbindlich bestätigt.</p>'
)


def migrate(cr, version):
    """Link-Block je Sprache nachziehen, ohne gepflegte Texte zu überschreiben."""
    if not version:
        # Neuinstallation: die XML-Daten tragen den Link-Block schon.
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    template = env.ref(XMLID, raise_if_not_found=False)
    if not template:
        _logger.info('Mailvorlage %s nicht vorhanden, nichts nachzuziehen.', XMLID)
        return
    for code, _name in env['res.lang'].get_installed():
        template_lang = template.with_context(lang=code)
        body = template_lang.body_html or ''
        if MARKER in body:
            _logger.info('Vorlage %s (%s): Link-Block bereits vorhanden.', template.id, code)
            continue
        if not ALT_ABSATZ.search(body):
            _logger.warning(
                'Vorlage %s individuell angepasst, Link-Block manuell ergänzen (Sprache %s).',
                template.id, code)
            continue
        template_lang.body_html = ALT_ABSATZ.sub(lambda _m: NEU_BLOCK, body, count=1)
        _logger.info('Vorlage %s (%s): Link-Block für die digitale Einwilligung ergänzt.',
                     template.id, code)
    if template.use_default_to:
        template.use_default_to = False
        _logger.info('Vorlage %s: Standard-Empfänger abgeschaltet (nur email_to).',
                     template.id)
