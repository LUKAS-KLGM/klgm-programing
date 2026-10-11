# -*- coding: utf-8 -*-
"""Mailvorlagen nachziehen: ``{{ … }}``, Striche in den Betreffzeilen, Trägerbezug.

WARUM DIESES SKRIPT NÖTIG IST
─────────────────────────────
In 19.0.7.0.0 wurden die Platzhalter in ``data/mail_template_data.xml`` von
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
wären die Mails weiter unlesbar geblieben. Dieselbe Falle ist im
Mailvorlagen-Migrationsskript von ``kjr_grant`` beschrieben; absichtlich OHNE
Versionsordner genannt, weil der Verweis sonst mit der nächsten Versionsanhebung
jenes Moduls wieder ins Leere zeigt (genau das war hier zweimal der Fall). Alle
sieben Vorlagen dieses Moduls sind betroffen.

WARUM DIESES SKRIPT IM ORDNER DER NEUEN VERSION LIEGT
─────────────────────────────────────────────────────
``odoo/modules/migration.py`` führt ein Skript nur aus, wenn die installierte
Version KLEINER ist als die Ordnerversion und diese kleiner/gleich der neuen
Manifestversion. Eine frühere Fassung dieses Skripts lag unter ``19.0.7.1.0`` —
also UNTER der auf den Instanzen installierten 19.0.7.2.1 — und wäre nie
gelaufen. Deshalb steht es jetzt im Ordner der neuen Manifestversion.

WARUM NICHT EINFACH DIE XML-WERTE ÜBERSCHREIBEN
───────────────────────────────────────────────
Der ``noupdate``-Schutz ist gewollt: die Geschäftsstelle darf die Vorlagen im
Backend anpassen, ohne dass ein Modul-Update ihre Formulierungen zurücksetzt. Ein
stumpfes Zurückschreiben der Auslieferungswerte würde genau diese Pflege löschen.

Deshalb wird hier nicht kopiert, sondern **derselbe Umbau auf dem gespeicherten
Wert** ausgeführt: jedes ``{{ … }}`` im Fließtext wird zu ``<t t-out="…"/>``, alles
andere bleibt unangetastet. Eigene Textänderungen der Geschäftsstelle überleben das.

SCHRITT 2: GEDANKENSTRICHE IN DEN BETREFFZEILEN
───────────────────────────────────────────────
Drei Betreffzeilen trugen einen Geviertstrich ("Reservierungsbestätigung … — …").
Nach der Projektkonvention stehen in kundensichtbarem Text keine Geviert- oder
Halbgeviertstriche; die XML liefert jetzt einen Doppelpunkt. Auch das erreicht
Bestandsinstanzen nur über dieses Skript. Ersetzt wird ausschließlich die exakte
Zeichenfolge " — " bzw. " – " durch ": "; eine Betreffzeile ohne Strich wird nicht
angefasst, ein zweiter Lauf ändert nichts.

SCHRITT 3: TRÄGERBEZUG IM RUMPF DER STORNIERUNGSVORLAGE
───────────────────────────────────────────────────────
Der Rumpf von ``mail_template_booking_cancelled`` nannte die Geschäftsstelle mit
dem Kürzel des Trägers („Bei Rückfragen wenden Sie sich an die
KJR-Geschäftsstelle."). Diese Mail geht an den Gast, der Satz steht also in
KUNDENSICHTBAREM Text, und das Modul ist White Label. Die Auslieferungsfassung
nennt jetzt ``object.company_id.name``; weil die Datei unter
``<data noupdate="1">`` liegt, muss der gespeicherte Satz hier nachgezogen werden.
Ersetzt wird ausschließlich die exakte Zeichenfolge; hat die Geschäftsstelle den
Satz selbst umformuliert, bleibt ihre Fassung stehen.

Idempotent: ohne ``{{`` im Rumpf, ohne Strich im Betreff und ohne den alten
Trägersatz passiert nichts.

BEWUSST NICHT ANGEFASST
───────────────────────
* Vorkommen INNERHALB eines Tags, also in einem HTML-Attribut (etwa
  ``href="{{ … }}"``). Dort wäre ``t-attf-href`` nötig, und welches Attribut gemeint
  ist, lässt sich nicht zuverlässig automatisch ableiten. Solche Fälle werden
  gezählt und protokolliert, damit sie von Hand nachgesehen werden können.
* ``{{ }}`` in ``subject``, ``email_from``, ``email_to`` und den übrigen Kopffeldern.
  Die laufen über die Engine ``inline_template``, die ``{{ }}`` sehr wohl ersetzt —
  dort ist die Schreibweise korrekt und bleibt. In der ausgelieferten
  ``data/mail_template_data.xml`` steht ``{{ }}`` deshalb nur noch in genau diesen
  drei Feldern; die sieben ``body_html`` sind bereits sauber. Das Skript bleibt
  trotzdem nötig, weil Bestandsinstanzen den alten gespeicherten Rumpf tragen.
* Übersetzte Zweitsprachen von ``body_html`` und ``subject``. Gepflegt wird
  ausschließlich Deutsch; sollte später eine zweite Sprache dazukommen, ist sie
  hier nachzuziehen.
"""
import logging
import re

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

