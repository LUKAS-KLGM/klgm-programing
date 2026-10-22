# -*- coding: utf-8 -*-
"""Seitenfuß nach Entscheidung 10 (Termin 13.10.2026): Blöcke entfernen, Kontaktlink.

Entscheidung 10: Seitenübersicht und Kontaktblock raus, ein Link zur
Kontaktseite rein. Rechtliches (Impressum, Datenschutz, Cookies,
Barrierefreiheit) und Suche bleiben. Keine neue Gestaltung: das Skript ENTFERNT
nur Blöcke und setzt EINEN Link im Stil der übrigen Fußzeilen-Links
(<p><a class="o_translate_inline">) dorthin, wo bisher der Kontaktblock unter
dem Logo stand. Die Rasterhöhe der Logo-Spalte und die Zeilenzahl des Rasters
werden auf den verbleibenden Inhalt gekürzt, sonst bliebe eine leere Fläche
in Höhe der entfernten Blöcke.

Autor:   KLGM UG (haftungsbeschraenkt), https://www.klgm-consulting.de
Lizenz:  OPL-1
Stand:   2026-10-22
Anleitung: tools/website_fixes/README.md, Abschnitt „Befund B“ (vor JEDER
Ausfuehrung lesen).

AUSFUEHREN DARF DAS SKRIPT NUR EINE BERECHTIGTE PERSON auf dem Server bzw.
einer Server-Kopie, nach einem Snapshot. Nicht lokal, nicht durch den
Assistenten.

Betriebsarten (Umgebungsvariablen):
    (keine)                  Dry-Run: schreibt die neue Fassung im Transaktions-
                             rahmen, prueft sie und rollt zurueck. Aendert nichts.
    KJR_FIX_WRITE=1          schreibt (Backup-Datei zuerst) und committet.
    KJR_FOOTER_VIEW_ID=<id>  Ansicht ausdruecklich angeben (sonst: die eine
                             website-eigene Ansicht website.template_footer_mega_links).
    KJR_FOOTER_CONTACT_URL   Ziel des Kontaktlinks (Vorgabe /ueber-uns/contactus).
    KJR_FOOTER_OUT=<ordner>  Ablage fuer Backup und neue Fassung (Vorgabe: aktuelles
                             Verzeichnis). Dateien: footer_<id>_backup_<zeit>.json
                             (alle Sprachfassungen roh) und footer_<id>_<lang>_neu.xml.

Aufruf (auf dem Server, NICHT lokal):
    odoo shell -d <db> --no-http < footer_2026-10.py                    # Dry-Run
    KJR_FIX_WRITE=1 odoo shell -d <db> --no-http < footer_2026-10.py    # schreibt

Erkennung der Bloecke (je Sprachfassung, mit lxml, ohne Textersetzung):
- behalten: Rasterelement mit Bild (Logo, samt mobiler Suche), Rasterelement mit
  Suchformular (Suche Desktop), Rasterelement mit Ueberschrift „Rechtliches“
- entfernen: alle uebrigen Rasterelemente (Seitenuebersicht samt Linkspalten,
  Kontakt „BÜROS“) sowie im Logo-Element alles nach der mobilen Suche
  (Trennlinie, Kontakt „POSTADRESSE“)
Weicht der Aufbau ab (nicht genau ein Logo-, Such- und Rechtliches-Element,
keine mobile Suche, Kontaktlink schon vorhanden), bricht das Skript ohne
Aenderung ab.
"""
import json
import os
import re
import time

from lxml import etree

WRITE = os.environ.get('KJR_FIX_WRITE') == '1'
VIEW_KEY = 'website.template_footer_mega_links'
CONTACT_URL = os.environ.get('KJR_FOOTER_CONTACT_URL') or '/ueber-uns/contactus'
CONTACT_LABEL = 'Kontakt'
OUT = os.environ.get('KJR_FOOTER_OUT') or os.getcwd()
GRID_AREA_RE = re.compile(r'grid-area:\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)')
# Rasterhoehe der Logo-Spalte nach dem Kuerzen (Zeilen a 50 px): Logo und Link.
# Das Logo ist hochkant (900 x 1273 px) und waechst mit der Spaltenbreite: bei
# 1920 px Fensterbreite etwa 370 px hoch, dazu der Link. 10 Zeilen (500 px)
# reichen bis etwa 2200 px Fensterbreite; vorher waren es 16 Zeilen.
LOGO_ROWS = 10


class Abbruch(Exception):
    pass


def _classes(el):
    return (el.get('class') or '').split()


def _text(el):
    return ' '.join(''.join(el.itertext()).split())


def _grid_area(el):
    m = GRID_AREA_RE.search(el.get('style') or '')
    return tuple(int(x) for x in m.groups()) if m else None


