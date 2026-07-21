# -*- coding: utf-8 -*-
"""
Tests für executive.dashboard.kpi._compute_value(): Orchestrierung über
alle source_type-Zweige, change_pct-Berechnung/Cap und Target-Ampel.
"""
from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestKpiComputeValue(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dashboard = cls.env['executive.dashboard'].create({'name': 'ED ComputeValue Test Dashboard'})
        cls.Lead = cls.env['crm.lead']
        cls.Lead.create({
            'name': 'ED-CV-Test-current',
            'type': 'opportunity',
            'expected_revenue': 1000.0,
            'date_deadline': '2026-06-10',
        })

    def _kpi(self, **vals):
        vals.setdefault('dashboard_id', self.dashboard.id)
        vals.setdefault('name', 'CV KPI')
        return self.env['executive.dashboard.kpi'].create(vals)

    def _model_kpi(self, **overrides):
        vals = dict(
            source_type='model', model_name='crm.lead', measure_field='expected_revenue',
            date_field='date_deadline', domain="[('name', '=', 'ED-CV-Test-current')]",
            aggregate='sum', show_comparison=False,
        )
        vals.update(overrides)
        return self._kpi(**vals)

    def test_model_source_end_to_end(self):
        kpi = self._model_kpi()
        result = kpi._compute_value('custom:2026-06-01,2026-06-30')
        self.assertEqual(result['value'], 1000.0)
        self.assertEqual(result['display_value'], '1.0k')

    def test_sql_source_end_to_end(self):
        kpi = self._kpi(source_type='sql', sql_query='SELECT 555')
        result = kpi._compute_value('last_30_days')
        self.assertEqual(result['value'], 555)

    def test_bank_balance_source_dispatches_correctly(self):
        # Only verifies _compute_value() routes source_type='bank_balance' to
        # _compute_bank_balance() and uses its return value — the balance math
        # itself is covered by real posted moves in test_kpi_bank_balance.py.
        # Stubbed here because the real value depends on whatever bank
        # journals/moves exist in the database (e.g. the App Store demo data).
        kpi = self._kpi(source_type='bank_balance')
        with patch.object(type(kpi), '_compute_bank_balance', return_value=4321.0):
            result = kpi._compute_value('last_30_days')
        self.assertEqual(result['value'], 4321.0)

    def test_formula_source_with_kpi_cache(self):
        kpi = self._kpi(source_type='formula', formula="kpi('Revenue') * 2")
        result = kpi._compute_value('last_30_days', kpi_cache={'Revenue': 21})
        self.assertEqual(result['value'], 42)

    def test_formula_error_returns_zero(self):
        kpi = self._kpi(source_type='formula', formula="kpi('Revenue') / 0")
        result = kpi._compute_value('last_30_days', kpi_cache={'Revenue': 21})
        self.assertEqual(result['value'], 0)

    def test_display_name_translates_under_german_context(self):
        kpi = self._kpi(name='Revenue (net)')
        self.assertEqual(kpi.with_context(lang='de_DE')._display_name(), 'Umsatz (netto)')
        self.assertEqual(kpi._display_name(), 'Revenue (net)')

    def test_display_name_falls_back_for_unmapped_name(self):
        # Custom, user-authored KPIs have no German entry — must not error,
        # just show the name as typed.
        kpi = self._kpi(name='Some Custom KPI')
        self.assertEqual(kpi.with_context(lang='de_DE')._display_name(), 'Some Custom KPI')

    def test_dashboard_formula_lookup_survives_german_display_language(self):
        # Regression test: kpi_cache must stay keyed by the stored (English)
        # name, not _display_name(), or a formula KPI's kpi('Revenue (net)')
        # reference breaks for German-language viewers as soon as a sibling
        # KPI's *displayed* name diverges from its stored name.
        self._model_kpi(name='Revenue (net)')
        self._kpi(source_type='formula', name='AOV',
                   formula="kpi('Revenue (net)') / 2", show_comparison=False)
        data = self.dashboard.with_context(lang='de_DE')._get_dashboard_data(
            'custom:2026-06-01,2026-06-30')
        aov_result = next(k for k in data['kpis'] if k['name'] == 'AOV')
        self.assertEqual(aov_result['value'], 500.0)

    def test_change_pct_capped_at_positive_999(self):
        kpi = self._model_kpi(budget_value=0.01)
        result = kpi._compute_value('custom:2026-06-01,2026-06-30', comparison_mode='budget')
        self.assertEqual(result['change_pct'], 999)

    def test_change_pct_zero_previous_gives_zero_pct(self):
        kpi = self._model_kpi()
        result = kpi._compute_value('custom:2026-06-01,2026-06-30')
        self.assertEqual(result['change_pct'], 0)

    def test_target_status_green_when_value_meets_target(self):
        kpi = self._model_kpi(target_value=500.0)
        result = kpi._compute_value('custom:2026-06-01,2026-06-30')
        self.assertEqual(result['target_status'], 'green')

    def test_target_status_yellow_between_warning_and_target(self):
        kpi = self._model_kpi(target_value=2000.0, target_warning=800.0)
        result = kpi._compute_value('custom:2026-06-01,2026-06-30')
        self.assertEqual(result['target_status'], 'yellow')

    def test_target_status_red_below_critical(self):
        kpi = self._model_kpi(target_value=5000.0, target_warning=3000.0, target_critical=1500.0)
        result = kpi._compute_value('custom:2026-06-01,2026-06-30')
        self.assertEqual(result['target_status'], 'red')

    def test_no_target_value_gives_empty_status(self):
        kpi = self._model_kpi()
        result = kpi._compute_value('custom:2026-06-01,2026-06-30')
        self.assertEqual(result['target_status'], '')
