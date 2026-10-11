# -*- coding: utf-8 -*-
"""Nachzug zweier Korrekturen, die ``noupdate="1"`` sonst nie erreicht hätte.

1. Mailvorlagen: ``{{ … }}`` im Fließtext auf ``<t t-out="…"/>``.
2. Mailvorlagen: Halbgeviertstrich zwischen Beginn und Ende der Maßnahme auf
   „bis" (Projektregel: keine Geviert-/Halbgeviertstriche in kundensichtbarem
   Text, und die Eingangsbestätigung ist kundensichtbar).
3. Förderart „Investitionszuschuss": Auslieferungstext ohne Trägerbezug und
   ohne das Wort PLATZHALTER im kundensichtbaren Namen.

WARUM DIESES SKRIPT NÖTIG IST
─────────────────────────────
In 19.0.15.3.0 wurden die Platzhalter in ``data/mail_template_data.xml`` von
``{{ … }}`` auf ``<t t-out="…"/>`` umgestellt. ``mail.template.body_html`` wird als
QWeb gerendert, und QWeb interpoliert ``{{ }}`` ausschließlich innerhalb von
Attributen, nie in Textknoten — im Chatter stand deshalb sichtbar
``{{ object.partner_id.name }}``.

Die XML-Änderung allein erreicht bestehende Datenbanken NICHT: die Vorlagen liegen
unter ``<data noupdate="1">``. Odoo überspringt solche Datensätze im Update-Modus
vollständig (``odoo/tools/convert.py``: ``if self.noupdate and self.mode != 'init':``
mit anschließendem ``return None``); ein zweiter Riegel sitzt in
``models._load_records`` über das gespeicherte ``ir.model.data.noupdate``-Flag.
Die Korrektur hätte also nur NEUE Datenbanken erreicht — auf Demo und Produktion
wären die Mails weiter unlesbar geblieben. Dieselbe Falle ist bereits in
``migrations/19.0.10.0.0/post-migration.py`` beschrieben und gilt wortgleich für
``data/kjr_grant_type_data.xml``, weshalb Punkt 2 hier mitläuft.

WARUM DER ORDNER 19.0.15.7.0 HEISST
───────────────────────────────────
Der Mailvorlagen-Teil lag ursprünglich unter ``migrations/19.0.15.4.0``. Diese
Nummer ist inzwischen von einer anderen Auslieferung belegt und auf Demo und
Produktion längst installiert. ``odoo/modules/migration.py`` führt ein Skript nur
aus, wenn seine Ordnerversion STRIKT GRÖSSER als die installierte und
kleiner/gleich der neuen Manifestversion ist
(``parsed_installed_version < parse_version(full_version) <= current_version``).
Unter der alten Nummer wäre es also nie gelaufen. Der Ordner trägt deshalb immer
die NEUE Manifestversion: wird das Manifest später erneut angehoben, wandert
dieser Ordner mit.

WARUM NICHT EINFACH DIE XML-WERTE ÜBERSCHREIBEN
───────────────────────────────────────────────
Der ``noupdate``-Schutz ist gewollt: die Geschäftsstelle darf die Vorlagen im
Backend anpassen, ohne dass ein Modul-Update ihre Formulierungen zurücksetzt. Ein
stumpfes Zurückschreiben der Auslieferungswerte würde genau diese Pflege löschen.

Deshalb wird hier nicht kopiert, sondern **derselbe Umbau auf dem gespeicherten
Wert** ausgeführt: jedes ``{{ … }}`` im Fließtext wird zu ``<t t-out="…"/>``, alles
andere bleibt unangetastet. Eigene Textänderungen der Geschäftsstelle überleben das.
Beim Förderart-Text greift dieselbe Vorsicht aus einer anderen Richtung: dort wird
nur geschrieben, wenn im Feld noch WÖRTLICH der alte Auslieferungswert steht
(Muster ``_korrigiere_betrag`` aus ``migrations/19.0.10.0.0``).

Idempotent: ohne ``{{`` im Rumpf passiert nichts, ein zweiter Lauf ändert nichts.

Der Halbgeviertstrich (Punkt 2) wird nach derselben Vorsichtsregel getauscht wie
die Förderart-Texte: ersetzt wird NUR, wenn im gespeicherten Rumpf noch wörtlich
die ausgelieferte Zeichenkette steht. Steht dort etwas anderes, hat die
Geschäftsstelle den Satz gepflegt; dann bleibt er unverändert und es gibt einen
Protokolleintrag. Die Reihenfolge in ``migrate`` ist dabei wesentlich: erst der
``{{ }}``-Umbau, danach der Strich. Auf einer Instanz aus der Zeit vor
19.0.15.3.0 steht im Rumpf noch ``{{ object.measure_start }} – …``; nach dem
Umbau trägt die Zeile die ``<t t-out="…"/>``-Schreibweise, auf die der
Exakt-Vergleich passt. Beide Auslieferungsstände werden damit erreicht.

BEWUSST NICHT ANGEFASST
───────────────────────
* Vorkommen INNERHALB eines Tags, also in einem HTML-Attribut (etwa
  ``href="{{ … }}"``). Dort wäre ``t-attf-href`` nötig, und welches Attribut gemeint
  ist, lässt sich nicht zuverlässig automatisch ableiten. Solche Fälle werden
  gezählt und protokolliert, damit sie von Hand nachgesehen werden können.
* ``subject``, ``email_from``, ``email_to`` und die übrigen Kopffelder. Die laufen
  über die Engine ``inline_template``, die ``{{ }}`` sehr wohl ersetzt — dort ist
  die Schreibweise korrekt und muss bleiben.
* Übersetzte Zweitsprachen von ``body_html``. Gepflegt wird ausschließlich Deutsch;
  sollte später eine zweite Sprache dazukommen, ist sie hier nachzuziehen.
"""
import logging
import re

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