def _set_grid_rows(el, rows):
    """Zeilenende des Rasterelements setzen und g-height-* anpassen."""
    area = _grid_area(el)
    r0, c0, _r1, c1 = area
    el.set('style', GRID_AREA_RE.sub(
        'grid-area: %d / %d / %d / %d' % (r0, c0, r0 + rows, c1), el.get('style')))
    el.set('class', ' '.join(
        'g-height-%d' % rows if c.startswith('g-height-') else c for c in _classes(el)))


def neue_fassung(arch):
    """Liefert (neue_arch, protokoll). Wirft Abbruch bei unerwartetem Aufbau."""
    parser = etree.XMLParser(remove_blank_text=False, strip_cdata=False, resolve_entities=False)
    root = etree.fromstring(arch.encode('utf-8'), parser)
    if root.xpath('.//a[@href=$u]', u=CONTACT_URL) and not root.xpath(
            './/*[contains(concat(" ", @class, " "), " o_grid_item ")]//h2[contains(., "Seitenübersicht")]'):
        raise Abbruch('Kontaktlink vorhanden und keine Seitenübersicht: offenbar schon umgestellt.')
    rows = root.xpath('.//div[@id="footer"]//div[contains(concat(" ", @class, " "), " o_grid_mode ")]')
    if len(rows) != 1:
        raise Abbruch('Raster im Fuß nicht eindeutig gefunden (%d).' % len(rows))
    row = rows[0]
    items = [el for el in row if isinstance(el.tag, str) and 'o_grid_item' in _classes(el)]
    logo = [el for el in items if el.xpath('.//img')]
    search = [el for el in items if el.xpath('.//form') and not el.xpath('.//img')]
    legal = [el for el in items if any('Rechtliches' in _text(h) for h in el.xpath('.//h2'))]
    if len(logo) != 1 or len(search) != 1 or len(legal) != 1:
        raise Abbruch('Erwartet je ein Logo-, Such- und Rechtliches-Element, gefunden %d/%d/%d.'
                      % (len(logo), len(search), len(legal)))
    logo, search, legal = logo[0], search[0], legal[0]
    for needed in ('/impressum', '/datenschutzerklaerung', '/cookie-richtlinie', '/barrierefreiheit'):
        if not legal.xpath('.//a[@href=$u]', u=needed):
            raise Abbruch('Rechtliches ohne Link %s - Aufbau weicht ab.' % needed)
    log = []
    keep = {logo, search, legal}
    for el in items:
        if el not in keep:
            log.append('entfernt: Rasterelement „%s…“' % _text(el)[:60])
            row.remove(el)
    # Logo-Element: alles nach der mobilen Suche entfernen (Trennlinie, Kontaktblock).
    mobile = logo.xpath('./div[contains(concat(" ", @class, " "), " kjr-footer-search-mobile ")]')
    if len(mobile) != 1:
        raise Abbruch('Mobile Suche im Logo-Element nicht gefunden.')
    mobile = mobile[0]
    removed = []
    for sib in list(mobile.itersiblings()):
        removed.append(_text(sib)[:40] or sib.tag)
        logo.remove(sib)
    mobile.tail = None
    if not any('Kontakt' in r or 'Oberallgäuer' in r for r in removed):
        raise Abbruch('Im Logo-Element stand kein Kontaktblock hinter der mobilen Suche.')
    log.append('entfernt im Logo-Element: %s' % ' | '.join(removed))
    # Kontaktlink im Stil der uebrigen Fusslinks.
    p = etree.SubElement(logo, 'p')
    a = etree.SubElement(p, 'a', {'href': CONTACT_URL, 'class': 'o_translate_inline'})
    a.text = CONTACT_LABEL
    log.append('eingefügt im Logo-Element: <p><a href="%s">%s</a></p>' % (CONTACT_URL, CONTACT_LABEL))
    # Raster auf den Inhalt kuerzen.
    _set_grid_rows(logo, LOGO_ROWS)
    last = max(_grid_area(el)[2] for el in (logo, search, legal)) - 1
    if row.get('data-row-count'):
        log.append('Rasterzeilen: %s -> %d' % (row.get('data-row-count'), last))
        row.set('data-row-count', str(last))
    return etree.tostring(root, encoding='unicode'), log


def pruefen(arch):
    """Ergebnis gegen Entscheidung 10 pruefen. Liefert Liste der Fehler."""
    root = etree.fromstring(arch.encode('utf-8'))
    fehler = []
    for href in ('/impressum', '/datenschutzerklaerung', '/cookie-richtlinie', '/barrierefreiheit', CONTACT_URL):
        if not root.xpath('.//a[@href=$u]', u=href):
            fehler.append('Link fehlt: %s' % href)
    if len(root.xpath('.//form[@action="/website/search"]')) != 2:
        fehler.append('Suche (mobil und Desktop) nicht vollständig')
    text = _text(root)
    for weg in ('Seitenübersicht', 'POSTADRESSE', 'BÜROS', 'Oberallgäuer Platz', 'Mühlenweg', 'Mitgliedsverbände'):
        if weg in text:
            fehler.append('noch vorhanden: %s' % weg)
    return fehler


