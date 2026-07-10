# -*- coding: utf-8 -*-
"""
Tests für executive.dashboard.kpi._compute_bank_balance() gegen einen
echten, geposteten account.move auf einem Bankjournal. Nutzt Odoos
offizielles AccountTestInvoicingCommon-Mixin für ein Mindest-Chart-of-
Accounts (Journal, Konten), statt das manuell nachzubauen.

AccountTestInvoicingCommon.setUpClass() operiert auf cls.env.company —
wenn diese Company (wie hier, mit den Demo-Daten für Screenshots)
bereits einen Kontenplan hat, wird der VORHANDENE Bankjournal
wiederverwendet statt ein isolierter neuer angelegt. Die Fallback-Suche
in _compute_bank_balance() ("irgendein Bankjournal") würde dann
versehentlich die echten Demo-Buchungen mitsummieren. Deshalb explizit
eine unabhängige Test-Company erzwingen.
"""
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestKpiBankBalance(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # setup_independent_company() creates a company hardcoded to the name
        # 'company_1_data'. Chart-of-accounts loading commits internally, so
        # on a persistent (non-throwaway) test database a company from a
        # prior test run can survive even though the rest of that run rolled
        # back. collect_company_accounting_data() always creates fresh
        # journals and isn't safe to call twice on the same company, so
        # remove any stale leftover first rather than trying to reuse it.
        stale = cls.env['res.company'].sudo().search([('name', '=', 'company_1_data')])
        stale.unlink()
        company = cls.setup_independent_company()
        cls.company_data = cls.collect_company_accounting_data(company)
        cls.dashboard = cls.env['executive.dashboard'].create({'name': 'ED Bank Test Dashboard'})
        cls.bank_journal = cls.company_data['default_journal_bank']

    def _kpi(self, **vals):
        vals.setdefault('dashboard_id', self.dashboard.id)
        vals.setdefault('name', 'Bank KPI')
        vals.setdefault('source_type', 'bank_balance')
        return self.env['executive.dashboard.kpi'].create(vals)

    def _archive_other_bank_journals(self):
        """_compute_bank_balance()'s fallback chain searches for ANY bank
        journal system-wide, unscoped by company. Archive every bank
        journal except this test's own (across all companies, including
        the real demo data seeded for App Store screenshots) so that
        fallback search is unambiguous."""
        all_companies = self.env['res.company'].sudo().search([])
        Journal = self.env['account.journal'].sudo().with_context(allowed_company_ids=all_companies.ids)
        others = Journal.search([('type', '=', 'bank'), ('id', '!=', self.bank_journal.id)])
        others.write({'active': False})

    def _post_move(self, journal, bank_account, amount, revenue_side=True):
        """Post a simple two-line move on `journal`: `amount` moves through
        `bank_account`, the contra line hits revenue (money in) or expense
        (money out)."""
        contra_account = (self.company_data['default_account_revenue'] if revenue_side
                           else self.company_data['default_account_expense'])
        move = self.env['account.move'].create({
            'journal_id': journal.id,
            'line_ids': [
                (0, 0, {
                    'account_id': bank_account.id,
                    'debit': amount if revenue_side else 0.0,
                    'credit': 0.0 if revenue_side else amount,
                    'name': 'bank line',
                }),
                (0, 0, {
                    'account_id': contra_account.id,
                    'debit': 0.0 if revenue_side else amount,
                    'credit': amount if revenue_side else 0.0,
                    'name': 'contra line',
                }),
            ],
        })
        move.action_post()
        return move

    def test_balance_reflects_net_posted_activity(self):
        # 1000 in, then 300 out -> running balance should be 700.
        self._post_move(self.bank_journal, self.bank_journal.default_account_id, 1000.0, revenue_side=True)
        self._post_move(self.bank_journal, self.bank_journal.default_account_id, 300.0, revenue_side=False)
        kpi = self._kpi(journal_id=self.bank_journal.id)
        self.assertEqual(kpi._compute_bank_balance(), 700.0)

    def test_kpi_level_journal_id_takes_priority(self):
        self._post_move(self.bank_journal, self.bank_journal.default_account_id, 250.0, revenue_side=True)
        kpi = self._kpi(journal_id=self.bank_journal.id)
        self.assertEqual(kpi._compute_bank_balance(), 250.0)

    def test_falls_back_to_global_config_parameter(self):
        self._post_move(self.bank_journal, self.bank_journal.default_account_id, 500.0, revenue_side=True)
        self.env['ir.config_parameter'].sudo().set_param(
            'executive_dashboard.bank_journal_id', str(self.bank_journal.id))
        kpi = self._kpi()  # no kpi-level journal_id
        self.assertEqual(kpi._compute_bank_balance(), 500.0)

    def test_falls_back_to_first_bank_journal_when_nothing_configured(self):
        self._archive_other_bank_journals()
        self._post_move(self.bank_journal, self.bank_journal.default_account_id, 125.0, revenue_side=True)
        self.env['ir.config_parameter'].sudo().set_param('executive_dashboard.bank_journal_id', '0')
        kpi = self._kpi()
        self.assertEqual(kpi._compute_bank_balance(), 125.0)

    def test_draft_moves_are_not_counted(self):
        contra = self.company_data['default_account_revenue']
        self.env['account.move'].create({
            'journal_id': self.bank_journal.id,
            'line_ids': [
                (0, 0, {'account_id': self.bank_journal.default_account_id.id,
                        'debit': 9999.0, 'credit': 0.0, 'name': 'draft bank line'}),
                (0, 0, {'account_id': contra.id,
                        'debit': 0.0, 'credit': 9999.0, 'name': 'draft contra'}),
            ],
        })  # never posted
        kpi = self._kpi(journal_id=self.bank_journal.id)
        self.assertEqual(kpi._compute_bank_balance(), 0)

    def test_no_bank_journal_anywhere_returns_zero(self):
        all_companies = self.env['res.company'].sudo().search([])
        Journal = self.env['account.journal'].sudo().with_context(allowed_company_ids=all_companies.ids)
        Journal.search([('type', '=', 'bank')]).write({'type': 'cash'})
        kpi = self._kpi()
        self.assertEqual(kpi._compute_bank_balance(), 0)
