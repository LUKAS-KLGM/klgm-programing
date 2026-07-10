# -*- coding: utf-8 -*-
"""
Integrationstests für executive.dashboard.kpi._aggregate_model gegen
echte crm.lead-Datensätze. Alle Zeiträume nutzen 'custom:YYYY-MM-DD,YYYY-MM-DD',
damit die Tests unabhängig vom echten Systemdatum sind — für die
Vorperioden-Fenster wurden die Testdaten anhand von _get_previous_range /
_get_previous_year_range aus dem custom-Fenster 2026-06-01..2026-06-30
zurückgerechnet (Vorperiode: 2026-05-02..2026-05-31, Vorjahr: 2025-06).
"""
from datetime import date

from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestKpiAggregateModel(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dashboard = cls.env['executive.dashboard'].create({'name': 'ED Test Dashboard'})
        cls.Lead = cls.env['crm.lead']

        def make_lead(name, day, revenue):
            return cls.Lead.create({
                'name': name,
                'type': 'opportunity',
                'expected_revenue': revenue,
                'date_deadline': day,
            })

        # Aktueller Zeitraum: Juni 2026.
        make_lead('ED-Test-current-1', date(2026, 6, 10), 1000.0)
        make_lead('ED-Test-current-2', date(2026, 6, 20), 500.0)
        # Liegt im previous_period-Fenster von Juni (2026-05-02..2026-05-31).
        make_lead('ED-Test-previous-period', date(2026, 5, 15), 9999.0)
        # Liegt im previous_year-Fenster (2025-06-01..2025-06-30).
        make_lead('ED-Test-previous-year', date(2025, 6, 15), 777.0)
        # Weit außerhalb aller obigen Fenster — darf nie mitgezählt werden.
        make_lead('ED-Test-out-of-range', date(2026, 1, 1), 123456.0)

    def _kpi(self, **vals):
        vals.setdefault('dashboard_id', self.dashboard.id)
        vals.setdefault('name', 'Test KPI')
        vals.setdefault('source_type', 'model')
        vals.setdefault('model_name', 'crm.lead')
        vals.setdefault('measure_field', 'expected_revenue')
        vals.setdefault('date_field', 'date_deadline')
        vals.setdefault('domain', "[('name', 'like', 'ED-Test-%')]")
        return self.env['executive.dashboard.kpi'].create(vals)

    def test_sum_with_previous_period(self):
        kpi = self._kpi(aggregate='sum')
        result = kpi._aggregate_model('custom:2026-06-01,2026-06-30')
        self.assertEqual(result['value'], 1500.0)
        self.assertEqual(result['previous'], 9999.0)

    def test_count(self):
        kpi = self._kpi(aggregate='count')
        result = kpi._aggregate_model('custom:2026-06-01,2026-06-30')
        self.assertEqual(result['value'], 2)
        self.assertEqual(result['previous'], 1)

    def test_avg(self):
        kpi = self._kpi(aggregate='avg')
        result = kpi._aggregate_model('custom:2026-06-01,2026-06-30')
        self.assertEqual(result['value'], 750.0)
        self.assertEqual(result['previous'], 9999.0)

    def test_previous_year_comparison_mode(self):
        kpi = self._kpi(aggregate='sum')
        result = kpi._aggregate_model(
            'custom:2026-06-01,2026-06-30', comparison_mode='previous_year')
        self.assertEqual(result['value'], 1500.0)
        self.assertEqual(result['previous'], 777.0)

    def test_budget_comparison_mode_ignores_dates(self):
        kpi = self._kpi(aggregate='sum', budget_value=2000.0)
        result = kpi._aggregate_model(
            'custom:2026-06-01,2026-06-30', comparison_mode='budget')
        self.assertEqual(result['value'], 1500.0)
        self.assertEqual(result['previous'], 2000.0)

    def test_show_comparison_off_skips_previous(self):
        kpi = self._kpi(aggregate='sum', show_comparison=False)
        result = kpi._aggregate_model('custom:2026-06-01,2026-06-30')
        self.assertEqual(result['value'], 1500.0)
        self.assertEqual(result['previous'], 0)

    def test_all_time_never_computes_a_previous_value(self):
        # all_time schließt Vergleichswerte explizit aus (period != 'all_time'
        # in der Gating-Bedingung) — unabhängig von show_comparison.
        today = date.today()
        self.Lead.create({
            'name': 'ED-Test-all-time',
            'type': 'opportunity',
            'expected_revenue': 42.0,
            'date_deadline': today,
        })
        kpi = self._kpi(aggregate='sum', domain="[('name', '=', 'ED-Test-all-time')]")
        result = kpi._aggregate_model('all_time')
        self.assertEqual(result['value'], 42.0)
        self.assertEqual(result['previous'], 0)

    def test_missing_model_or_measure_field_returns_zeroed_result(self):
        kpi = self._kpi(model_name=False)
        result = kpi._aggregate_model('custom:2026-06-01,2026-06-30')
        self.assertEqual(
            result, {'value': 0, 'previous': 0, 'chart_data': [], 'sparkline': []})

    def test_unknown_model_name_returns_zeroed_result(self):
        kpi = self._kpi(model_name='not.a.real.model')
        result = kpi._aggregate_model('custom:2026-06-01,2026-06-30')
        self.assertEqual(
            result, {'value': 0, 'previous': 0, 'chart_data': [], 'sparkline': []})