MODULE = 'kjr_grant'
VERSION = '19.0.15.7.0'
PLACEHOLDER = re.compile(r'\{\{(.*?)\}\}', re.S)

XMLID_INVEST = 'kjr_grant.grant_type_invest'
XMLID_STARTHILFE = 'kjr_grant.grant_type_4_7'

# Zeitraumzeile der Eingangsbestätigung: Auslieferungsstand bis einschließlich
# 19.0.15.6.1 -> Fassung ohne Halbgeviertstrich. Der Vergleich läuft auf dem
# Rumpf NACH dem {{ }}-Umbau, deshalb die t-out-Schreibweise.
ZEITRAUM_ALT = ('<t t-out="object.measure_start"/> – '
                '<t t-out="object.measure_end"/>')
ZEITRAUM_NEU = ('<t t-out="object.measure_start"/> bis '
                '<t t-out="object.measure_end"/>')

# Auslieferungsstand bis einschließlich 19.0.15.6.1 -> neuer, trägerneutraler Text.
INVEST_NAME_ALT = 'Investitionszuschuss (Landkreis – konfigurierbar)'
INVEST_NAME_NEU = 'Investitionszuschuss (externes Programm, konfigurierbar)'
INVEST_DESC_ALT = (
    'Generischer Investitionszuschuss für Anschaffungen/Baumaßnahmen nach einem '
    'externen Förderprogramm (z. B. Landkreis). Berechnung: konfigurierbarer Anteil '
    'der nachgewiesenen Investitionskosten (Förderquote), gedeckelt auf den '
    'Höchstbetrag (0 = ohne Deckel). PLATZHALTER-Werte – Förderquote und '
    'Höchstbetrag vor Nutzung an das gültige Programm anpassen.'
)
INVEST_DESC_NEU = (
    'Generischer Investitionszuschuss für Anschaffungen und Baumaßnahmen nach einem '
    'externen Förderprogramm. Berechnung: konfigurierbarer Anteil der nachgewiesenen '
    'Investitionskosten (Förderquote), gedeckelt auf den Höchstbetrag '
    '(0 = ohne Deckel). Förderquote und Höchstbetrag sind vor der Nutzung an das '
    'gültige Programm anzupassen.'
)


# Pflichtunterlage der Gruppenstarthilfe: Der Auslieferungstext nannte das
# Kuerzel des Traegers. Der Text steht auf der oeffentlichen Hilfeseite.
# ACHTUNG: STARTHILFE_DOCS_ALT ist der WOERTLICHE Altwert und wird nur
# verglichen, nie angezeigt. Er darf NICHT traegerneutral umgeschrieben
# werden - sonst findet das Skript den Altbestand nicht mehr und der
# Kundenbezug bleibt in Bestandsinstanzen stehen.
STARTHILFE_DOCS_ALT = 'Formular Neugründung (Beilage KJR OA)'
STARTHILFE_DOCS_NEU = 'Formular Neugründung (Beilage der Geschäftsstelle)'


