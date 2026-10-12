# -*- coding: utf-8 -*-
"""Bereinigt Website-Formular-Textareas, deren Inhalt nur aus <br/> besteht.

Befund A (Website-Formulare): In gespeicherten Website-Ansichten stehen
<textarea>-Felder, deren Inhalt nur ein <br/> ist (Editor-Artefakt bzw. nach
erneutem Speichern als escapter Text). Im Browser erscheint dann "<br/>" als
vorausgefuellter Text im Eingabefeld.

Autor:   KLGM UG (haftungsbeschraenkt), https://www.klgm-consulting.de
Lizenz:  OPL-1
Stand:   2026-10-12
Anleitung: tools/website_fixes/README.md (vor JEDER Ausfuehrung lesen).

AUSFUEHREN DARF DAS SKRIPT NUR EINE BERECHTIGTE PERSON auf dem Server bzw.
einer Server-Kopie, nach einem Snapshot. Nicht lokal, nicht durch den
Assistenten.

Betriebsarten (Umgebungsvariablen):
    (keine)              Dry-Run: listet Treffer, schreibt nichts, Rollback.
    KJR_FIX_WRITE=1      schreibt die Korrektur ueber das ORM und committet.
    KJR_FIX_SCAN_HTML=1  reiner Lesemodus: listet NUR die IDs von event.event,
                         deren description '<textarea' und '<br' enthaelt
                         (Sonderfall HTML-Feld, siehe README). Schreibt nie,
                         auch nicht zusammen mit KJR_FIX_WRITE=1.

Ausgabe: Ansichts-IDs, technische Schluessel, Seiten-URLs und Feldnamen der
Textareas; keine personenbezogenen Daten.

Aufruf (auf dem Server, NICHT lokal):
    odoo shell -d <db> --no-http < fix_textarea_br.py            # Dry-Run (Standard)
    KJR_FIX_WRITE=1 odoo shell -d <db> --no-http < fix_textarea_br.py   # schreibt

Vorgehen:
- Kandidaten per SQL NUR LESEN (arch_db ist seit Odoo 16 jsonb {lang: arch}).
- Jede Sprachfassung einzeln mit lxml parsen; betroffen ist eine <textarea>,
  deren Inhalt leer waere, wenn man <br>-Elemente bzw. den Literaltext
  "<br/>", "<br>", "<br />" entfernt (beide Varianten kommen vor: echtes
  Element aus dem Editor oder escapter Text nach einem erneuten Speichern).
- Schreiben ausschliesslich ueber das ORM (Validierung _check_xml, Caches,
  Uebersetzungs-Mechanik), je Sprache mit with_context(lang=..., no_cow=True),
  ohne website_id im Kontext -> keine COW-Kopie, website-spezifische Views
  (website_id gesetzt) werden als eigene Datensaetze direkt korrigiert.
- Nach jedem Schreiben wird roh nachgelesen und geprueft.
"""
import os
import re

from lxml import etree

SCAN_HTML = os.environ.get('KJR_FIX_SCAN_HTML') == '1'
# Der Lesemodus schreibt nie, auch wenn KJR_FIX_WRITE gesetzt ist.
WRITE = os.environ.get('KJR_FIX_WRITE') == '1' and not SCAN_HTML
BR_TEXT_RE = re.compile(r'^\s*(?:<br\s*/?>\s*)+$', re.IGNORECASE)


def _is_br_only(textarea):
    """True, wenn die Textarea nur aus <br>-Elementen oder dem Text '<br/>' besteht."""
    children = list(textarea)
    text = (textarea.text or '')
    tails = ''.join((child.tail or '') for child in children)
    if children:
        if any(not isinstance(c.tag, str) or c.tag.lower() != 'br' for c in children):
            return False
        return not (text + tails).strip()
    return bool(BR_TEXT_RE.match(text))


