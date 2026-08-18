# -*- coding: utf-8 -*-
"""Tests des quartalsweisen Auszahlungslaufs (``kjr.grant.payout.run``).

Der Massenlauf darf das Vier-Augen-Prinzip nicht aufweichen: Anträge, die die
auslösende Person selbst sachlich geprüft hat, werden übersprungen und im
Ergebnisbericht begründet — der Lauf bricht deswegen aber nicht ab. Ebenso darf
ein zweiter Lauf nichts doppelt anweisen: die Zahlungsanweisung ist ein
Bearbeitungsvermerk mit Rechtsfolge, kein wiederholbarer Vorgang.

Die Anträge werden hier bewusst direkt im Status "Bewilligt" angelegt (im Test
läuft die Umgebung mit erhöhten Rechten, siehe ``create()`` am Antrag). Geprüft
wird der Lauf, nicht der vorgelagerte Workflow — der ist in
``test_compliance.py`` abgedeckt.
"""
from odoo.tests.common import TransactionCase, new_test_user
from odoo.tests import tagged
from odoo.exceptions import AccessError, UserError


@tagged('post_install', '-at_install')
class TestKjrGrantPayoutRun(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Application = cls.env['kjr.grant.application']
        cls.Run = cls.env['kjr.grant.payout.run']
        cls.assoc = cls.env['res.partner'].create({
            'name': 'Auszahlungsverband e. V.',
            'is_company': True,
            'is_kjr_member': True,
            'kjr_vr_right': True,
        })
        # Zwei Sachbearbeitende: nur so lässt sich das Vier-Augen-Prinzip prüfen.
        cls.reviewer_a = new_test_user(
            cls.env, login='kjr_pruefer_a',
            groups='base.group_user,kjr_grant.group_kjr_reviewer',
            name='Prüferin A')
        cls.reviewer_b = new_test_user(
            cls.env, login='kjr_pruefer_b',
            groups='base.group_user,kjr_grant.group_kjr_reviewer',
            name='Prüfer B')
        cls.clerk = new_test_user(
            cls.env, login='kjr_ohne_recht', groups='base.group_user',
            name='Ohne Berechtigung')

        # Zwei Anträge von A geprüft, einer von B — Bewilligung im Haushaltsjahr 2026.
        cls.app_a1 = cls._app(cls.reviewer_a, 100.0)
        cls.app_a2 = cls._app(cls.reviewer_a, 250.0)
        cls.app_b1 = cls._app(cls.reviewer_b, 40.0)

    @classmethod
    def _app(cls, reviewer, amount, **kw):
        vals = {
            'partner_id': cls.assoc.id,
            'grant_type_id': cls.env.ref('kjr_grant.grant_type_4_1a').id,
            'measure_name': 'Testmaßnahme',
            'measure_start': '2026-07-01',
            'measure_end': '2026-07-01',
            'tn_count': 20,
            'cost_accommodation': 500.0,
            'state': 'approved',
            'sachlich_richtig': True,
            'reviewed_by': reviewer.id,
            'date_submitted': '2026-06-01',
            'date_approved': '2026-06-15',
            'grant_approved': amount,
        }
        vals.update(kw)
        return cls.Application.create(vals)

    def _run(self, user, **kw):
        vals = {
            'fiscal_year': 2026,
            'period_type': 'year',
            'period_basis': 'date_approved',
            'enforce_cutoff': False,
        }
        vals.update(kw)
        return self.Run.with_user(user).create(vals)

    # ── Abgrenzung des Zeitraums ─────────────────────────────────────────────

    def test_period_bounds_from_quarter(self):
        """Quartal + Haushaltsjahr ergeben die Zeitraumgrenzen."""
        run = self._run(self.reviewer_b, period_type='q3')
        self.assertEqual(str(run.date_from), '2026-07-01')
        self.assertEqual(str(run.date_to), '2026-09-30')

    def test_application_outside_period_is_not_listed(self):
        """Ein Antrag außerhalb des Zeitraums gehört in einen anderen Lauf."""
        run = self._run(self.reviewer_b, period_type='q1')  # 01.01.–31.03.2026
        self.assertNotIn(self.app_a1, run.application_ids)
        self.assertNotIn(self.app_a1, run.blocked_ids)

    # ── Vorschau ─────────────────────────────────────────────────────────────

    def test_preview_lists_approved_applications(self):
        """Bewilligte, noch nicht angewiesene Anträge des Zeitraums stehen im Lauf."""
        run = self._run(self.reviewer_b)
        self.assertIn(self.app_a1, run.application_ids)
        self.assertIn(self.app_a2, run.application_ids)
        self.assertEqual(run.application_count, 2)
        self.assertEqual(run.amount_total, 350.0)

    def test_preview_skips_own_reviewed_applications(self):
        """Vier-Augen-Prinzip: selbst geprüfte Anträge stehen NICHT im eigenen Lauf."""
        run = self._run(self.reviewer_b)
        self.assertNotIn(self.app_b1, run.application_ids)
        self.assertIn(self.app_b1, run.blocked_ids)
        self.assertIn('Vier-Augen-Prinzip', run.blocked_info)

    def test_preview_is_user_specific(self):
        """Derselbe Zeitraum ergibt für die andere Person die gespiegelte Auswahl."""
        run = self._run(self.reviewer_a)
        self.assertIn(self.app_b1, run.application_ids)
        self.assertNotIn(self.app_a1, run.application_ids)
        self.assertNotIn(self.app_a2, run.application_ids)

    def test_zero_amount_application_is_blocked(self):
        """Ohne bewilligten Betrag wird nichts angewiesen."""
        empty = self._app(self.reviewer_a, 0.0)
        run = self._run(self.reviewer_b)
        self.assertNotIn(empty, run.application_ids)
        self.assertIn(empty, run.blocked_ids)

    def test_missing_reference_date_is_reported(self):
        """Ein bewilligter Antrag ohne maßgebliches Datum fällt nicht still heraus."""
        undated = self._app(self.reviewer_a, 80.0, date_approved=False)
        run = self._run(self.reviewer_b)
        self.assertNotIn(undated, run.application_ids)
        self.assertIn(undated, run.blocked_ids)

    # ── Ausführung ───────────────────────────────────────────────────────────

    def test_run_orders_payment_for_selected_applications(self):
        """Der Lauf weist die einbezogenen Anträge zur Zahlung an."""
        run = self._run(self.reviewer_b)
        run.action_run()
        self.assertEqual(run.state, 'done')
        self.assertEqual(run.ordered_count, 2)
        self.assertEqual(run.ordered_amount, 350.0)
        self.assertTrue(self.app_a1.payment_ordered)
        self.assertTrue(self.app_a2.payment_ordered)
        self.assertEqual(self.app_a1.payment_ordered_by, self.reviewer_b)
        self.assertTrue(self.app_a1.payment_ordered_date)
        # Der selbst geprüfte Antrag bleibt unangetastet.
        self.assertFalse(self.app_b1.payment_ordered)

    def test_run_skips_own_reviewed_application_even_if_added_by_hand(self):
        """Die Vorschau ist eine Anzeige, keine Sicherung: jeder Antrag wird beim
        Lauf erneut geprüft. Ein von Hand hinzugefügter, selbst geprüfter Antrag
        wird übersprungen — der Lauf bricht deswegen NICHT ab."""
        run = self._run(self.reviewer_b)
        run.application_ids = [(4, self.app_b1.id)]
        run.action_run()
        self.assertEqual(run.ordered_count, 2)
        self.assertEqual(run.skipped_count, 1)
        self.assertIn(self.app_b1, run.skipped_ids)
        self.assertFalse(self.app_b1.payment_ordered)
        self.assertIn('Vier-Augen-Prinzip', run.result_text)

    def test_second_run_orders_nothing_twice(self):
        """Bereits angewiesene Anträge kommen in keinen weiteren Lauf."""
        first = self._run(self.reviewer_b)
        first.action_run()
        ordered_date = self.app_a1.payment_ordered_date

        second = self._run(self.reviewer_b)
        self.assertFalse(second.application_ids,
                         'Angewiesene Anträge dürfen nicht erneut aufgeführt werden.')
        with self.assertRaises(UserError):
            second.action_run()
        # Der Vermerk des ersten Laufs bleibt unverändert (keine Doppelanweisung).
        self.assertEqual(self.app_a1.payment_ordered_date, ordered_date)
        self.assertEqual(self.app_a1.payment_ordered_by, self.reviewer_b)

    def test_run_cannot_be_executed_twice(self):
        """Ein ausgeführter Lauf lässt sich nicht erneut starten."""
        run = self._run(self.reviewer_b)
        run.action_run()
        with self.assertRaises(UserError):
            run.action_run()
        with self.assertRaises(UserError):
            run.action_refresh()

    def test_run_requires_reviewer_group(self):
        """Ohne Sachbearbeiter-Berechtigung wird nichts angewiesen.

        Der Lauf wird von einer berechtigten Person vorbereitet und erst die
        Ausführung von der unberechtigten versucht — so prüft der Test die
        Berechtigungsabfrage in ``action_run()`` und nicht die (ohnehin
        vorhandene) Zugriffsregel auf dem Assistenten selbst.
        """
        run = self._run(self.reviewer_b)
        with self.assertRaises(AccessError):
            run.with_user(self.clerk).action_run()
        self.assertFalse(self.app_a1.payment_ordered)

    def test_report_lists_ordered_and_skipped(self):
        """Der Ergebnisbericht dokumentiert Anweisung und Übersprungenes."""
        run = self._run(self.reviewer_b)
        run.application_ids = [(4, self.app_b1.id)]
        run.action_run()
        self.assertIn(self.app_a1.name, run.result_text)
        self.assertIn(self.app_b1.name, run.result_text)
        self.assertIn(self.reviewer_b.name, run.result_text)

    # ── Stichtagsregel ───────────────────────────────────────────────────────

    def test_cutoff_rule_without_configured_cutoff_blocks_instead_of_guessing(self):
        """Ist die Stichtagsregel aktiv, aber kein Stichtag gepflegt, wird kein
        Datum unterstellt — die betroffenen Anträge werden gemeldet."""
        params = self.env['ir.config_parameter'].sudo()
        params.search([('key', 'in', ('kjr_grant.payout_cutoff_day',
                                      'kjr_grant.payout_cutoff_month'))]).unlink()
        self.assertIsNone(self.Run._payout_cutoff())
        run = self._run(self.reviewer_b, enforce_cutoff=True)
        self.assertFalse(run.application_ids)
        self.assertIn(self.app_a1, run.blocked_ids)
        self.assertIn('Stichtag', run.blocked_info)
