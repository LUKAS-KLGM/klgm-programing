# -*- coding: utf-8 -*-
"""Setzt die website-spezifische Editor-Kopie der Einrichtungsliste zurueck.

Befund (Abgleich 22.10.2026): Neben der Modul-Ansicht
kjr_facility.website_facility_list (website_id leer) gibt es eine
website-spezifische Kopie (Live: ir_ui_view 4332, website_id=3). Odoo nimmt fuer
die Website immer die Kopie. Beim Modul-Update gleicht Odoo eine Kopie nur ab,
solange sie unveraendert ist (base ir_ui_view._load_records_write), danach
bleibt sie auf dem alten Stand stehen. Folge live: /service/einrichtungen zeigt
beim Zeltplatz "40 Betten" statt "40 Plaetze", und jede kuenftige Code-Aenderung
an der Liste bleibt wirkungslos.

Autor:   KLGM UG (haftungsbeschraenkt), https://www.klgm-consulting.de
Lizenz:  OPL-1
Stand:   2026-10-22
Anleitung: tools/website_fixes/README.md, Befund C (vor JEDER Ausfuehrung lesen).

AUSFUEHREN DARF DAS SKRIPT NUR EINE BERECHTIGTE PERSON auf dem Server bzw.
einer Server-Kopie, nach einem Snapshot.

Betriebsarten (Umgebungsvariablen):
    (keine)               Probelauf: zeigt alle website-spezifischen Kopien von
                          kjr_*-Ansichten, vergleicht die Kopie der
                          Einrichtungsliste mit der Modul-Ansicht und zeigt die
                          Unterschiede. Schreibt nichts, Rollback.
    KJR_FIX_WRITE=1       sichert die Kopie als JSON und loescht sie, aber NUR,
                          wenn sie einem bekannten Modulstand entspricht (keine
                          erkennbare Inhaltsaenderung des KJR). Sonst nur Meldung.
    KJR_FIX_FORCE=1       (nur zusammen mit KJR_FIX_WRITE=1) loescht die Kopie
                          auch bei erkennbaren Inhaltsaenderungen. Nur nach
                          Ruecksprache mit dem KJR; die gemeldeten Texte sind
                          danach nur noch in der Sicherung.
    KJR_FIX_KEY=<key>     andere Ansicht pruefen (Standard:
                          kjr_facility.website_facility_list). Bekannte
                          Modulstaende gibt es nur fuer den Standard-Key; fuer
                          andere Keys gilt nur "identisch mit Modul-Ansicht" als
                          unbedenklich.
    KJR_FIX_BACKUP_DIR=<pfad>  Ablage der Sicherung (Standard: aktuelles
                          Verzeichnis).
    KJR_FIX_RESTORE=<datei>    spielt eine Sicherung dieses Skripts zurueck
                          (gleiche ID, alle Sprachfassungen). Nur mit
                          KJR_FIX_WRITE=1 wird committet.

Aufruf (auf dem Server):
    odoo-bin shell -c odoo.conf -d <db> --no-http < reset_facility_list_copy.py
    KJR_FIX_WRITE=1 odoo-bin shell -c odoo.conf -d <db> --no-http < reset_facility_list_copy.py

Ausgabe: Ansichts-IDs, Keys, Website, Unterschiede im Template-Quelltext; keine
personenbezogenen Daten.
"""
import datetime
import difflib
import hashlib
import json
import os

from lxml import etree

DEFAULT_KEY = 'kjr_facility.website_facility_list'

# Fingerabdruecke (normalisierter Quelltext, siehe _norm_lines) aller
# ausgelieferten Fassungen von kjr_facility.website_facility_list laut
# Git-Historie. Entspricht eine Kopie einer dieser Fassungen, hat niemand
# Inhalte im Editor geaendert -> Kopie kann weg.
KNOWN_MODULE_VERSIONS = {
    'd062d1b823eebdd9': 'b76e77f (2026-10-22)',
    '47de1c6c89e164ec': 'd7e79f4 (2026-09-10)',
    'da3f5ed595654008': 'b5bbf30 (2026-08-22)',
    'de722d09bbca5b9e': 'd51edc5 (2026-08-16)',
    '5d9f67235514f150': '2350b8d (2026-06-21)',
}
# Fingerabdruecke aller Zeilen dieser Fassungen. Nur fuer die Einordnung der
# Unterschiede in der Ausgabe ("alter Modulstand" oder "nicht aus dem Modul").
KNOWN_MODULE_LINES = set()  # wird unten befuellt (_KNOWN_LINES_RAW)


def _ws(value):
    return ' '.join((value or '').split())


def _ser(el):
    attrs = ' '.join('%s="%s"' % (k, _ws(v)) for k, v in sorted(el.attrib.items()))
    parts = ['<%s%s>' % (el.tag, (' ' + attrs) if attrs else '')]
    if _ws(el.text):
        parts.append(_ws(el.text))
    for child in el:
        if isinstance(child.tag, str):  # Kommentare und PIs zaehlen nicht
            parts.append(_ser(child))
        if _ws(child.tail):
            parts.append(_ws(child.tail))
    parts.append('</%s>' % el.tag)
    return ''.join(parts)


