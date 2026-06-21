# -*- coding: utf-8 -*-
"""Tests des Materialverleihs: Mitgliedstarif, Verfügbarkeit, Abschreibung."""
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestKjrRental(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Entleiher Test'})
        cls.category = cls.env['kjr.rental.category'].create({'name': 'Technik'})
        cls.item = cls.env['kjr.rental.item'].create({
            'name': 'Beamer', 'category_id': cls.category.id,
            'quantity_total': 5, 'price_per_day': 10.0,
            'has_member_price': True, 'price_member_per_day': 5.0, 'deposit': 20.0,
        })

    def _order(self, qty=1, is_member=False, date_from='2026-09-01', date_to='2026-09-03'):
        return self.env['kjr.rental.order'].create({
            'partner_id': self.partner.id, 'is_member': is_member,
            'date_from': date_from, 'date_to': date_to,
            'line_ids': [(0, 0, {'item_id': self.item.id, 'quantity': qty})],
        })

    def test_member_vs_standard_price(self):
        """Mitglieder erhalten den Mitgliedstarif (5 €), Nicht-Mitglieder den Standard (10 €)."""
        self.assertEqual(self.item.price_for(True), 5.0)
        self.assertEqual(self.item.price_for(False), 10.0)
        member_order = self._order(is_member=True)
        self.assertEqual(member_order.line_ids.price_per_day, 5.0)

    def test_subtotal_days_quantity(self):
        """Zwischensumme = Tagespreis × Menge × Tage (10 × 2 × 3 = 60)."""
        order = self._order(qty=2, is_member=False,
                            date_from='2026-09-01', date_to='2026-09-03')
        self.assertEqual(order.rental_days, 3)
        self.assertEqual(order.line_ids.subtotal, 60.0)
        self.assertEqual(order.line_ids.deposit_subtotal, 40.0)

    def test_availability_blocks_overbooking(self):
        """Bestand 5: eine Reservierung über 5 Stück blockiert eine zweite
        überlappende Reservierung (0 verfügbar)."""
        first = self._order(qty=5, date_from='2026-09-01', date_to='2026-09-05')
        first.action_reserve()
        self.assertEqual(first.state, 'reserved')
        self.assertEqual(
            self.item.quantity_available('2026-09-02', '2026-09-04'), 0)
        second = self._order(qty=1, date_from='2026-09-02', date_to='2026-09-04')
        with self.assertRaises(UserError):
            second.action_reserve()

    def test_book_value_floor_at_salvage(self):
        """Lineare Eigenabschreibung: voll abgeschriebener Artikel fällt nie unter
        den Restwert."""
        item = self.env['kjr.rental.item'].create({
            'name': 'Altbus', 'category_id': self.category.id,
            'purchase_value': 1000.0, 'purchase_date': '2000-01-01',
            'useful_life_years': 5, 'salvage_value': 100.0,
        })
        self.assertEqual(item.book_value, 100.0)

    def test_book_value_without_depreciation_data(self):
        """Ohne Anschaffungsdatum/Nutzungsdauer bleibt der Buchwert = Anschaffungswert."""
        item = self.env['kjr.rental.item'].create({
            'name': 'Neu', 'category_id': self.category.id, 'purchase_value': 500.0,
        })
        self.assertEqual(item.book_value, 500.0)
