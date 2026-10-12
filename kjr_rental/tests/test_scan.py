# -*- coding: utf-8 -*-
"""B51/B52: QR-Etikett, Scannen per Kamera/Handscanner, Rückgabe per Scan und
Lagerorte für das Zurückräumen."""
import importlib.util

from odoo.exceptions import ValidationError
from odoo.tests import HttpCase, new_test_user, tagged
from odoo.tests.common import TransactionCase
from odoo.tools import file_path

MIGRATION_19_0_5_7_0 = 'kjr_rental/migrations/19.0.5.7.0/post-migration.py'


def _lade_migration():
    """post-migration.py als Modul laden (Ordnername enthält Punkte)."""
    spec = importlib.util.spec_from_file_location(
        'kjr_rental_post_migration_19_0_5_7_0', file_path(MIGRATION_19_0_5_7_0))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class KjrRentalScanCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Entleiher Scan'})
        cls.category = cls.env['kjr.rental.category'].create({'name': 'Fahrzeuge Test'})
        cls.location = cls.env['kjr.rental.location'].create({
            'name': 'Spielewagen Test', 'color': '#1F77B4',
            'note': 'Garage, linke Seite'})
        cls.item = cls.env['kjr.rental.item'].create({
            'name': 'Bobbycar', 'category_id': cls.category.id,
            'code': 'BC-01', 'barcode': 'KJR-BC-01', 'quantity_total': 3,
            'location_id': cls.location.id, 'storage_bin': 'Regal 3',
            'price_per_day': 1.0,
        })
        cls.other_item = cls.env['kjr.rental.item'].create({
            'name': 'Rollbrett', 'category_id': cls.category.id,
            'code': 'RB_1', 'quantity_total': 2,
        })

    def _order(self, qty=2, item=None, state='issued',
               date_from='2026-09-01', date_to='2026-09-03'):
        order = self.env['kjr.rental.order'].create({
            'partner_id': self.partner.id,
            'date_from': date_from, 'date_to': date_to,
            'line_ids': [(0, 0, {'item_id': (item or self.item).id, 'quantity': qty})],
        })
        if state in ('reserved', 'issued'):
            order.action_reserve()
        if state == 'issued':
            order.action_issue()
        return order


