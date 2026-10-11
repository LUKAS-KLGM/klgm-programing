# -*- coding: utf-8 -*-
"""Zusicherungen an die ausgelieferten Stammdaten des Materialverleihs.

Geprüft wird in BEIDEN Tests die AUSGELIEFERTE Datei, nicht der Zustand der
Instanz. Begründung: die Seed-Sätze stehen unter <data noupdate="1"> und sind
ausdrücklich zur freien Pflege freigegeben (siehe Kommentare in
data/kjr_rental_data.xml und migrations/19.0.5.5.0/post-migration.py, das
gepflegte Werte bewusst stehen lässt). Ein Test gegen env.ref würde eine
erlaubte Kundeneinstellung, etwa ein geleertes Icon-Feld, zum roten Test und
damit zum fehlgeschlagenen Upgrade machen, obwohl weder Modul noch Daten
defekt sind. `icon` ist ein optionales fields.Char ohne required.
"""
import xml.etree.ElementTree as ElementTree

from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.tools import file_open

SEED_DATEI = 'kjr_rental/data/kjr_rental_data.xml'

# Die sieben Kategorien aus data/kjr_rental_data.xml.
SEED_KATEGORIEN = [
    'cat_vehicle', 'cat_tent', 'cat_tech', 'cat_sport',
    'cat_kitchen', 'cat_games', 'cat_other',
]

# Kundennamen und Ortsbezüge, die in einem weiß gelabelten Modul nicht
# vorkommen dürfen. Geprüft wird die AUSGELIEFERTE Datei, nicht die Instanz:
# wie ein Betreiber seine Lagerorte benennt, ist seine Sache.
VERBOTENE_BEZEICHNER = [
    'Oberallgäu', 'Sonthofen', 'Immenstadt', 'Oberstdorf', 'Kreisjugendring',
]

# Die XML-IDs tragen aus Kompatibilitätsgründen noch Ortsnamen (ein Umbenennen
# erzeugte auf Bestandsinstanzen Dubletten) und werden deshalb ausgeblendet.
BESTANDS_XMLIDS = ('loc_sonthofen', 'loc_immenstadt', 'loc_oberstdorf')


@tagged('post_install', '-at_install')
class TestKjrRentalSeedData(TransactionCase):

    def _seed_inhalt(self):
        """Rohtext der ausgelieferten Stammdatendatei."""
        with file_open(SEED_DATEI, 'r') as datei:
            return datei.read()

    def test_seed_kategorien_haben_icon(self):
        """Jede Kategorie in der ausgelieferten Datei trägt ein FontAwesome-4-Icon."""
        baum = ElementTree.fromstring(self._seed_inhalt())
        gefunden = {}
        for record in baum.iter('record'):
            if record.get('model') != 'kjr.rental.category':
                continue
            icon = record.find("field[@name='icon']")
            gefunden[record.get('id')] = None if icon is None else (icon.text or '')
        self.assertEqual(
            sorted(gefunden), sorted(SEED_KATEGORIEN),
            'Die ausgelieferten Kategorien weichen von der erwarteten Liste ab. '
            'Wird eine Kategorie ergänzt oder entfernt, SEED_KATEGORIEN mitpflegen.')
        for xmlid, icon in sorted(gefunden.items()):
            self.assertIsNotNone(
                icon, 'Kategorie "%s" hat in %s kein Feld "icon".' % (xmlid, SEED_DATEI))
            # Odoo 19 liefert FontAwesome 4.7.0 aus, die Klasse muss daher mit
            # "fa-" beginnen; der Kanban und die Katalogüberschrift setzen das
            # "fa" selbst davor. Siehe Kommentar über den Sätzen in der Datei.
            self.assertTrue(
                icon.startswith('fa-'),
                'Kategorie "%s" hat kein FontAwesome-Icon (Wert: %r).' % (xmlid, icon))

    def test_seed_datei_ohne_kundennamen(self):
        """Die ausgelieferten Stammdaten nennen keinen Kunden und keinen Ort."""
        inhalt = self._seed_inhalt()
        for xmlid in BESTANDS_XMLIDS:
            inhalt = inhalt.replace(xmlid, '')
        for wort in VERBOTENE_BEZEICHNER:
            self.assertNotIn(
                wort, inhalt,
                'Kundenbezug "%s" in den Seed-Daten gefunden.' % wort)
