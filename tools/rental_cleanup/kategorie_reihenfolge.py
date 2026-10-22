# -*- coding: utf-8 -*-
"""Reihenfolge der Verleih-Kategorien pruefen ("Sonstiges" vor "Besteck").

Befund (Prod, lesend geprueft am 22.10.2026): Kategorie 15 "Sonstiges"
(XML-ID kjr_rental.cat_other, ausgeliefert mit sequence 99) steht auf
sequence 0, Kategorie 16 "Besteck" auf sequence 1. Beides hat admin am
13.10.2026 um 09:24 gesetzt (Termin, Ziehgriff im Backend). Katalog und
Filterleiste auf /service/verleih beginnen deshalb mit "Sonstiges".

Der Code arbeitet richtig (Reihenfolge = Feld sequence, siehe
kjr.rental.item._group_by_category). Die Reihenfolge pflegt der KJR unter
Verleih > Konfiguration > Kategorien per Ziehgriff. Das Skript zeigt sie nur
an und schiebt Sammelkategorien ("Sonstiges", "Sonstige", "Diverses",
"Verschiedenes") auf Wunsch ans Ende.

Autor:   KLGM UG (haftungsbeschraenkt), https://www.klgm-consulting.de
Lizenz:  OPL-1
Stand:   2026-10-22

AUSFUEHREN DARF DAS SKRIPT NUR EINE BERECHTIGTE PERSON auf dem Server bzw.
einer Server-Kopie, nach einem Snapshot und nach Ruecksprache mit dem KJR.

Betriebsarten (Umgebungsvariablen):
    (keine)               Probelauf: listet die Kategorien in Katalog-Reihenfolge
                          und meldet Sammelkategorien, die nicht am Ende stehen.
                          Schreibt nichts.
    KJR_FIX_WRITE=1       sichert sequence aller Kategorien als JSON und setzt
                          jede gemeldete Sammelkategorie auf (hoechste sequence
                          der uebrigen Kategorien + 10, mindestens 99).
    KJR_FIX_BACKUP_DIR=<pfad>  Ablage der Sicherung (Standard: aktuelles
                          Verzeichnis).

Aufruf (auf dem Server):
    odoo-bin shell -c odoo.conf -d <db> --no-http < kategorie_reihenfolge.py
    KJR_FIX_WRITE=1 odoo-bin shell -c odoo.conf -d <db> --no-http < kategorie_reihenfolge.py

Rueckweg: die Sicherung nennt je Kategorie die alte sequence; im Backend per
Ziehgriff oder im Shell mit Category.browse(id).sequence = alt.
"""
import datetime
import json
import os

SAMMEL_NAMEN = {'sonstiges', 'sonstige', 'diverses', 'verschiedenes'}


def _key(name):
    return ' '.join((name or '').split()).casefold()


def main(env):
    write = os.environ.get('KJR_FIX_WRITE') == '1'
    backup_dir = os.environ.get('KJR_FIX_BACKUP_DIR') or os.getcwd()
    print('=== kategorie_reihenfolge: %s ===' % ('SCHREIBLAUF' if write else 'Probelauf'))
    Category = env['kjr.rental.category'].with_context(lang='de_DE')
    Item = env['kjr.rental.item'].with_context(active_test=False)
    cats = Category.search([])  # _order = sequence, name
    published = Item.search([('website_published', '=', True), ('active', '=', True)])
    by_cat = {}
    for item in published:
        by_cat[item.category_id.id] = by_cat.get(item.category_id.id, 0) + 1
    print('Kategorien in Katalog-Reihenfolge (sequence, Name):')
    for cat in cats:
        print('  sequence=%4s  id=%-4s %-25s veroeffentlichte Artikel: %s' % (
            cat.sequence, cat.id, cat.name, by_cat.get(cat.id, 0)))
    visible = cats.filtered(lambda c: by_cat.get(c.id))
    sammel = visible.filtered(lambda c: _key(c.name) in SAMMEL_NAMEN)
    others = visible - sammel
    max_other = max(others.mapped('sequence') or [0])
    wrong = sammel.filtered(lambda c: c.sequence <= max_other)
    print()
    if not wrong:
        print('Sammelkategorien stehen bereits am Ende (oder es gibt keine). Nichts zu tun.')
        return
    target = max(max_other + 10, 99)
    for cat in wrong:
        print('Sammelkategorie "%s" (id %s, sequence %s) steht vor anderen Kategorien '
              '-> Vorschlag sequence %s.' % (cat.name, cat.id, cat.sequence, target))
    if not write:
        print('Probelauf: nichts geschrieben. Die Reihenfolge pflegt der KJR; '
              'nur nach Ruecksprache mit KJR_FIX_WRITE=1 ausfuehren.')
        env.cr.rollback()
        return
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    path = os.path.join(backup_dir, 'backup_kjr_rental_category_sequence_%s.json' % stamp)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump({'db': env.cr.dbname,
                   'kategorien': [{'id': c.id, 'name': c.name, 'sequence': c.sequence}
                                  for c in Category.with_context(active_test=False).search([])]},
                  fh, ensure_ascii=False, indent=1)
    print('Sicherung: %s' % path)
    wrong.write({'sequence': target})
    env.cr.commit()
    print('Committet: %s auf sequence %s.' % (', '.join(wrong.mapped('name')), target))


if 'env' in globals():
    main(env)  # noqa: F821  (odoo shell stellt env bereit)
