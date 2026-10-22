# -*- coding: utf-8 -*-
"""Doppelte Verleih-Kategorien und -Lagerorte bereinigen (kjr_rental).

Befund (Prod, lesend geprüft am 22.10.2026):
- Kategorien: IDs 1-7 ohne XML-ID (Altbestand vom 25.06.2026) und IDs 9-15 mit
  XML-ID kjr_rental.cat_* tragen dieselben Namen. Alle Artikel hängen an den
  Sätzen mit XML-ID (bzw. an "Besteck", id 16, ohne Gegenstück).
- Lagerorte: "Lager Sonthofen/Immenstadt/Oberstdorf" (IDs 10-12, ohne XML-ID)
  sind die alten Auslieferungsnamen der Sätze kjr_rental.loc_* (IDs 13-15, seit
  19.0.5.5.0 "Hauptlager/Nebenlager/Außenlager"). Dazu drei Adress-Lagerorte
  (IDs 4-6) und die drei Bestände aus 19.0.5.7.0 (IDs 16-18). Kein Artikel hat
  einen Lagerort.

Autor:   KLGM UG (haftungsbeschraenkt), https://www.klgm-consulting.de
Lizenz:  OPL-1
Stand:   2026-10-22

AUSFUEHREN DARF DAS SKRIPT NUR EINE BERECHTIGTE PERSON auf dem Server bzw.
einer Server-Kopie, nach einem Snapshot. Nicht durch den Assistenten.

Betriebsarten (Umgebungsvariablen):
    (keine)          Dry-Run: listet, was geschehen wuerde, schreibt nichts.
    KJR_FIX_WRITE=1  fuehrt die Bereinigung aus und committet.

Aufruf (auf dem Server):
    odoo-bin shell -c odoo.conf -d <db> --no-http < bereinige_dubletten.py
    KJR_FIX_WRITE=1 odoo-bin shell -c odoo.conf -d <db> --no-http < bereinige_dubletten.py

Regeln:
1. Kategorie ohne XML-ID, deren Name (ohne Ruecksicht auf Gross-/Klein-
   schreibung und Leerzeichen) einer Kategorie MIT XML-ID aus kjr_rental
   entspricht: alle Artikel (auch archivierte) werden auf die Kategorie mit
   XML-ID umgehaengt, danach wird die Dublette geloescht. Kategorien ohne
   Gegenstueck (z. B. "Besteck") bleiben unberuehrt.
2. Lagerort ohne XML-ID, der einen ALTEN Auslieferungsnamen traegt ("Lager
   Sonthofen" usw.): Artikel werden auf den zugehoerigen Lagerort mit XML-ID
   umgehaengt, die Dublette geloescht.
3. Alle uebrigen Lagerorte werden NUR AUFGELISTET (mit Artikelzahl). Ob die
   Adress-Lagerorte oder die Platzhalter Haupt-/Neben-/Aussenlager entfallen,
   entscheidet die Geschaeftsstelle; dann im Backend archivieren.
Es werden keine Namen geaendert. Idempotent.
"""
import os

WRITE = os.environ.get('KJR_FIX_WRITE') == '1'

# Alter Auslieferungsname -> XML-ID (siehe kjr_rental/migrations/19.0.5.5.0).
ALTE_LAGERNAMEN = {
    'lager sonthofen': 'kjr_rental.loc_sonthofen',
    'lager immenstadt': 'kjr_rental.loc_immenstadt',
    'lager oberstdorf': 'kjr_rental.loc_oberstdorf',
}


def _key(name):
    return ' '.join((name or '').split()).casefold()


def _xmlid_map(env, model):
    """{res_id: 'modul.name'} fuer alle XML-IDs des Modells."""
    data = env['ir.model.data'].sudo().search([('model', '=', model)])
    return {d.res_id: '%s.%s' % (d.module, d.name) for d in data}


def _umhaengen(env, field, source, target):
    Item = env['kjr.rental.item'].with_context(active_test=False)
    items = Item.search([(field, '=', source.id)])
    print('    %d Artikel von id %s auf id %s umhaengen' % (len(items), source.id, target.id))
    if WRITE and items:
        items.write({field: target.id})
    return items


def bereinigen(env):
    env = env(context=dict(env.context, active_test=False))
    Item = env['kjr.rental.item'].with_context(active_test=False)

    print('== Kategorien')
    Category = env['kjr.rental.category']
    xmlids = _xmlid_map(env, 'kjr.rental.category')
    cats = Category.search([], order='id')
    with_xmlid = {_key(c.name): c for c in cats if xmlids.get(c.id, '').startswith('kjr_rental.')}
    for cat in cats:
        n = Item.search_count([('category_id', '=', cat.id)])
        if cat.id in xmlids:
            print('  id %-3s %-25s %-25s %d Artikel (bleibt)' % (cat.id, cat.name, xmlids[cat.id], n))
            continue
        target = with_xmlid.get(_key(cat.name))
        if not target:
            print('  id %-3s %-25s %-25s %d Artikel (ohne Gegenstueck, bleibt)' % (cat.id, cat.name, '-', n))
            continue
        print('  id %-3s %-25s Dublette von id %s (%s)' % (cat.id, cat.name, target.id, xmlids[target.id]))
        _umhaengen(env, 'category_id', cat, target)
        if WRITE:
            cat.unlink()
            print('    geloescht')

    print('== Lagerorte')
    Location = env['kjr.rental.location']
    xmlids = _xmlid_map(env, 'kjr.rental.location')
    for loc in Location.search([], order='id'):
        n = Item.search_count([('location_id', '=', loc.id)])
        if loc.id in xmlids:
            print('  id %-3s %-40s %-28s %d Artikel (bleibt)' % (loc.id, loc.name, xmlids[loc.id], n))
            continue
        target_xmlid = ALTE_LAGERNAMEN.get(_key(loc.name))
        target = env.ref(target_xmlid, raise_if_not_found=False) if target_xmlid else None
        if not target:
            print('  id %-3s %-40s %-28s %d Artikel (nur gelistet, Entscheidung Geschaeftsstelle)'
                  % (loc.id, loc.name, '-', n))
            continue
        print('  id %-3s %-40s alter Name von id %s (%s)' % (loc.id, loc.name, target.id, target_xmlid))
        _umhaengen(env, 'location_id', loc, target)
        if WRITE:
            loc.unlink()
            print('    geloescht')

    if WRITE:
        env.cr.commit()
        print('== geschrieben und committet')
    else:
        env.cr.rollback()
        print('== Dry-Run: nichts geschrieben (KJR_FIX_WRITE=1 zum Ausfuehren)')


bereinigen(env)  # noqa: F821 - env stellt odoo-bin shell bereit