def _raw_arch(view_id):
    env.cr.execute('SELECT arch_db FROM ir_ui_view WHERE id = %s', (view_id,))
    row = env.cr.fetchone()
    return (row and row[0]) or {}


def _find_view():
    View = env['ir.ui.view'].with_context(active_test=False)
    if os.environ.get('KJR_FOOTER_VIEW_ID'):
        view = View.browse(int(os.environ['KJR_FOOTER_VIEW_ID'])).exists()
        if not view or view.key != VIEW_KEY:
            raise Abbruch('KJR_FOOTER_VIEW_ID zeigt nicht auf %s.' % VIEW_KEY)
        return view
    views = View.search([('key', '=', VIEW_KEY), ('website_id', '!=', False)])
    if len(views) != 1:
        raise Abbruch('%d website-eigene Ansichten %s gefunden; bitte KJR_FOOTER_VIEW_ID setzen.'
                      % (len(views), VIEW_KEY))
    return views


def main():
    view = _find_view()
    print('Ansicht %s key=%r website_id=%s aktiv=%s' % (view.id, view.key, view.website_id.id, view.active))
    raw = _raw_arch(view.id)
    plan = {}
    for lang, arch in sorted(raw.items()):
        new_arch, log = neue_fassung(arch)
        fehler = pruefen(new_arch)
        if fehler:
            raise Abbruch('%s: neue Fassung verletzt Entscheidung 10: %s' % (lang, fehler))
        plan[lang] = new_arch
        print('  %s:' % lang)
        for line in log:
            print('    - %s' % line)
        path = os.path.join(OUT, 'footer_%d_%s_neu.xml' % (view.id, lang))
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(new_arch)
        print('    neue Fassung: %s' % path)

    if WRITE:
        backup = os.path.join(OUT, 'footer_%d_backup_%s.json' % (view.id, time.strftime('%Y%m%d-%H%M%S')))
        with open(backup, 'w', encoding='utf-8') as fh:
            json.dump(raw, fh, ensure_ascii=False, indent=1)
        print('Backup (alle Sprachfassungen roh): %s' % backup)

    # Schreiben ueber das ORM (Validierung, Caches), en_US zuerst, danach jede
    # Sprache, die noch nicht dem Plan entspricht. Ohne website_id im Kontext
    # und mit no_cow: die website-eigene Ansicht wird direkt geaendert.
    target = view.with_context(no_cow=True)
    for lang in sorted(plan, key=lambda l: (l != 'en_US', l)):
        current = _raw_arch(view.id).get(lang)
        if current and not pruefen(current):
            continue
        target.with_context(lang=lang).write({'arch_db': neue_fassung(current)[0]})
        target.invalidate_recordset(['arch_db'])
    nachher = _raw_arch(view.id)
    offen = {lang: pruefen(arch) for lang, arch in nachher.items() if pruefen(arch)}
    print('Nach dem Schreiben: %s' % ('alle Sprachen geprüft, in Ordnung' if not offen else offen))

    # Kombinierte Vorlage website.layout pruefen (so, wie die Website sie
    # zusammensetzt). Ein echtes Rendern braucht eine HTTP-Anfrage und ist
    # deshalb Schritt 5 der Anleitung (Startseite im Browser bzw. per curl).
    website = view.website_id
    layout = env['ir.ui.view'].with_context(website_id=website.id, lang='de_DE')._get_template_view(
        'website.layout')
    combined = layout._get_combined_arch()
    footers = combined.xpath('//div[@id="footer"]')
    print('Kombinierte Vorlage website.layout: Fuß %s, Kontaktlink %s, Seitenübersicht %s.' % (
        'gefunden' if footers else 'NICHT gefunden',
        'vorhanden' if footers and footers[0].xpath('.//a[@href=$u]', u=CONTACT_URL) else 'FEHLT',
        'noch vorhanden' if footers and 'Seitenübersicht' in _text(footers[0]) else 'entfernt'))

    if WRITE and not offen:
        env.cr.commit()
        print('Commit ausgeführt. Danach Startseite in jeder Sprache prüfen (README, Befund B).')
    else:
        env.cr.rollback()
        print('Dry-Run bzw. Fehler: zurückgerollt, nichts geändert.')


try:
    main()
except Abbruch as exc:
    env.cr.rollback()
    print('ABBRUCH, nichts geändert: %s' % exc)