MODULE = 'kjr_facility'
VERSION = '19.0.7.3.0'
PLACEHOLDER = re.compile(r'\{\{(.*?)\}\}', re.S)
# Nur die exakte Strich-Umgebung ersetzen, damit Bindestriche in Wörtern
# ("Mo-Fr-Tarif") unberührt bleiben.
SUBJECT_DASHES = (' — ', ' – ')
# Schritt 3: White Label im Rumpf der Stornierungsvorlage. Nur dieser exakte
# Teilsatz wird ersetzt, damit eine eigene Formulierung der Geschäftsstelle
# unangetastet bleibt.
TRAEGER_SATZ = 'an die KJR-Geschäftsstelle.'
TRAEGER_ERSATZ = 'an die Geschäftsstelle von <t t-out="object.company_id.name"/>.'


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


def _neutral_traeger(body):
    """Trägerkürzel im Rumpf durch den Gesellschaftsnamen ersetzen.

    Rückgabe: (neuer Rumpf, Anzahl ersetzt).
    """
    treffer = body.count(TRAEGER_SATZ)
    if not treffer:
        return body, 0
    return body.replace(TRAEGER_SATZ, TRAEGER_ERSATZ), treffer


def _plain_subject(subject):
    """Geviert-/Halbgeviertstrich in der Betreffzeile durch einen Doppelpunkt ersetzen."""
    new = subject
    for dash in SUBJECT_DASHES:
        new = new.replace(dash, ': ')
    return new


def migrate(cr, version):
    if not version:
        return  # Neuinstallation: die XML liefert bereits den korrigierten Stand.

    env = api.Environment(cr, SUPERUSER_ID, {})
    xmlids = env['ir.model.data'].search([
        ('module', '=', MODULE),
        ('model', '=', 'mail.template'),
    ])
    templates = env['mail.template'].browse(xmlids.mapped('res_id')).exists()

    touched = total_replaced = total_skipped = subjects = traeger = 0
    for template in templates:
        body = str(template.body_html or '')
        new_body = body
        if '{{' in new_body:
            new_body, replaced, skipped = _convert(new_body)
            total_replaced += replaced
            total_skipped += skipped
            if skipped:
                _logger.warning(
                    'Migration %s %s: Vorlage "%s" (id %s) enthält %d Platzhalter '
                    'in einem HTML-Attribut. Die bleiben unverändert und brauchen von '
                    'Hand ein t-attf-Attribut.',
                    MODULE, VERSION, template.name, template.id, skipped,
                )
        new_body, traeger_treffer = _neutral_traeger(new_body)
        traeger += traeger_treffer
        if new_body != body:
            template.body_html = new_body
            touched += 1

        subject = str(template.subject or '')
        new_subject = _plain_subject(subject)
        if new_subject != subject:
            template.subject = new_subject
            subjects += 1

    env.flush_all()
    _logger.info(
        'Migration %s %s: %d von %d Mailvorlage(n) im Rumpf angepasst, '
        '%d Platzhalter auf t-out umgestellt, %d in Attributen übersprungen, '
        '%d Betreffzeile(n) auf Doppelpunkt umgestellt, '
        '%d Trägerbezug/Trägerbezüge im Rumpf neutralisiert.',
        MODULE, VERSION, touched, len(templates), total_replaced, total_skipped,
        subjects, traeger,
    )
