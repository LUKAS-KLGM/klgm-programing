# -*- coding: utf-8 -*-
"""
Tests für die reinen (DB-unabhängigen) Berechnungsfunktionen von
executive.dashboard.kpi: Wertformatierung, Zeitraum-Auflösung und
Activity-Domain-Mapping.
"""
from datetime import date, timedelta
from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.tests import tagged


class _FixedDate(date):
    """date-Subklasse mit eingefrorenem today(), damit _get_date_range
    unabhängig von der echten Systemzeit testbar ist."""

    @classmethod
    def today(cls):
        return date(2026, 8, 20)


@tagged('post_install', '-at_install')
class TestKpiFormatValue(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Kpi = cls.env['executive.dashboard.kpi']

    def test_zero(self):
        self.assertEqual(self.Kpi._format_value(0), '0')

    def test_float_equal_to_int_below_1000(self):
        self.assertEqual(self.Kpi._format_value(42.0), '42')

    def test_negative_small_int(self):
        self.assertEqual(self.Kpi._format_value(-50), '-50')

    def test_fraction_below_1(self):
        self.assertEqual(self.Kpi._format_value(0.567), '0.57')

    def test_fraction_between_1_and_100(self):
        self.assertEqual(self.Kpi._format_value(45.678), '45.7')

    def test_between_100_and_1000(self):
        self.assertEqual(self.Kpi._format_value(250.4), '250')

    def test_int_below_1000_stays_plain(self):
        self.assertEqual(self.Kpi._format_value(999), '999')

    def test_int_at_1000_switches_to_k_suffix(self):
        # 1000 landet in der ">= 1_000"-Verzweigung noch vor der
        # Plain-Int-Verzweigung, daher "1.0k" statt "1000".
        self.assertEqual(self.Kpi._format_value(1000), '1.0k')

    def test_ten_thousand_boundary(self):
        self.assertEqual(self.Kpi._format_value(10000), '10k')

    def test_million_boundary(self):
        self.assertEqual(self.Kpi._format_value(1_500_000), '1.5M')

    def test_negative_large(self):
        self.assertEqual(self.Kpi._format_value(-25000), '-25k')


@tagged('post_install', '-at_install')
class TestKpiDateRange(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Kpi = cls.env['executive.dashboard.kpi']

    def setUp(self):
        super().setUp()
        patcher = patch(
            'odoo.addons.executive_dashboard.models.dashboard_kpi.date',
            _FixedDate,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_last_7_days(self):
        self.assertEqual(
            self.Kpi._get_date_range('last_7_days'),
            (date(2026, 8, 13), date(2026, 8, 20)),
        )

    def test_last_30_days(self):
        self.assertEqual(
            self.Kpi._get_date_range('last_30_days'),
            (date(2026, 7, 21), date(2026, 8, 20)),
        )

    def test_last_90_days(self):
        self.assertEqual(
            self.Kpi._get_date_range('last_90_days'),
            (date(2026, 8, 20) - timedelta(days=90), date(2026, 8, 20)),
        )

    def test_this_month(self):
        self.assertEqual(
            self.Kpi._get_date_range('this_month'),
            (date(2026, 8, 1), date(2026, 8, 20)),
        )

    def test_this_quarter_differs_from_this_month(self):
        # August liegt mitten in Q3, this_quarter muss daher im Juli
        # beginnen, nicht im August.
        self.assertEqual(
            self.Kpi._get_date_range('this_quarter'),
            (date(2026, 7, 1), date(2026, 8, 20)),
        )

    def test_this_year(self):
        self.assertEqual(
            self.Kpi._get_date_range('this_year'),
            (date(2026, 1, 1), date(2026, 8, 20)),
        )

    def test_last_year_full_calendar_year(self):
        self.assertEqual(
            self.Kpi._get_date_range('last_year'),
            (date(2025, 1, 1), date(2025, 12, 31)),
        )

    def test_custom_range(self):
        self.assertEqual(
            self.Kpi._get_date_range('custom:2026-02-01,2026-02-14'),
            (date(2026, 2, 1), date(2026, 2, 14)),
        )

    def test_custom_range_malformed_falls_back_to_default(self):
        self.assertEqual(
            self.Kpi._get_date_range('custom:not-a-date'),
            (date(2026, 7, 21), date(2026, 8, 20)),
        )

    def test_unknown_period_falls_back_to_default(self):
        self.assertEqual(
            self.Kpi._get_date_range('does_not_exist'),
            (date(2026, 7, 21), date(2026, 8, 20)),
        )

    def test_all_time_starts_at_oldest_company_creation(self):
        date_from, date_to = self.Kpi._get_date_range('all_time')
        oldest = self.env['res.company'].sudo().search(
            [], order='create_date asc', limit=1)
        self.assertEqual(date_from, oldest.create_date.date())
        self.assertEqual(date_to, date(2026, 8, 20))


@tagged('post_install', '-at_install')
class TestKpiPreviousRange(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Kpi = cls.env['executive.dashboard.kpi']

    def test_previous_period_is_equal_length_and_non_overlapping(self):
        # Ein 30-Tage-Fenster (Juni) muss von einem gleich langen Fenster
        # abgelöst werden, das am Vortag des Fensterstarts endet.
        result = self.Kpi._get_previous_range(date(2026, 7, 1), date(2026, 7, 31))
        self.assertEqual(result, (date(2026, 5, 31), date(2026, 6, 30)))

    def test_previous_single_day(self):
        result = self.Kpi._get_previous_range(date(2026, 7, 15), date(2026, 7, 15))
        self.assertEqual(result, (date(2026, 7, 14), date(2026, 7, 14)))

    def test_previous_year_range(self):
        result = self.Kpi._get_previous_year_range(date(2026, 3, 1), date(2026, 3, 31))
        self.assertEqual(result, (date(2025, 3, 1), date(2025, 3, 31)))

    def test_previous_year_range_crashes_on_leap_day(self):
        # Bekannte Lücke: replace(year=...) hat kein Clamping auf den
        # 28.02., daher crasht jeder Zeitraum, der den 29.02. berührt,
        # sobald das Vorjahr kein Schaltjahr ist (z.B. 2024 -> 2023).
        with self.assertRaises(ValueError):
            self.Kpi._get_previous_year_range(date(2024, 2, 29), date(2024, 3, 1))


@tagged('post_install', '-at_install')
class TestKpiMapActivityDomain(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Kpi = cls.env['executive.dashboard.kpi']

    def test_phonecall_category_maps_to_or_of_two_labels(self):
        mapped = self.Kpi._map_activity_domain(
            [('activity_type_id.category', '=', 'phonecall')])
        self.assertEqual(mapped, [
            '|', ('activity_type', 'ilike', 'Anruf'), ('activity_type', 'ilike', 'Call'),
        ])

    def test_meeting_category_maps_to_or_of_two_labels(self):
        mapped = self.Kpi._map_activity_domain(
            [('activity_type_id.category', '=', 'meeting')])
        self.assertEqual(mapped, [
            '|', ('activity_type', 'ilike', 'Meeting'), ('activity_type', 'ilike', 'Besprechung'),
        ])

    def test_other_category_maps_to_single_ilike(self):
        mapped = self.Kpi._map_activity_domain(
            [('activity_type_id.category', '=', 'other')])
        self.assertEqual(mapped, [('activity_type', 'ilike', 'other')])

    def test_activity_type_name_maps_directly(self):
        mapped = self.Kpi._map_activity_domain(
            [('activity_type_id.name', '=', 'Anruf')])
        self.assertEqual(mapped, [('activity_type', '=', 'Anruf')])

    def test_user_id_maps_to_user_name(self):
        mapped = self.Kpi._map_activity_domain([('user_id', '=', 5)])
        self.assertEqual(mapped, [('user_name', '=', 5)])

    def test_date_deadline_maps_to_activity_date(self):
        mapped = self.Kpi._map_activity_domain(
            [('date_deadline', '>=', '2026-01-01')])
        self.assertEqual(mapped, [('activity_date', '>=', '2026-01-01')])

    def test_unrecognized_field_passed_through_unchanged(self):
        mapped = self.Kpi._map_activity_domain([('state', '=', 'done')])
        self.assertEqual(mapped, [('state', '=', 'done')])

    def test_string_operators_passed_through(self):
        mapped = self.Kpi._map_activity_domain(
            ['|', ('user_id', '=', 1), ('user_id', '=', 2)])
        self.assertEqual(mapped, ['|', ('user_name', '=', 1), ('user_name', '=', 2)])
