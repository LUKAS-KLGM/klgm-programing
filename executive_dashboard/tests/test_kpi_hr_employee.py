# -*- coding: utf-8 -*-
"""
Tests für den hr.employee-Sonderfall in _aggregate_model(): Headcount
während eines Zeitraums, basierend auf Einstellungs-/Austrittsdatum.

create_date lässt sich nicht über die ORM zurückdatieren (Odoo setzt es
selbst bei create()), daher wird es hier per Raw-SQL direkt in der
laufenden Testtransaktion überschrieben — Standardtechnik für Tests, die
ein historisches Erstelldatum brauchen; die Transaktion wird nach dem
Test ohnehin zurückgerollt.

Diese Odoo-19-Instanz hat kein hr_contract installiert, daher greift in
_aggregate_model() der create_date-Fallback (kein contract_date_start/
first_contract_date verfügbar).
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

    def _backdate_create_date(self, employee, create_date):
        self.env.cr.execute(
            "UPDATE hr_employee SET create_date = %s WHERE id = %s",
            (create_date, employee.id),
        )
        employee.invalidate_recordset(['create_date'])

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
        hired_after = self.Employee.create({'name': 'ED-HR-Test-HiredAfter'})
        self._backdate_create_date(hired_after, '2026-08-01 00:00:00')

        kpi = self._kpi()
        result = kpi._aggregate_model('custom:2026-06-01,2026-06-30')
        self.assertEqual(result['value'], 0)

    def test_includes_employee_hired_before_the_period(self):
        hired_before = self.Employee.create({'name': 'ED-HR-Test-HiredBefore'})
        self._backdate_create_date(hired_before, '2026-01-01 00:00:00')

        kpi = self._kpi()
        result = kpi._aggregate_model('custom:2026-06-01,2026-06-30')
        self.assertEqual(result['value'], 1)

    def test_excludes_employee_departed_before_the_period(self):
        departed = self.Employee.create({
            'name': 'ED-HR-Test-Departed',
            'departure_date': '2026-03-01',
        })
        self._backdate_create_date(departed, '2025-01-01 00:00:00')

        kpi = self._kpi()
        result = kpi._aggregate_model('custom:2026-06-01,2026-06-30')
        self.assertEqual(result['value'], 0)

    def test_includes_employee_departed_during_the_period(self):
        departed_mid_period = self.Employee.create({
            'name': 'ED-HR-Test-DepartedMidPeriod',
            'departure_date': '2026-06-15',
        })
        self._backdate_create_date(departed_mid_period, '2025-01-01 00:00:00')

        kpi = self._kpi()
        result = kpi._aggregate_model('custom:2026-06-01,2026-06-30')
        self.assertEqual(result['value'], 1)