def _norm_lines(arch):
    """Template-Inhalt ohne Wurzel (<template>/<t t-name>), ohne Kommentare,
    Leerraum zusammengefasst, Attribute sortiert; ein Element je Zeile."""
    if isinstance(arch, str):
        arch = arch.encode('utf-8')
    root = etree.fromstring(arch)
    out = []
    if _ws(root.text):
        out.append(_ws(root.text))
    for child in root:
        if isinstance(child.tag, str):
            out.append(_ser(child))
        if _ws(child.tail):
            out.append(_ws(child.tail))
    return '\n'.join(out).replace('><', '>\n<').split('\n')


def _fp(lines):
    return hashlib.sha256('\n'.join(lines).encode('utf-8')).hexdigest()[:16]


def _line_fp(line):
    return hashlib.sha256(line.encode('utf-8')).hexdigest()[:12]


_KNOWN_LINES_RAW = """
06c4041be36c 06d05f481fd7 0834ed733371 1912d0a796fd 25f0f6427174 2a4cf1207bd5
2b9a69445a59 2bc41db682db 3973d706f375 4f2384a77c82 594fbba1e976 5d7da2533fa4
60cd30ffe1b2 63886118efcc 649dd755a7d9 669df4e94e0d 75276f3cd019 759804221693
77017b6a4ca3 802c0dfbb0bf 81d331d183df 826f0ac88266 855ecbdfacf3 87fc08277e74
a3c12ce379cb a86ceef69e39 aa2cc2132e51 aac32651b10f b6fd6d800c59 b8bf820e855a
cd66d3745603 cf16ee2a8dac cfe683dcab5a d6dc1aad6b63 da8751729f98 edde0c228fef
f518a3c40345 fb83c3cc1a98 fcf284dc7828
"""
KNOWN_MODULE_LINES.update(_KNOWN_LINES_RAW.split())


def _list_kjr_copies(env):
    env.cr.execute("""
        SELECT s.id, s.key, s.website_id, s.active, s.inherit_id, g.id,
               (s.arch_db->>'en_US') = (g.arch_db->>'en_US'),
               s.create_date, cu.login
          FROM ir_ui_view s
     LEFT JOIN ir_ui_view g ON g.key = s.key AND g.website_id IS NULL
     LEFT JOIN res_users cu ON cu.id = s.create_uid
         WHERE s.website_id IS NOT NULL AND s.key LIKE 'kjr%%'
      ORDER BY s.key, s.id""")
    rows = env.cr.fetchall()
    print('Website-spezifische Kopien von kjr_*-Ansichten: %d' % len(rows))
    for vid, key, wid, active, inherit, gid, same, cdate, login in rows:
        print('  - %s %s website=%s aktiv=%s erbt_von=%s modul_view=%s '
              'gleich_wie_modul(en_US)=%s angelegt=%s von=%s' % (
                  vid, key, wid, active, inherit or '-', gid or '-', same,
                  cdate and cdate.strftime('%Y-%m-%d'), login))
    print()


def _classify(env, copy, generic, key):
    """Liefert (unbedenklich, bericht_zeilen)."""
    report = []
    generic_lines = _norm_lines(generic.with_context(lang='en_US').arch_db)
    known = dict(KNOWN_MODULE_VERSIONS) if key == DEFAULT_KEY else {}
    known[_fp(generic_lines)] = 'aktuelle Modul-Ansicht %s' % generic.id
    env.cr.execute('SELECT arch_db FROM ir_ui_view WHERE id = %s', (copy.id,))
    arch_by_lang = env.cr.fetchone()[0] or {}
    harmless = True
    for lang in sorted(arch_by_lang):
        try:
            lines = _norm_lines(arch_by_lang[lang])
        except etree.XMLSyntaxError as exc:
            report.append('  [%s] nicht parsebar (%s) -> nur Meldung' % (lang, exc))
            harmless = False
            continue
        match = known.get(_fp(lines))
        if match:
            report.append('  [%s] entspricht Modulstand %s -> keine Inhaltsaenderung' % (lang, match))
            continue
        harmless = False
        report.append('  [%s] weicht von allen bekannten Modulstaenden ab. '
                      'Unterschiede (- Modul-Ansicht, + Kopie):' % lang)
        for diff in difflib.unified_diff(generic_lines, lines, lineterm='', n=0):
            if diff.startswith(('---', '+++', '@@')):
                continue
            note = ''
            if diff.startswith('+'):
                note = ('   [alter Modulstand]' if _line_fp(diff[1:]) in KNOWN_MODULE_LINES
                        else '   [NICHT aus dem Modul: Inhaltsaenderung im Editor]')
            report.append('      %s%s' % (diff, note))
    return harmless, report


