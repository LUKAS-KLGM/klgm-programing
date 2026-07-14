# -*- coding: utf-8 -*-
"""
Tests für den hr.employee-Sonderfall in _aggregate_model(): Headcount
während eines Zeitraums, basierend auf Einstellungs-/Austrittsdatum.

Diese Odoo-19-Instanz hat `contract_date_start` direkt auf hr.employee
(über hr.version/_inherits, kein separates hr_contract-Modul nötig),
daher nutzt _aggregate_model() dieses Feld als emp_start — NICHT
create_date. `contract_date_start` ist normal beschreibbar, ein
Backdating-Workaround ist also nicht nötig.
"""
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestKpiAggregateHrEmployee(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dashboard = cls.env['executive.dashboard'].create({'name': 'ED HR Test Dashboard'})
        cls.Employee = cls.env['hr.employee']
        assert 'contract_date_start' in cls.Employee._fields, (
            "This test assumes contract_date_start exists on hr.employee "
            "in this Odoo version; _aggregate_model()'s emp_start fallback "
            "chain picks it over create_date when present.")

    def _kpi(self, **vals):
        vals.setdefault('dashboard_id', self.dashboard.id)
        vals.setdefault('name', 'HR Headcount KPI')
        vals.setdefault('source_type', 'model')
        vals.setdefault('model_name', 'hr.employee')
        vals.setdefault('measure_field', 'id')
        vals.setdefault('aggregate', 'count')
        vals.setdefault('apply_date_filter', False)
        vals.setdefault('domain', "[('name', 'like', 'ED-HR-Test-%')]")
        return self.env['executive.dashboard.kpi'].create(vals)

    def test_excludes_employee_hired_after_the_period(self):
        self.Employee.create({
            'name': 'ED-HR-Test-HiredAfter',
            'contract_date_start': '2026-08-01',
        })
        kpi = self._kpi()
        result = kpi._aggregate_model('custom:2026-06-01,2026-06-30')
        self.assertEqual(result['value'], 0)

    def test_includes_employee_hired_before_the_period(self):
        self.Employee.create({
            'name': 'ED-HR-Test-HiredBefore',
            'contract_date_start': '2026-01-01',
        })
        kpi = self._kpi()
        result = kpi._aggregate_model('custom:2026-06-01,2026-06-30')
        self.assertEqual(result['value'], 1)

    def test_excludes_employee_departed_before_the_period(self):
        self.Employee.create({
            'name': 'ED-HR-Test-Departed',
            'contract_date_start': '2025-01-01',
            'departure_date': '2026-03-01',
        })
        kpi = self._kpi()
        result = kpi._aggregate_model('custom:2026-06-01,2026-06-30')
        self.assertEqual(result['value'], 0)

    def test_includes_employee_departed_during_the_period(self):
        self.Employee.create({
            'name': 'ED-HR-Test-DepartedMidPeriod',
            'contract_date_start': '2025-01-01',
            'departure_date': '2026-06-15',
        })
        kpi = self._kpi()
        result = kpi._aggregate_model('custom:2026-06-01,2026-06-30')
        self.assertEqual(result['value'], 1)

    def test_includes_employee_with_no_contract_start_recorded(self):
        # emp_start missing (False) counts as "always employed" per the
        # domain's '|' (field, '=', False) branch.
        self.Employee.create({'name': 'ED-HR-Test-NoStartDate'})
        kpi = self._kpi()
        result = kpi._aggregate_model('custom:2026-06-01,2026-06-30')
        self.assertEqual(result['value'], 1)
