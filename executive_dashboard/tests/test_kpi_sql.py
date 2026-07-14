# -*- coding: utf-8 -*-
"""
Tests für executive.dashboard.kpi._execute_sql (source_type='sql').
"""
from datetime import date

from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestKpiExecuteSql(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dashboard = cls.env['executive.dashboard'].create({'name': 'ED SQL Test Dashboard'})

    def _kpi(self, **vals):
        vals.setdefault('dashboard_id', self.dashboard.id)
        vals.setdefault('name', 'SQL KPI')
        vals.setdefault('source_type', 'sql')
        return self.env['executive.dashboard.kpi'].create(vals)

    def test_simple_query_returns_scalar(self):
        kpi = self._kpi(sql_query="SELECT 42")
        self.assertEqual(kpi._execute_sql('last_30_days'), 42)

    def test_date_placeholders_are_substituted(self):
        kpi = self._kpi(sql_query="SELECT '{date_from}'::date")
        result = kpi._execute_sql('custom:2026-02-01,2026-02-14')
        self.assertEqual(result, date(2026, 2, 1))

    def test_no_query_returns_zero(self):
        kpi = self._kpi(sql_query=False)
        self.assertEqual(kpi._execute_sql('last_30_days'), 0)

    def test_null_result_returns_zero(self):
        kpi = self._kpi(sql_query="SELECT NULL")
        self.assertEqual(kpi._execute_sql('last_30_days'), 0)

    def test_broken_sql_is_caught_and_returns_zero(self):
        kpi = self._kpi(sql_query="SELECT * FROM this_table_does_not_exist")
        self.assertEqual(kpi._execute_sql('last_30_days'), 0)

    def test_broken_sql_does_not_poison_the_transaction(self):
        # A failed statement leaves the Postgres transaction in an aborted
        # state; the except-block must roll back to a savepoint, otherwise
        # every subsequent query in the same request fails with
        # "current transaction is aborted, commands ignored until end of
        # transaction block" — including the dashboard's OTHER, healthy KPIs.
        kpi = self._kpi(sql_query="SELECT * FROM this_table_does_not_exist")
        kpi._execute_sql('last_30_days')
        self.assertTrue(self.dashboard.exists())