def _to_t_out(expr):
    """``{{ expr }}`` → ``<t t-out="expr"/>`` mit passender Anführungszeichenwahl."""
    expr = expr.strip()
    if '"' not in expr:
        return '<t t-out="%s"/>' % expr
    if "'" not in expr:
        return "<t t-out='%s'/>" % expr
    return '<t t-out="%s"/>' % expr.replace('"', '&quot;')


def _convert(body):
    """Fließtext-Platzhalter umstellen, Attribut-Platzhalter unangetastet lassen.

    Rückgabe: (neuer Rumpf, Anzahl ersetzt, Anzahl übersprungen).
    """
    replaced = []
    skipped = []

    def repl(match):
        before = body[:match.start()]
        # Steht der Fund zwischen '<' und '>', sitzt er in einem Attribut.
        if before.rfind('<') > before.rfind('>'):
            skipped.append(match.group(0))
            return match.group(0)
        replaced.append(match.group(0))
        return _to_t_out(match.group(1))

    return PLACEHOLDER.sub(repl, body), len(replaced), len(skipped)


def _ziehe_mailvorlagen_nach(env):
    """``{{ … }}`` im gespeicherten ``body_html`` auf ``<t t-out="…"/>`` umstellen."""
    xmlids = env['ir.model.data'].search([
        ('module', '=', MODULE),
        ('model', '=', 'mail.template'),
    ])
    templates = env['mail.template'].browse(xmlids.mapped('res_id')).exists()

    touched = total_replaced = total_skipped = 0
    for template in templates:
        body = str(template.body_html or '')
        if '{{' not in body:
            continue
        new_body, replaced, skipped = _convert(body)
        total_skipped += skipped
        if skipped:
            _logger.warning(
                'Migration %s %s: Vorlage "%s" (id %s) enthält %d Platzhalter '
                'in einem HTML-Attribut. Die bleiben unverändert und brauchen von Hand '
                'ein t-attf-Attribut.',
                MODULE, VERSION, template.name, template.id, skipped,
            )
        if new_body == body:
            continue
        template.body_html = new_body
        touched += 1
        total_replaced += replaced

    _logger.info(
        'Migration %s %s: %d von %d Mailvorlage(n) angepasst, '
        '%d Platzhalter auf t-out umgestellt, %d in Attributen übersprungen.',
        MODULE, VERSION, touched, len(templates), total_replaced, total_skipped,
    )


def _ersetze_zeitraum_strich(body):
    """Halbgeviertstrich der Zeitraumzeile auf „bis".

    Rückgabe: (neuer Rumpf, Anzahl ersetzt). Ersetzt wird nur der wörtliche
    Auslieferungsstand; alles andere bleibt unangetastet. Idempotent, weil die
    neue Fassung die alte Zeichenkette nicht mehr enthält.
    """
    treffer = body.count(ZEITRAUM_ALT)
    if not treffer:
        return body, 0
    return body.replace(ZEITRAUM_ALT, ZEITRAUM_NEU), treffer


def _ziehe_zeitraumstrich_nach(env):
    """Den Halbgeviertstrich aus dem gespeicherten ``body_html`` entfernen.

    Läuft NACH ``_ziehe_mailvorlagen_nach``, damit der Exakt-Vergleich auch auf
    Instanzen greift, die den Zeitraum noch in der ``{{ }}``-Schreibweise
    gespeichert hatten.
    """
    xmlids = env['ir.model.data'].search([
        ('module', '=', MODULE),
        ('model', '=', 'mail.template'),
    ])
    templates = env['mail.template'].browse(xmlids.mapped('res_id')).exists()

    touched = 0
    for template in templates:
        body = str(template.body_html or '')
        if '–' not in body:
            continue
        new_body, ersetzt = _ersetze_zeitraum_strich(body)
        if not ersetzt:
            _logger.info(
                'Migration %s %s: Vorlage "%s" (id %s) enthält einen '
                'Halbgeviertstrich, aber nicht die ausgelieferte Zeitraumzeile - '
                'übersprungen, um gepflegten Text nicht zu überschreiben.',
                MODULE, VERSION, template.name, template.id,
            )
            continue
        template.body_html = new_body
        touched += 1
        _logger.info(
            'Migration %s %s: Vorlage "%s" (id %s): Halbgeviertstrich der '
            'Zeitraumzeile %dx auf "bis" umgestellt.',
            MODULE, VERSION, template.name, template.id, ersetzt,
        )
    if not touched:
        _logger.info(
            'Migration %s %s: keine Mailvorlage mit Halbgeviertstrich in der '
            'Zeitraumzeile gefunden (bereits korrigiert oder gepflegt).',
            MODULE, VERSION,
        )