def _clean(arch):
    """Liefert (neue_arch, anzahl_treffer). Arch bleibt unveraendert, wenn nichts passt."""
    if not arch or '<textarea' not in arch:
        return arch, 0
    parser = etree.XMLParser(remove_blank_text=False, strip_cdata=False, resolve_entities=False)
    try:
        root = etree.fromstring(arch.encode('utf-8'), parser)
    except etree.XMLSyntaxError as exc:
        print('    ! nicht parsebar, uebersprungen: %s' % exc)
        return arch, 0
    hits = 0
    for textarea in root.iter('textarea'):
        if _is_br_only(textarea):
            print('    - textarea name=%r id=%r Inhalt=%r' % (
                textarea.get('name'), textarea.get('id'),
                (textarea.text or '') + ''.join(etree.tostring(c, encoding='unicode') for c in textarea)))
            for child in list(textarea):
                textarea.remove(child)
            textarea.text = ''
            hits += 1
    if not hits:
        return arch, 0
    return etree.tostring(root, encoding='unicode'), hits


def _raw_arch(view_id):
    env.cr.execute('SELECT arch_db FROM ir_ui_view WHERE id = %s', (view_id,))
    row = env.cr.fetchone()
    return (row and row[0]) or {}


def _scan_event_html():
    """Lesemodus KJR_FIX_SCAN_HTML=1: nur IDs von event.event ausgeben.

    event.event.description ist ein uebersetzbares HTML-Feld (jsonb je
    Sprache); gesucht wird im Rohtext aller Sprachfassungen, nur lesend.
    """
    env.cr.execute("""
        SELECT id FROM event_event
         WHERE description::text ILIKE '%%<textarea%%'
           AND (description::text ILIKE '%%<br%%' OR description::text ILIKE '%%&lt;br%%')
         ORDER BY id
    """)
    event_ids = [r[0] for r in env.cr.fetchall()]
    print('Lesemodus (KJR_FIX_SCAN_HTML=1): event.event mit <textarea> und <br> '
          'in der Beschreibung: %s' % len(event_ids))
    for event_id in event_ids:
        print('  event.event %s' % event_id)
    print('Nichts geaendert (Lesemodus).')
    env.cr.rollback()


def _fix_views():
    """Hauptteil (unveraendert aus der Pruefung uebernommen)."""
    env.cr.execute("""
        SELECT id FROM ir_ui_view
         WHERE type = 'qweb'
           AND arch_db::text ILIKE '%%<textarea%%'
           AND (arch_db::text ILIKE '%%<br%%' OR arch_db::text ILIKE '%%&lt;br%%')
         ORDER BY id
    """)
    view_ids = [r[0] for r in env.cr.fetchall()]
    print('Kandidaten (SQL-Vorauswahl): %s' % len(view_ids))

    View = env['ir.ui.view'].with_context(active_test=False, no_cow=True)
    total = 0
    for view in View.browse(view_ids):
        raw = _raw_arch(view.id)
        plan = {}
        for lang, arch in sorted(raw.items()):
            new_arch, hits = _clean(arch)
            if hits:
                plan[lang] = (new_arch, hits)
        if not plan:
            continue
        total += sum(h for _a, h in plan.values())
        print('View %s key=%r name=%r website_id=%s aktiv=%s Seiten=%s Sprachen=%s' % (
            view.id, view.key, view.name, view.website_id.id or '-', view.active,
            ', '.join(view.page_ids.mapped('url')) or '-', ', '.join(plan)))
        if not WRITE:
            continue
        # en_US zuerst: Strukturaenderung in der Quellsprache wird von Odoo auf die
        # uebrigen Sprachen uebertragen (Begriffs-Uebersetzungen bleiben erhalten).
        # Danach jede noch betroffene Sprache einzeln nachziehen.
        for lang in sorted(plan, key=lambda l: (l != 'en_US', l)):
            current = _raw_arch(view.id).get(lang)
            new_arch, hits = _clean(current)
            if not hits:
                continue
            view.with_context(lang=lang).write({'arch_db': new_arch})
            view.invalidate_recordset(['arch_db'])
        still = [lang for lang, arch in _raw_arch(view.id).items() if _clean(arch)[1]]
        print('    -> geschrieben; noch betroffen: %s' % (still or 'keine'))

    print('Treffer gesamt: %s (%s)' % (total, 'GESCHRIEBEN' if WRITE else 'Dry-Run, nichts geaendert'))
    if WRITE:
        env.cr.commit()
        print('Commit ausgefuehrt. Danach Seite im Browser (Quelltext) pruefen.')
    else:
        env.cr.rollback()


if SCAN_HTML:
    _scan_event_html()
else:
    _fix_views()
