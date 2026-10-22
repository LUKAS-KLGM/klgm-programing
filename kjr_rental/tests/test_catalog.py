# -*- coding: utf-8 -*-
"""Katalog des Verleihs (Termin 13.10.2026).

- Reihenfolge der Kategorien folgt dem Feld sequence (Ziehgriff im Backend).
- Die sechs Beispielartikel sind aus den ausgelieferten Daten entfernt.
- Die öffentliche Seite nennt keinen Mitgliedstarif mehr, zeigt den
  Warnhinweis eines Artikels und den neutralen Preishinweis.
"""
import importlib.util
import xml.etree.ElementTree as ElementTree

from odoo.tests import HttpCase, tagged
from odoo.tests.common import TransactionCase
from odoo.tools import file_open
from odoo.tools.misc import file_path

SEED_DATEI = 'kjr_rental/data/kjr_rental_data.xml'
BEISPIEL_XMLIDS = ('item_bus', 'item_tent', 'item_pa', 'item_balls',
                   'item_kitchen', 'item_games')


@tagged('post_install', '-at_install')
class TestKjrRentalCategoryOrder(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Category = cls.env['kjr.rental.category']
        cls.cat_b = Category.create({'name': 'RF Besteck', 'sequence': 30})
        cls.cat_a = Category.create({'name': 'RF Zelte', 'sequence': 10})
        cls.cat_c = Category.create({'name': 'RF Geschirr', 'sequence': 20})
        Item = cls.env['kjr.rental.item']
        cls.items = Item.browse()
        for cat, name in ((cls.cat_b, 'RF Gabel'), (cls.cat_a, 'RF Zelt'),
                          (cls.cat_c, 'RF Teller'), (cls.cat_b, 'RF Löffel')):
            cls.items |= Item.create({'name': name, 'category_id': cat.id,
                                      'price_per_day': 1.0})

    def test_gruppen_nach_reihenfolge(self):
        """Die Kategorien stehen in der Reihenfolge ihres Felds sequence."""
        groups = self.env['kjr.rental.item']._group_by_category(self.items)
        self.assertEqual(list(groups), [self.cat_a, self.cat_c, self.cat_b])
        self.assertEqual(len(groups[self.cat_b]), 2)

    def test_umsortieren_wirkt_sofort(self):
        """Ziehen im Backend ändert sequence, der Katalog folgt ohne weitere Pflege."""
        self.cat_b.sequence = 1
        groups = self.env['kjr.rental.item']._group_by_category(self.items)
        self.assertEqual(list(groups)[0], self.cat_b)

    def test_gleiche_reihenfolge_nach_name(self):
        """Bei gleicher Reihenfolge entscheidet der Name."""
        (self.cat_a | self.cat_b | self.cat_c).write({'sequence': 5})
        groups = self.env['kjr.rental.item']._group_by_category(self.items)
        self.assertEqual(list(groups), [self.cat_b, self.cat_c, self.cat_a])

    def test_beispielartikel_nicht_mehr_ausgeliefert(self):
        """Die sechs Beispielartikel stehen nicht mehr in den Stammdaten."""
        with file_open(SEED_DATEI, 'r') as datei:
            baum = ElementTree.fromstring(datei.read())
        ids = {rec.get('id') for rec in baum.iter('record')}
        for xmlid in BEISPIEL_XMLIDS:
            self.assertNotIn(xmlid, ids)
        self.assertIn('item_spielmobil', ids)

    def test_mitgliedstarif_standard_aus(self):
        """Neue Artikel haben keinen eigenen Mitgliedstarif; ein Vorgang eines
        Kontakts mit Mitgliedskennzeichen zahlt den Standardpreis."""
        item = self.items[0]
        self.assertFalse(item.has_member_price)
        member = self.env['res.partner'].create({'name': 'RF Mitglied', 'is_kjr_member': True})
        order = self.env['kjr.rental.order'].create({
            'partner_id': member.id, 'date_from': '2026-11-02', 'date_to': '2026-11-02',
            'line_ids': [(0, 0, {'item_id': item.id, 'quantity': 1})],
        })
        self.assertEqual(order.line_ids.price_per_day, item.price_per_day)

    def test_migration_schaltet_mitgliedstarif_ab(self):
        """Migration 19.0.5.8.0 schaltet has_member_price überall ab, auch archiviert."""
        aktiv = self.items[0]
        archiviert = self.items[1]
        (aktiv | archiviert).write({'has_member_price': True, 'price_member_per_day': 0.5})
        archiviert.active = False
        spec = importlib.util.spec_from_file_location(
            'kjr_rental_mig_19_0_5_8_0',
            file_path('kjr_rental/migrations/19.0.5.8.0/post-migration.py'))
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        migration._mitgliedstarif_abschalten(self.env)
        self.assertFalse(aktiv.has_member_price)
        self.assertFalse(archiviert.has_member_price)


@tagged('post_install', '-at_install')
class TestKjrRentalCatalogPage(HttpCase):

    def test_katalogseite(self):
        Category = self.env['kjr.rental.category']
        cat_late = Category.create({'name': 'RF Kategorie Spät', 'sequence': 900})
        cat_early = Category.create({'name': 'RF Kategorie Früh', 'sequence': -900})
        Item = self.env['kjr.rental.item']
        Item.create({'name': 'RF Spätartikel', 'category_id': cat_late.id,
                     'price_per_day': 2.0, 'website_published': True})
        Item.create({'name': 'RF Gaskocher', 'category_id': cat_early.id,
                     'price_per_day': 3.0, 'website_published': True,
                     'warning_note': 'RF Gasflasche nicht im Lieferumfang'})
        response = self.url_open('/service/verleih')
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn('RF Gasflasche nicht im Lieferumfang', html)
        self.assertLess(html.index('RF Kategorie Früh'), html.index('RF Kategorie Spät'))
        for wort in ('Mitgliedstarif', 'vergünstigte', 'Ihr Tarif', 'Mitglied:'):
            self.assertNotIn(wort, html)
        # Filterleiste steht oben, vor den Hinweisblöcken der Seite.
        self.assertLess(html.index('aria-label="Kategorien filtern"'),
                        html.index('Wer darf ausleihen?'))
        self.assertIn('Verbindlich ist die Rechnung der Geschäftsstelle', html)
        self.env['ir.config_parameter'].sudo().set_param(
            'kjr_rental.price_notice', 'RF eigener Preishinweis')
        html = self.url_open('/service/verleih').text
        self.assertIn('RF eigener Preishinweis', html)
        # Filterleiste: "Alle" plus beide Kategorien, Filter zeigt nur eine.
        self.assertIn('?kategorie=%d' % cat_early.id, html)
        self.assertIn('>Alle</a>', html)
        html = self.url_open('/service/verleih?kategorie=%d' % cat_early.id).text
        self.assertIn('RF Gaskocher', html)
        self.assertNotIn('RF Spätartikel', html)
        # Kategorie ohne veröffentlichte Artikel erscheint nicht in der Leiste.
        cat_empty = Category.create({'name': 'RF Leer', 'sequence': 1})
        html = self.url_open('/service/verleih?kategorie=%d' % cat_empty.id).text
        self.assertNotIn('RF Leer', html)
        self.assertIn('RF Spätartikel', html)