@tagged('post_install', '-at_install')
class TestKjrRentalScan(KjrRentalScanCommon):

    # --- B51: QR-Code auf dem Etikett -------------------------------------
    def test_qr_wert_und_bildadresse(self):
        item = self.item
        self.assertTrue(item.label_qr_value.endswith('/kjr_rental/scan/KJR-BC-01'))
        self.assertTrue(item.label_qr_src.startswith('/report/barcode/?'))
        self.assertIn('barcode_type=QR', item.label_qr_src)
        self.assertFalse(self.other_item.label_qr_value)
        self.assertFalse(self.other_item.label_qr_src)

    def test_qr_kern_route_erzeugt_png(self):
        """Die Kern-Route /report/barcode (ir.actions.report.barcode) kann QR."""
        png = self.env['ir.actions.report'].barcode(
            'QR', self.item.label_qr_value, width=300, height=300, barLevel='M')
        self.assertTrue(png.startswith(b'\x89PNG'))

    def test_etikett_enthaelt_qr_code128_und_lagerort(self):
        html = self.env['ir.actions.report']._render_qweb_html(
            'kjr_rental.report_rental_label', self.item.ids)[0].decode()
        self.assertIn('barcode_type=QR', html)
        self.assertIn('/report/barcode/Code128/KJR-BC-01', html)
        self.assertIn('Spielewagen Test · Regal 3', html)
        self.assertIn('#1f77b4', html)

    # --- B51: Code finden ----------------------------------------------------
    def test_find_by_scan(self):
        Item = self.env['kjr.rental.item']
        self.assertEqual(Item._find_by_scan('KJR-BC-01'), self.item)
        self.assertEqual(Item._find_by_scan('  kjr-bc-01 '), self.item)
        self.assertEqual(Item._find_by_scan('BC-01'), self.item)
        self.assertEqual(Item._find_by_scan(self.item.label_qr_value), self.item)
        self.assertEqual(
            Item._find_by_scan('https://example.org/kjr_rental/scan/KJR-BC-01?x=1'), self.item)
        self.assertEqual(Item._find_by_scan('rb_1'), self.other_item)
        self.assertFalse(Item._find_by_scan('UNBEKANNT'))
        self.assertFalse(Item._find_by_scan(''))
        # Platzhalter dürfen nicht als Joker wirken.
        self.assertFalse(Item._find_by_scan('KJR-BC-%'))
        self.assertFalse(Item._find_by_scan('RB%'))

    def test_lookup_liefert_artikel_und_lagerort(self):
        order = self._order(qty=2)
        result = self.env['kjr.rental.item'].kjr_scan_lookup(raw='KJR-BC-01')
        self.assertTrue(result['found'])
        self.assertEqual(result['item']['id'], self.item.id)
        self.assertEqual(result['item']['return_location_label'], 'Spielewagen Test · Regal 3')
        self.assertEqual(result['item']['location_color'], '#1f77b4')
        self.assertEqual(result['item']['location_note'], 'Garage, linke Seite')
        self.assertEqual([o['id'] for o in result['orders']], [order.id])
        self.assertTrue(result['orders'][0]['can_return'])
        missing = self.env['kjr.rental.item'].kjr_scan_lookup(raw='NIX')
        self.assertFalse(missing['found'])
        self.assertIn('NIX', missing['message'])
        by_id = self.env['kjr.rental.item'].kjr_scan_lookup(item_id=self.item.id)
        self.assertEqual(by_id['item']['name'], 'Bobbycar')

    # --- B51: Rückgabe per Scan ------------------------------------------------
    def test_rueckgabe_scan_zaehlt_bis_vollstaendig(self):
        order = self._order(qty=2)
        first = order.kjr_scan_register_return(self.item.id)
        self.assertTrue(first['ok'])
        self.assertIn('Spielewagen Test · Regal 3', first['message'])
        self.assertEqual(order.line_ids.return_scanned_qty, 1)
        self.assertFalse(order.return_scan_complete)
        second = order.kjr_scan_register_return(self.item.id)
        self.assertTrue(second['ok'])
        self.assertTrue(second['order_complete'])
        self.assertTrue(order.return_scan_complete)
        self.assertEqual(order.return_scan_summary, '2 von 2 Stück gescannt')
        third = order.kjr_scan_register_return(self.item.id)
        self.assertFalse(third['ok'])
        self.assertEqual(order.line_ids.return_scanned_qty, 2)

    def test_rueckgabe_scan_nur_ausgegeben_und_passender_artikel(self):
        reserved = self._order(qty=1, state='reserved')
        self.assertFalse(reserved.kjr_scan_register_return(self.item.id)['ok'])
        issued = self._order(qty=1, date_from='2026-10-01', date_to='2026-10-02')
        self.assertFalse(issued.kjr_scan_register_return(self.other_item.id)['ok'])
        self.assertEqual(issued.line_ids.return_scanned_qty, 0)

    def test_ruecknahme_dokumentiert_scanstand(self):
        order = self._order(qty=2)
        order.kjr_scan_register_return(self.item.id)
        order.write({'return_checked_complete': False, 'return_checked_clean': True,
                     'return_note': 'Ein Bobbycar fehlt.'})
        order.action_return()
        self.assertEqual(order.state, 'returned')
        bodies = ' '.join(order.message_ids.mapped('body'))
        self.assertIn('Per Scan erfasst: 1 von 2 Stück gescannt', bodies)
        self.assertIn('Bobbycar (1)', bodies)

    def test_ruecknahme_ohne_scan_unveraendert(self):
        order = self._order(qty=1)
        order.write({'return_checked_complete': True, 'return_checked_clean': True})
        order.action_return()
        bodies = ' '.join(order.message_ids.mapped('body'))
        self.assertNotIn('Per Scan erfasst', bodies)

    def test_ausgabe_setzt_scanstand_zurueck(self):
        order = self._order(qty=2)
        order.kjr_scan_register_return(self.item.id)
        order.action_reset_draft()
        order.action_reserve()
        order.action_issue()
        self.assertEqual(order.line_ids.return_scanned_qty, 0)

    def test_scanstand_nicht_ueber_menge(self):
        order = self._order(qty=1)
        with self.assertRaises(ValidationError):
            order.line_ids.return_scanned_qty = 2

    def test_aktionen_oeffnen_scanansicht(self):
        order = self._order(qty=1)
        action = order.action_open_return_scan()
        self.assertEqual(action['tag'], 'kjr_rental_scan')
        self.assertEqual(action['context']['kjr_scan_order_id'], order.id)
        item_action = self.item.action_open_scan()
        self.assertEqual(item_action['context']['kjr_scan_item_id'], self.item.id)
        self.assertEqual(self.item.open_order_count, 1)
        self.assertEqual(self.item.issued_order_count, 1)
        self.assertEqual(
            self.env.ref('kjr_rental.action_kjr_rental_scan').tag, 'kjr_rental_scan')

    def test_rueckgabe_button_nur_bei_ausgegebener_ausleihe(self):
        """'Rückgabe zuordnen' am Artikel hängt an issued_order_count: eine nur
        reservierte Ausleihe zählt als offen, aber nicht als ausgegeben."""
        self._order(qty=1, state='reserved')
        self.item.invalidate_recordset(['open_order_count', 'issued_order_count'])
        self.assertEqual(self.item.open_order_count, 1)
        self.assertEqual(self.item.issued_order_count, 0)
        self._order(qty=1, date_from='2026-09-10', date_to='2026-09-12')
        self.item.invalidate_recordset(['open_order_count', 'issued_order_count'])
        self.assertEqual(self.item.open_order_count, 2)
        self.assertEqual(self.item.issued_order_count, 1)

    # --- B52: Lagerort, Farbe, Lagerplatz ---------------------------------------
    def test_lagerort_anzeige(self):
        self.assertEqual(self.item.return_location_label, 'Spielewagen Test · Regal 3')
        self.assertEqual(self.other_item.return_location_label, 'Kein Lagerort hinterlegt')
        line_order = self._order(qty=1)
        self.assertEqual(line_order.line_ids.return_location_label, 'Spielewagen Test · Regal 3')
        self.assertEqual(line_order.line_ids.item_location_id, self.location)

    def test_lagerort_farbe_wird_geprueft(self):
        self.assertEqual(self.location.color, '#1f77b4')
        with self.assertRaises(ValidationError):
            self.env['kjr.rental.location'].create({'name': 'Kaputt', 'color': 'red;x'})
        leer = self.env['kjr.rental.location'].create({'name': 'Ohne Farbe', 'color': '  '})
        self.assertFalse(leer.color)

    def test_lagerorte_nur_ohne_gleichnamigen_anlegen(self):
        """_ensure_named: gleichnamig (Schreibweise egal, auch archiviert) wird
        nicht erneut angelegt, Dubletten bleiben unangetastet."""
        Location = self.env['kjr.rental.location'].with_context(active_test=False)
        Location.create({'name': ' testort  alpha '})
        Location.create({'name': 'Testort Gamma', 'active': False})
        Location.create({'name': 'Testort Doppelt'})
        Location.create({'name': 'Testort Doppelt'})
        before = Location.search_count([])
        entries = [(40, 'Testort Alpha'), (50, 'Testort Beta'),
                   (60, 'Testort Gamma'), (70, 'Testort Doppelt')]

        created = Location._ensure_named(entries)

        self.assertEqual(created.mapped('name'), ['Testort Beta'])
        self.assertEqual(created.sequence, 50)
        self.assertEqual(Location.search_count([]), before + 1)
        self.assertEqual(Location.search_count([('name', '=', 'Testort Doppelt')]), 2)
        self.assertFalse(Location.search([('name', '=', 'Testort Gamma')]).active)
        self.assertFalse(Location._ensure_named(entries))
        self.assertEqual(Location.search_count([]), before + 1)

    def test_migration_legt_lagerorte_an(self):
        """19.0.5.7.0: Spielewagen, Normaler Verleih, Reserveverleih existieren
        danach je mindestens einmal; ein vorhandener gleichnamiger Satz wird
        nicht verdoppelt, ein zweiter Lauf legt nichts an."""
        Location = self.env['kjr.rental.location'].with_context(active_test=False)
        if not Location.search_count([('name', '=ilike', 'spielewagen')]):
            Location.create({'name': 'SPIELEWAGEN'})
        spielewagen_before = Location.search_count([('name', '=ilike', 'spielewagen')])
        migration = _lade_migration()
        migration.migrate(self.env.cr, '19.0.5.6.0')
        self.env.invalidate_all()
        counts = {
            name: Location.search_count([('name', '=ilike', name)])
            for _seq, name in migration.LAGERORTE
        }
        self.assertEqual(counts['Spielewagen'], spielewagen_before)
        for name, count in counts.items():
            self.assertGreaterEqual(count, 1, name)
        total = Location.search_count([])
        migration.migrate(self.env.cr, '19.0.5.6.0')
        self.env.invalidate_all()
        self.assertEqual(Location.search_count([]), total)

    def test_lagerorte_neuinstallation_unberuehrt(self):
        before = self.env['kjr.rental.location'].with_context(active_test=False).search_count([])
        _lade_migration().migrate(self.env.cr, None)
        self.assertEqual(
            self.env['kjr.rental.location'].with_context(active_test=False).search_count([]),
            before)


