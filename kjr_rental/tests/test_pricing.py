# -*- coding: utf-8 -*-
"""R4 – Preismodelle des Materialverleihs.

Fünf Modelle, je ein durchgerechnetes Beispiel:

===============  ==========================================================
Pro Tag          Grundpreis × Menge × angefangene Tage (bisheriges Verhalten)
Pro Nacht        Grundpreis × Menge × Nächte (Tage − 1)
Pro Stück        Grundpreis × Menge, ohne Zeitbezug
Kilometer        Grundgebühr (Zeitbezug am Artikel) + Kilometersatz × gefahrene km
Mengenstaffel    ab der Staffelmenge ersetzt der Staffelpreis den Grundpreis
===============  ==========================================================

Dazu die beiden Regressionsfälle, die bei der Einführung der Preismodelle
schiefgehen konnten:

* Ein Artikel OHNE gesetztes Preismodell (Bestandsdaten, die den Feld-Default
  beim Upgrade nicht abbekommen haben) muss exakt wie vorher rechnen.
* Preise bereits fakturierter bzw. ausgegebener Positionen dürfen sich nicht
  mehr ändern — sonst laufen Rechnung und Ausleihvorgang auseinander.
"""
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestKjrRentalPricing(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Item = cls.env['kjr.rental.item']
        cls.Order = cls.env['kjr.rental.order']
        cls.partner = cls.env['res.partner'].create({'name': 'Entleiher Preismodelle'})
        cls.category = cls.env['kjr.rental.category'].create({'name': 'Preismodelle'})

    def _item(self, **kw):
        vals = {'name': 'Testartikel', 'category_id': self.category.id,
                'quantity_total': 100, 'has_member_price': False}
        vals.update(kw)
        return self.Item.create(vals)

    def _order(self, item, quantity=1, date_from='2026-09-01', date_to='2026-09-03',
               is_member=False, **line_vals):
        line = {'item_id': item.id, 'quantity': quantity}
        line.update(line_vals)
        return self.Order.create({
            'partner_id': self.partner.id,
            'is_member': is_member,
            'date_from': date_from,
            'date_to': date_to,
            'line_ids': [(0, 0, line)],
        })

    # ══ Die fünf Preismodelle ════════════════════════════════════════════════

    def test_per_day(self):
        """Pro Tag: 10 € × 2 Stück × 3 Tage = 60 €."""
        item = self._item(name='Beamer', pricing_model='per_day', price_per_day=10.0)
        order = self._order(item, quantity=2)
        self.assertEqual(order.rental_days, 3)
        self.assertEqual(order.line_ids.billable_units, 3)
        self.assertEqual(order.line_ids.subtotal, 60.0)
        self.assertEqual(item.price_unit_label, 'pro Tag')

    def test_per_night(self):
        """Pro Nacht: 3 Kalendertage sind 2 Nächte → 10 € × 2 Stück × 2 = 40 €."""
        item = self._item(name='Zelt', pricing_model='per_night', price_per_day=10.0)
        order = self._order(item, quantity=2)
        self.assertEqual(order.rental_days, 3)
        self.assertEqual(order.line_ids.billable_units, 2)
        self.assertEqual(order.line_ids.subtotal, 40.0)
        self.assertEqual(item.price_unit_label, 'pro Nacht')

    def test_per_night_single_day_has_no_night(self):
        """Eine Ausleihe ohne Übernachtung ergibt 0 Nächte — und damit 0 €."""
        item = self._item(name='Zelt kurz', pricing_model='per_night', price_per_day=10.0)
        order = self._order(item, date_from='2026-09-01', date_to='2026-09-01')
        self.assertEqual(order.rental_days, 1)
        self.assertEqual(order.line_ids.subtotal, 0.0)

    def test_per_night_with_minimum_billable_units(self):
        """Mit gepflegter Mindestberechnung wird die Untergrenze angewandt."""
        item = self._item(name='Zelt mit Mindestsatz', pricing_model='per_night',
                          price_per_day=10.0, min_billable_units=1)
        order = self._order(item, date_from='2026-09-01', date_to='2026-09-01')
        self.assertEqual(order.line_ids.billable_units, 1)
        self.assertEqual(order.line_ids.subtotal, 10.0)

    def test_per_unit(self):
        """Pro Stück / Pauschale: 10 € × 4 Stück, ohne Zeitbezug = 40 € (auch bei 3 Tagen)."""
        item = self._item(name='Kiste Geschirr', pricing_model='per_unit',
                          price_per_day=10.0, unit_label='Kiste')
        order = self._order(item, quantity=4)
        self.assertEqual(order.rental_days, 3)
        self.assertEqual(order.line_ids.billable_units, 1)
        self.assertEqual(order.line_ids.subtotal, 40.0)
        self.assertIn('Kiste', item.price_unit_label)

    def test_per_km(self):
        """Grundgebühr + Kilometerpreis: 25 € pauschal + 0,30 €/km × 120 km = 61 €."""
        item = self._item(name='Bulli', pricing_model='per_km', price_time_basis='flat',
                          price_per_day=25.0, price_per_km=0.30)
        order = self._order(item, quantity=1, distance_km=120.0)
        line = order.line_ids
        self.assertEqual(line.price_per_km, 0.30,
                         'Der Kilometersatz wird beim Kilometermodell übernommen.')
        self.assertEqual(line.billable_units, 1)
        self.assertAlmostEqual(line.subtotal, 61.0, places=2)

    def test_per_km_base_fee_can_be_per_day(self):
        """Mit Zeitbezug "je Tag" fällt die Grundgebühr je Tag an: 25 × 3 + 36 = 111 €."""
        item = self._item(name='Bulli je Tag', pricing_model='per_km',
                          price_time_basis='day', price_per_day=25.0, price_per_km=0.30)
        order = self._order(item, quantity=1, distance_km=120.0)
        self.assertEqual(order.line_ids.billable_units, 3)
        self.assertAlmostEqual(order.line_ids.subtotal, 111.0, places=2)

    def test_km_amount_only_counts_once_per_line(self):
        """Der Kilometeranteil hängt an der Position, nicht an der Stückzahl:
        die gefahrenen Kilometer werden NICHT mit der Menge multipliziert."""
        item = self._item(name='Bulli Menge', pricing_model='per_km',
                          price_time_basis='flat', price_per_day=0.0, price_per_km=0.50)
        order = self._order(item, quantity=3, distance_km=100.0)
        self.assertAlmostEqual(order.line_ids.subtotal, 50.0, places=2)

    def test_tiered(self):
        """Mengenstaffel: ab 20 Stück gilt 2 € für ALLE Stück → 25 × 2 € = 50 €."""
        item = self._item(name='Bierzeltgarnitur', pricing_model='tiered',
                          price_time_basis='flat', price_per_day=4.0)
        self.env['kjr.rental.price.tier'].create([
            {'item_id': item.id, 'min_quantity': 10, 'price': 3.0},
            {'item_id': item.id, 'min_quantity': 20, 'price': 2.0},
        ])
        order = self._order(item, quantity=25)
        line = order.line_ids
        self.assertEqual(line.price_per_day, 4.0, 'Der Grundpreis bleibt dokumentiert.')
        self.assertEqual(line.price_unit_effective, 2.0)
        self.assertEqual(line.subtotal, 50.0)

    def test_tiered_below_first_step_keeps_base_price(self):
        """Unterhalb der ersten Stufe gilt weiterhin der Grundpreis: 5 × 4 € = 20 €."""
        item = self._item(name='Garnitur klein', pricing_model='tiered',
                          price_time_basis='flat', price_per_day=4.0)
        self.env['kjr.rental.price.tier'].create(
            {'item_id': item.id, 'min_quantity': 10, 'price': 3.0})
        order = self._order(item, quantity=5)
        self.assertEqual(order.line_ids.price_unit_effective, 4.0)
        self.assertEqual(order.line_ids.subtotal, 20.0)

    def test_tiered_with_daily_basis(self):
        """Mit Zeitbezug "je Tag" wird der Staffelpreis mit den Tagen multipliziert:
        2 € × 25 Stück × 3 Tage = 150 €."""
        item = self._item(name='Garnitur je Tag', pricing_model='tiered',
                          price_time_basis='day', price_per_day=4.0)
        self.env['kjr.rental.price.tier'].create(
            {'item_id': item.id, 'min_quantity': 20, 'price': 2.0})
        order = self._order(item, quantity=25)
        self.assertEqual(order.line_ids.billable_units, 3)
        self.assertEqual(order.line_ids.subtotal, 150.0)

    def test_tiered_member_price(self):
        """Der Mitgliedstarif gilt auch innerhalb der Staffel."""
        item = self._item(name='Garnitur Mitglied', pricing_model='tiered',
                          price_time_basis='flat', price_per_day=4.0,
                          has_member_price=True, price_member_per_day=2.0)
        self.env['kjr.rental.price.tier'].create(
            {'item_id': item.id, 'min_quantity': 20, 'price': 2.0, 'price_member': 1.0})
        order = self._order(item, quantity=25, is_member=True)
        self.assertEqual(order.line_ids.price_unit_effective, 1.0)
        self.assertEqual(order.line_ids.subtotal, 25.0)

    def test_manual_line_price_beats_the_tier(self):
        """Ein von Hand gesetzter Zeilenpreis hat Vorrang vor der Staffel."""
        item = self._item(name='Garnitur Sonderpreis', pricing_model='tiered',
                          price_time_basis='flat', price_per_day=4.0)
        self.env['kjr.rental.price.tier'].create(
            {'item_id': item.id, 'min_quantity': 20, 'price': 2.0})
        order = self._order(item, quantity=25)
        order.line_ids.price_per_day = 1.5
        self.assertEqual(order.line_ids.price_unit_effective, 1.5)
        self.assertEqual(order.line_ids.subtotal, 37.5)

    # ══ Regression 1: Artikel ohne gesetztes Preismodell ═════════════════════

    def test_default_pricing_model_is_per_day(self):
        """Ein neu angelegter Artikel bekommt das Bestandsverhalten als Vorgabe."""
        item = self._item(name='Ohne Angabe', price_per_day=10.0)
        self.assertEqual(item.pricing_model, 'per_day')

    def test_empty_pricing_model_behaves_exactly_like_before(self):
        """Bestandsartikel ohne gesetzten Wert rechnen unverändert Grundpreis ×
        Menge × Tage.

        Das Feld ist Pflichtfeld (NOT NULL), ein leerer Wert lässt sich also nicht
        speichern — geprüft wird deshalb der Rückfall in ``_pricing_model()``
        anhand eines nicht gespeicherten Datensatzes, genau dem Upgrade-Fall, für
        den der Rückfall gebaut wurde.
        """
        legacy = self.Item.new({'name': 'Altbestand', 'pricing_model': False,
                                'price_per_day': 10.0})
        self.assertFalse(legacy.pricing_model)
        self.assertEqual(legacy._pricing_model(), 'per_day')
        self.assertEqual(legacy.billable_units(3), 3)
        self.assertEqual(legacy.price_for(False), 10.0)
        self.assertEqual(legacy.unit_price_for(25, False), 10.0,
                         'Ohne Preismodell greift auch keine Mengenstaffel.')

    def test_existing_day_price_calculation_is_unchanged(self):
        """Regressionsrechnung wie vor der Einführung der Preismodelle:
        10 € × 2 Stück × 3 Tage = 60 €, Kaution 2 × 20 € = 40 €."""
        item = self._item(name='Bestandsartikel', price_per_day=10.0, deposit=20.0)
        order = self._order(item, quantity=2)
        self.assertEqual(order.line_ids.subtotal, 60.0)
        self.assertEqual(order.line_ids.deposit_subtotal, 40.0)
        self.assertEqual(order.amount_total, 60.0)
        self.assertEqual(order.deposit_total, 40.0)

    def test_km_price_is_not_applied_outside_the_km_model(self):
        """Ein am Artikel gepflegter Kilometersatz darf ohne aktiviertes
        Kilometermodell keine zusätzliche Gebühr erzeugen."""
        item = self._item(name='Bus als Tagesartikel', pricing_model='per_day',
                          price_per_day=10.0, price_per_km=0.30)
        order = self._order(item, quantity=1, distance_km=500.0)
        self.assertEqual(order.line_ids.price_per_km, 0.0)
        self.assertEqual(order.line_ids.subtotal, 30.0)

    # ══ Regression 2: Preise fakturierter Positionen sind eingefroren ═══════

    def test_prices_frozen_flag(self):
        """Die Einfrier-Regel: Rechnung ODER ausgegeben/zurückgegeben/storniert."""
        item = self._item(name='Einfrieren', price_per_day=10.0)
        order = self._order(item)
        line = order.line_ids
        self.assertFalse(line._prices_frozen())
        for state in ('issued', 'returned', 'cancelled'):
            order.state = state
            self.assertTrue(line._prices_frozen(), state)
        order.state = 'draft'
        self.assertFalse(line._prices_frozen())

    def test_issued_order_keeps_its_prices(self):
        """Ab Ausgabe wird der abgerechnete Preis nicht mehr nachgezogen —
        auch nicht bei einem Tarifwechsel, der die Neuberechnung anstoßen würde."""
        item = self._item(name='Ausgegeben', price_per_day=10.0, deposit=20.0,
                          has_member_price=True, price_member_per_day=5.0)
        order = self._order(item, quantity=2)
        self.assertEqual(order.line_ids.price_per_day, 10.0)
        order.state = 'issued'
        # Tarifwechsel: 'order_id.is_member' steht in den depends von
        # _compute_price, die Neuberechnung läuft also wirklich an.
        order.is_member = True
        item.write({'price_per_day': 99.0, 'price_member_per_day': 88.0, 'deposit': 99.0})
        order.line_ids.invalidate_recordset(
            ['price_per_day', 'deposit_unit', 'price_unit_effective', 'subtotal'])
        self.assertEqual(order.line_ids.price_per_day, 10.0)
        self.assertEqual(order.line_ids.deposit_unit, 20.0)
        self.assertEqual(order.line_ids.subtotal, 60.0)

    def test_invoiced_order_keeps_its_prices(self):
        """Sobald eine Rechnung existiert, ändern sich die Zeilenpreise nicht mehr —
        auch nicht bei einem Wechsel des Tarifs (Mitglied/Nicht-Mitglied)."""
        journal = self.env['account.journal'].search([
            ('type', '=', 'sale'), ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not journal:
            self.skipTest('Kein Verkaufsjournal im Test-Mandanten '
                          '(kein Kontenplan installiert) – Rechnungsfall nicht prüfbar.')
        item = self._item(name='Fakturiert', price_per_day=10.0,
                          has_member_price=True, price_member_per_day=5.0)
        order = self._order(item, quantity=2)
        self.assertEqual(order.line_ids.price_per_day, 10.0)

        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'journal_id': journal.id,
        })
        order.invoice_id = move.id
        # Tarifwechsel und Artikelpreisänderung nach der Fakturierung.
        order.is_member = True
        item.write({'price_per_day': 99.0, 'price_member_per_day': 88.0})
        order.line_ids.invalidate_recordset(
            ['price_per_day', 'price_unit_effective', 'subtotal'])
        self.assertEqual(order.line_ids.price_per_day, 10.0,
                         'Fakturierte Positionen dürfen sich nicht mehr verändern.')
        self.assertEqual(order.line_ids.subtotal, 60.0)

    def test_new_line_on_a_frozen_order_still_gets_a_price(self):
        """Eine im Formular NEU hinzugefügte Position eines ausgegebenen Vorgangs
        bekommt den aktuellen Artikelpreis — sonst stünde sie mit 0,00 € in
        Vertrag und Rechnung.

        Nachgestellt wird der Formularfall (noch nicht gespeicherte Zeile ohne
        ``_origin``); genau darauf stützt sich die Ausnahme in ``_compute_price``.
        """
        item = self._item(name='Nachtrag', price_per_day=10.0, deposit=20.0)
        order = self._order(item)
        order.state = 'issued'
        self.assertTrue(order.line_ids._prices_frozen())
        extra = self.env['kjr.rental.order.line'].new({
            'order_id': order.id, 'item_id': item.id, 'quantity': 1,
        })
        self.assertEqual(extra.price_per_day, 10.0)
        self.assertEqual(extra.deposit_unit, 20.0)
