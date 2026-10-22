# -*- coding: utf-8 -*-
"""Beispielartikel und Mitgliedstarif-Hinweise auf Bestandsinstanzen entfernen.

1. Die sechs Beispielartikel aus data/kjr_rental_data.xml (bis 19.0.5.7.0):
   9-Sitzer Bus, Gruppenzelt, PA-Anlage, Sportgeräte-Set, Feldküche und
   Großspielgeräte. Sie standen auf Bestandsinstanzen mit erfundenen Preisen und
   Mitgliedstarifen im öffentlichen Katalog (Rückmeldung des Betreibers vom
   14.10.2026: es gibt nur einen Bus und keine Mitgliedspreise). Die Sätze liegen
   unter noupdate="1"; das Entfernen aus der Datendatei allein löscht sie nicht.

   Regeln:
   - Gefunden wird nur über die XML-ID, nie über den Namen.
   - Trägt der Artikel nicht mehr seinen Auslieferungsnamen, hat die
     Geschäftsstelle ihn übernommen: er bleibt unverändert (Protokoll).
   - Hängt der Artikel an einer Ausleihe oder Inventur, wird er archiviert und
     von der Website genommen (die Historie bleibt lesbar). Sonst gelöscht.
   - Der Spielmobil-Artikel (item_spielmobil) bleibt, er ist kein Beispielartikel.

2. Ansichten, die die Katalogseite erweitern (z. B. ein im Website-Editor
   angelegter Infotext), werden von zwei Sätzen befreit: dem Hinweis auf
   vergünstigte Mitgliedstarife und dem Umsatzsteuerhinweis, der dem neutralen
   Preishinweis der Katalogseite widersprach (Umsatzsteuer im Verleih ist noch
   nicht geklärt). Ersetzt wird nur der exakt bekannte Wortlaut; abweichend
   gepflegte Texte bleiben unberührt und werden protokolliert.

Idempotent: ein zweiter Lauf findet nichts mehr.
"""
import json
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# (XML-ID, Auslieferungsname)
BEISPIELARTIKEL = [
    ('kjr_rental.item_bus', '9-Sitzer Bus'),
    ('kjr_rental.item_tent', 'Gruppenzelt (10 Pers.)'),
    ('kjr_rental.item_pa', 'PA-Anlage'),
    ('kjr_rental.item_balls', 'Sportgeräte-Set'),
    ('kjr_rental.item_kitchen', 'Feldküche'),
    ('kjr_rental.item_games', 'Großspielgeräte (Kubb, Twister XXL)'),
]

# Exakte Textstellen, die aus erweiternden Ansichten der Katalogseite entfallen.
# Die Ortsbezeichnung im ersten Satz ist der Wortlaut der Bestandsinstanz; das
# Modul selbst liefert ihn nicht aus.
ENTFERNEN = [
    '\n            <p class="text-muted mb-2">Mitgliedsverbände des Kreisjugendrings '
    'erhalten vergünstigte Tarife.</p>',
    '\n            <p class="text-muted mb-0"><strong>Hinweis zur Umsatzsteuer:</strong> '
    'Für Jugendgruppen und Jugendverbände, die Jugendarbeit im Sinne der §§ 11 ff. '
    'SGB VIII durchführen, gelten die angegebenen Preise ohne Umsatzsteuer. Bei '
    'gewerblicher Nutzung wird die Umsatzsteuer zusätzlich berechnet.</p>',
]
# Bleibt nach dem Entfernen ein anderer Wortlaut mit diesen Stichwörtern stehen,
# wird er nur protokolliert.
STICHWOERTER = ('vergünstigte Tarife', 'ohne Umsatzsteuer', 'Mitgliedstarif')


def _beispielartikel_entfernen(env):
    Item = env['kjr.rental.item'].with_context(active_test=False)
    for xmlid, name in BEISPIELARTIKEL:
        item = env.ref(xmlid, raise_if_not_found=False)
        if not item or item._name != 'kjr.rental.item':
            continue
        item = Item.browse(item.id)
        if (item.name or '').strip() != name:
            _logger.info('%s (id %s) heißt jetzt "%s" und wurde gepflegt: unverändert.',
                         xmlid, item.id, item.name)
            continue
        used = (env['kjr.rental.order.line'].sudo().search_count([('item_id', '=', item.id)])
                + env['kjr.rental.inventory.line'].sudo().search_count([('item_id', '=', item.id)]))
        if used:
            item.write({'active': False, 'website_published': False})
            _logger.info('%s (id %s, "%s") hat %d Ausleih-/Inventurposition(en): archiviert.',
                         xmlid, item.id, name, used)
        else:
            item.unlink()
            _logger.info('%s (id %s, "%s") gelöscht.', xmlid, item.id, name)


def _katalogtexte_bereinigen(env):
    catalog = env.ref('kjr_rental.website_rental_catalog', raise_if_not_found=False)
    if not catalog:
        return
    cr = env.cr
    cr.execute("""
        SELECT id, arch_db FROM ir_ui_view
         WHERE inherit_id = %s AND arch_db IS NOT NULL
    """, (catalog.id,))
    for view_id, arch in cr.fetchall():
        if isinstance(arch, str):
            arch = json.loads(arch)
        changed = False
        for lang, text in arch.items():
            new = text
            for snippet in ENTFERNEN:
                new = new.replace(snippet, '')
            if new != text:
                arch[lang] = new
                changed = True
            for word in STICHWOERTER:
                if word in new:
                    _logger.warning('Ansicht %s (%s) enthält weiterhin "%s" in abweichendem '
                                    'Wortlaut: bitte im Website-Editor prüfen.',
                                    view_id, lang, word)
        if changed:
            cr.execute('UPDATE ir_ui_view SET arch_db = %s WHERE id = %s',
                       (json.dumps(arch), view_id))
            _logger.info('Ansicht %s: Mitgliedstarif-/Umsatzsteuerhinweis entfernt.', view_id)
    env.registry.clear_cache('templates')


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    _beispielartikel_entfernen(env)
    _katalogtexte_bereinigen(env)