def _backup(env, copy, backup_dir):
    env.cr.execute('SELECT row_to_json(v) FROM ir_ui_view v WHERE id = %s', (copy.id,))
    row = env.cr.fetchone()[0]
    env.cr.execute("""SELECT row_to_json(d) FROM ir_model_data d
                       WHERE model = 'ir.ui.view' AND res_id = %s""", (copy.id,))
    imd = [r[0] for r in env.cr.fetchall()]
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    path = os.path.join(backup_dir, 'backup_ir_ui_view_%s_%s.json' % (copy.id, stamp))
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump({'db': env.cr.dbname, 'ir_ui_view': row, 'ir_model_data': imd},
                  fh, ensure_ascii=False, indent=1, default=str)
    return path


def _restore(env, path, write):
    with open(path, encoding='utf-8') as fh:
        data = json.load(fh)
    row = data['ir_ui_view']
    if env['ir.ui.view'].browse(row['id']).exists():
        print('Ansicht %s existiert bereits, nichts zurueckgespielt.' % row['id'])
        return
    env.cr.execute("""INSERT INTO ir_ui_view
                      SELECT * FROM json_populate_record(NULL::ir_ui_view, %s::json)""",
                   (json.dumps(row),))
    for imd in data.get('ir_model_data') or []:
        env.cr.execute("""INSERT INTO ir_model_data
                          SELECT * FROM json_populate_record(NULL::ir_model_data, %s::json)""",
                       (json.dumps(imd),))
    env.registry.clear_cache('templates')
    env.invalidate_all()
    print('Ansicht %s (%s) aus %s zurueckgespielt.' % (row['id'], row['key'], path))
    if write:
        env.cr.commit()
        print('Committet.')
    else:
        env.cr.rollback()
        print('Probelauf: zurueckgerollt (KJR_FIX_WRITE=1 zum Schreiben).')


def main(env):
    write = os.environ.get('KJR_FIX_WRITE') == '1'
    force = write and os.environ.get('KJR_FIX_FORCE') == '1'
    key = os.environ.get('KJR_FIX_KEY') or DEFAULT_KEY
    backup_dir = os.environ.get('KJR_FIX_BACKUP_DIR') or os.getcwd()
    restore = os.environ.get('KJR_FIX_RESTORE')
    print('=== reset_facility_list_copy: %s ===' % (
        'SCHREIBLAUF' + (' (FORCE)' if force else '') if write else 'Probelauf'))
    if restore:
        _restore(env, restore, write)
        return

    _list_kjr_copies(env)

    View = env['ir.ui.view'].with_context(active_test=False)
    generic = View.search([('key', '=', key), ('website_id', '=', False)], limit=1)
    if not generic:
        print('Modul-Ansicht %s nicht gefunden, Abbruch.' % key)
        return
    copies = View.search([('key', '=', key), ('website_id', '!=', False)])
    print('Modul-Ansicht: %s (%s)' % (generic.id, key))
    if not copies:
        print('Keine website-spezifische Kopie vorhanden. Nichts zu tun.')
        return
    deleted = []
    for copy in copies:
        print('Kopie %s: website=%s (%s) aktiv=%s angelegt=%s von %s' % (
            copy.id, copy.website_id.id, copy.website_id.name, copy.active,
            copy.create_date, copy.create_uid.login))
        harmless, report = _classify(env, copy, generic, key)
        print('\n'.join(report))
        children = View.search([('inherit_id', '=', copy.id)])
        pages = env['website.page'].with_context(active_test=False).search([('view_id', '=', copy.id)])
        if children or pages:
            print('  -> Kopie hat erbende Ansichten %s bzw. Seiten %s: nur Meldung, '
                  'bitte von Hand im Website-Builder pruefen.' % (children.ids, pages.ids))
            continue
        if not harmless and not force:
            print('  -> Erkennbare Inhaltsaenderung: Kopie bleibt bestehen (nur Meldung). '
                  'Texte mit dem KJR klaeren; danach ggf. KJR_FIX_FORCE=1.')
            continue
        if not write:
            print('  -> wuerde gesichert und geloescht (Probelauf).')
            continue
        path = _backup(env, copy, backup_dir)
        print('  -> Sicherung: %s' % path)
        copy.with_context(no_cow=True).unlink()
        deleted.append(copy.id)
        print('  -> geloescht.')
    if write and deleted:
        env.registry.clear_cache('templates')
        env.cr.commit()
        remaining = View.search([('key', '=', key), ('website_id', '!=', False)])
        print('Committet. Geloescht: %s. Verbleibende Kopien: %s' % (
            deleted, remaining.ids or 'keine'))
    else:
        env.cr.rollback()
        print('Nichts geschrieben.')


if 'env' in globals():
    main(env)  # noqa: F821  (odoo shell stellt env bereit)