def _korrigiere_text(record, fname, alt, neu):
    """Setzt ``fname`` auf ``neu`` – aber nur, wenn dort noch exakt ``alt`` steht.

    Gibt True zurück, wenn geschrieben wurde. Steht schon der neue Text da, ist
    nichts zu tun (Idempotenz); steht etwas Drittes da, hat die Geschäftsstelle
    gepflegt und wird nicht überschrieben.
    """
    aktuell = (record[fname] or '').strip()
    if aktuell == neu.strip():
        return False
    if aktuell != alt.strip():
        _logger.info(
            'Migration %s %s: Förderart (ID %s) hat in %s einen vom '
            'Auslieferungsstand abweichenden Text - übersprungen, um manuelle '
            'Pflege nicht zu überschreiben. Vorgefunden: %r',
            MODULE, VERSION, record.id, fname, aktuell,
        )
        return False
    record.write({fname: neu})
    _logger.info(
        'Migration %s %s: Förderart (ID %s): %s auf den trägerneutralen '
        'Auslieferungstext aktualisiert.',
        MODULE, VERSION, record.id, fname,
    )
    return True


def _ziehe_investitionszuschuss_nach(env):
    """Name und Beschreibung der Förderart „Investitionszuschuss" nachziehen.

    Beide Felder erscheinen in Listen, Auswahlfeldern und auf der öffentlichen
    Hilfeseite. Der Auslieferungstext nannte einen konkreten Fördergeber und trug
    das Wort PLATZHALTER in Großbuchstaben im Kundentext.
    """
    record = env.ref(XMLID_INVEST, raise_if_not_found=False)
    if not record or not record.exists():
        _logger.info(
            'Migration %s %s: Förderart %s nicht gefunden - übersprungen '
            '(bereits gelöscht oder nie installiert).',
            MODULE, VERSION, XMLID_INVEST,
        )
        return
    _korrigiere_text(record, 'name', INVEST_NAME_ALT, INVEST_NAME_NEU)
    _korrigiere_text(record, 'description', INVEST_DESC_ALT, INVEST_DESC_NEU)


def _ziehe_starthilfe_nach(env):
    """Pflichtunterlage der Gruppenstarthilfe (§ 4.7) trägerneutral formulieren.

    Der Text erscheint auf der öffentlichen Hilfeseite unter „Welche Unterlagen
    brauche ich?" und im Backend an der Förderart.
    """
    record = env.ref(XMLID_STARTHILFE, raise_if_not_found=False)
    if not record or not record.exists():
        _logger.info(
            'Migration %s %s: Förderart %s nicht gefunden - übersprungen '
            '(bereits gelöscht oder nie installiert).',
            MODULE, VERSION, XMLID_STARTHILFE,
        )
        return
    _korrigiere_text(
        record, 'requires_other_docs', STARTHILFE_DOCS_ALT, STARTHILFE_DOCS_NEU,
    )


def migrate(cr, version):
    if not version:
        return  # Neuinstallation: die XML liefert bereits den korrigierten Stand.

    env = api.Environment(cr, SUPERUSER_ID, {})
    _ziehe_mailvorlagen_nach(env)
    # Zwingend NACH dem {{ }}-Umbau: der Exakt-Vergleich erwartet die
    # t-out-Schreibweise der Zeitraumzeile.
    _ziehe_zeitraumstrich_nach(env)
    # active_test=False: der Investitionszuschuss ist seit 19.0.10.0.0 bewusst inaktiv.
    _ziehe_investitionszuschuss_nach(env(context={'active_test': False}))
    _ziehe_starthilfe_nach(env)