@tagged('post_install', '-at_install')
class TestKjrRentalScanRoute(HttpCase):
    """QR-Ziel /kjr_rental/scan/<code>: führt angemeldetes Verleih-Personal zum
    Artikel und lässt andere nicht in den Artikelstamm."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        category = cls.env['kjr.rental.category'].create({'name': 'Route Test'})
        cls.item = cls.env['kjr.rental.item'].create({
            'name': 'Kettcar', 'category_id': category.id, 'barcode': 'KJR-KC-01'})
        new_test_user(cls.env, login='verleih_scan', password='verleih_scan_pw1',
                      groups='base.group_user,kjr_rental.group_kjr_rental_user')
        new_test_user(cls.env, login='portal_scan', password='portal_scan_pw1',
                      groups='base.group_portal')
        new_test_user(cls.env, login='intern_scan', password='intern_scan_pw1',
                      groups='base.group_user')

    def test_route_leitet_auf_artikel(self):
        self.authenticate('verleih_scan', 'verleih_scan_pw1')
        response = self.url_open('/kjr_rental/scan/KJR-KC-01', allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.assertTrue(response.headers['Location'].endswith(
            '/odoo/action-kjr_rental.action_kjr_rental_item/%d' % self.item.id))

    def test_route_unbekannt_oeffnet_scanansicht(self):
        self.authenticate('verleih_scan', 'verleih_scan_pw1')
        response = self.url_open('/kjr_rental/scan/GIBTESNICHT', allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.assertTrue(response.headers['Location'].endswith(
            '/odoo/action-kjr_rental.action_kjr_rental_scan'))

    def test_route_portal_gesperrt(self):
        self.authenticate('portal_scan', 'portal_scan_pw1')
        response = self.url_open('/kjr_rental/scan/KJR-KC-01', allow_redirects=False)
        self.assertEqual(response.status_code, 404)

    def test_route_intern_ohne_gruppe_hinweis(self):
        """Interne Benutzer ohne "Sachbearbeiter Verleih" bekommen einen klaren
        Hinweis (403) statt "Seite nicht gefunden"."""
        self.authenticate('intern_scan', 'intern_scan_pw1')
        response = self.url_open('/kjr_rental/scan/KJR-KC-01', allow_redirects=False)
        self.assertEqual(response.status_code, 403)
        self.assertIn('Sachbearbeiter Verleih', response.text)

    def test_route_ohne_anmeldung_zur_anmeldung(self):
        response = self.url_open('/kjr_rental/scan/KJR-KC-01', allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.assertIn('/web/login', response.headers['Location'])
