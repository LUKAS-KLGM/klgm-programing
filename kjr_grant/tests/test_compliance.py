# -*- coding: utf-8 -*-
"""
Richtlinien-Compliance-Tests für die KJR-Zuschussverwaltung.

Jeder Test schreibt eine konkrete Regel der KJR-OA-Zuschussrichtlinie
(Fassung ab 01.12.2022) bzw. der BJR-Standards als ausführbare Assertion fest –
geprüft gegen die ausgelieferten Förderart-Stammdaten (data/kjr_grant_type_data.xml)
und Systemparameter (data/ir_config_parameter_data.xml).

So kann das Kunden-Staging die fachliche Korrektheit per
`odoo-bin -i kjr_grant --test-enable` automatisch verifizieren, statt jede Zahl
manuell nachzurechnen. Erwartungswerte sind in den Docstrings hergeleitet.
"""
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestKjrGrantCompliance(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Application = cls.env['kjr.grant.application']
        cls.Settlement = cls.env['kjr.grant.settlement']
        # Antragsberechtigter Mitgliedsverband (§ 3.1: Vertretungsrecht in der VV).
        cls.assoc = cls.env['res.partner'].create({
            'name': 'Testverband e. V.',
            'is_company': True,
            'is_kjr_member': True,
            'kjr_vr_right': True,
        })
        # Natürliche Person (Juleica-Inhaberin).
        cls.person = cls.env['res.partner'].create({
            'name': 'Maxi Musterleiter',
            'is_company': False,
        })

    # ── Hilfsmethode ─────────────────────────────────────────────────────────
    def _app(self, type_xmlid, **kw):
        vals = {
            'partner_id': self.assoc.id,
            'grant_type_id': self.env.ref(type_xmlid).id,
            'measure_name': 'Testmaßnahme',
            'measure_start': '2026-07-01',
            'measure_end': '2026-07-01',
        }
        vals.update(kw)
        return self.Application.create(vals)

    # ══ § 4.1a Freizeitmaßnahme eintägig (5 €/TN, max 250 €) ═════════════════
    def test_4_1a_single_rate(self):
        """20 TN × 5 € = 100 € (unter Höchstbetrag, Fehlbetrag/Quote nicht bindend)."""
        app = self._app('kjr_grant.grant_type_4_1a', tn_count=20, cost_accommodation=500.0)
        self.assertEqual(app.grant_calculated, 100.0)

    def test_4_1a_max_amount_cap(self):
        """60 TN × 5 € = 300 €, gedeckelt auf Höchstbetrag 250 €."""
        app = self._app('kjr_grant.grant_type_4_1a', tn_count=60, cost_accommodation=2000.0)
        self.assertEqual(app.grant_calculated, 250.0)

    def test_4_1a_deficit_cap(self):
        """Kosten 120 €, Einnahmen 80 € → Fehlbetrag 40 €. Zuschuss nie über
        Fehlbetrag, auch wenn rechnerisch 100 € (20×5) möglich wären."""
        app = self._app('kjr_grant.grant_type_4_1a', tn_count=20,
                        cost_accommodation=120.0, income_tn_fees=80.0)
        self.assertEqual(app.grant_calculated, 40.0)

    # ══ § 4.1b mehrtägig (8 €/TN/Tag, max 600 €) + Juleica-Zuschlag +50 % ════
    def test_4_1b_juleica_uplift(self):
        """2 Tage, 10 TN, 2 Jugendleiter mit Juleica.
        10×2×8 = 160 (TN) + 2 Leiter × 2 Tage × (8 × 1,5) = 48 → 208 €.
        (Ohne Juleica-Zuschlag wären es 192 € → der +50 %-Zuschlag ist wirksam.)"""
        app = self._app('kjr_grant.grant_type_4_1b',
                        measure_start='2026-07-01', measure_end='2026-07-02',
                        tn_count=10, tn_leader_count=2, tn_leader_juleica=2,
                        cost_accommodation=1000.0)
        self.assertEqual(app.measure_days, 2)
        self.assertEqual(app.grant_calculated, 208.0)

    def test_4_1b_leader_ratio_cap(self):
        """Max. 1 anerkannter Jugendleiter je 5 TN (KJR-OA). Bei 10 TN und 5
        angegebenen Leitern werden nur 2 gefördert:
        10×1×8 = 80 + 2 Leiter × 1 × 8 = 16 → 96 € (statt 120 € bei 5 Leitern)."""
        app = self._app('kjr_grant.grant_type_4_1b',
                        measure_start='2026-07-01', measure_end='2026-07-01',
                        tn_count=10, tn_leader_count=5, tn_leader_juleica=0,
                        cost_accommodation=1000.0)
        self.assertEqual(app.grant_calculated, 96.0)

    # ══ § 4.7 Gruppenstarthilfe (Pauschale 150 €, deckelfrei) ════════════════
    def test_4_7_pauschale_exempt_from_deficit(self):
        """Pauschale 150 € wird auch ohne Fehlbetrag (keine Kosten/Einnahmen)
        voll gewährt – § 4.7 ist von der Fehlbetrags-/Quotendeckelung ausgenommen."""
        app = self._app('kjr_grant.grant_type_4_7', tn_count=5)
        self.assertEqual(app.grant_calculated, 150.0)

    def test_4_7_pauschale_even_with_surplus(self):
        """Auch bei Überschuss (Einnahmen > Kosten, Fehlbetrag 0) bleibt es 150 €."""
        app = self._app('kjr_grant.grant_type_4_7', tn_count=5,
                        cost_accommodation=50.0, income_tn_fees=300.0)
        self.assertEqual(app.grant_calculated, 150.0)

    # ══ § 4.9 Delegiertenförderung (Fahrtkosten n. BayRKG) ═══════════════════
    def test_4_9_bayrkg_car_roundtrip(self):
        """PKW, 100 km einfache Strecke → Hin+Rück 200 km × 0,35 €/km = 70 €."""
        app = self._app('kjr_grant.grant_type_4_9',
                        delegate_transport_mode='car', delegate_km_one_way=100.0)
        self.assertEqual(app.grant_calculated, 70.0)

    def test_4_9_bayrkg_passenger_allowance(self):
        """Mit 2 Mitfahrer/innen: 200 km × (0,35 + 2×0,03) = 200 × 0,41 = 82 €."""
        app = self._app('kjr_grant.grant_type_4_9',
                        delegate_transport_mode='car', delegate_km_one_way=100.0,
                        delegate_passenger_count=2)
        self.assertEqual(app.grant_calculated, 82.0)

    # ══ Maßnahmentage: An-/Abreise-Regel (10-Uhr-/17-Uhr-Zählung) ════════════
    def test_measure_days_arrival_departure_rule(self):
        """3 Kalendertage, aber Anreise ab 10:00 und Abreise bis 17:00 →
        An- und Abreisetag zählen als EIN Tag → 2 förderfähige Tage."""
        app = self._app('kjr_grant.grant_type_4_1b',
                        measure_start='2026-07-01', measure_end='2026-07-03',
                        measure_start_time=10.0, measure_end_time=17.0, tn_count=5)
        self.assertEqual(app.measure_days, 2)

    def test_measure_days_full_count_without_times(self):
        """Ohne erfasste Uhrzeiten gilt die volle Kalendertageszählung (3 Tage)."""
        app = self._app('kjr_grant.grant_type_4_1b',
                        measure_start='2026-07-01', measure_end='2026-07-03', tn_count=5)
        self.assertEqual(app.measure_days, 3)

    # ══ Auszahlungs-Stichtag 15.11. (knüpft an Antragseingang) ═══════════════
    def test_payout_cutoff_same_year(self):
        """Eingang bis 15.11. → Auszahlung im selben Haushaltsjahr."""
        app = self._app('kjr_grant.grant_type_4_1a', tn_count=10, cost_accommodation=200.0)
        app.date_submitted = '2026-11-10'
        app.invalidate_recordset(['payout_year'])
        self.assertEqual(app.payout_year, 2026)

    def test_payout_cutoff_next_year(self):
        """Eingang nach dem 15.11. → Auszahlung erst im Folgejahr."""
        app = self._app('kjr_grant.grant_type_4_1a', tn_count=10, cost_accommodation=200.0)
        app.date_submitted = '2026-11-20'
        app.invalidate_recordset(['payout_year'])
        self.assertEqual(app.payout_year, 2027)

    # ══ Rückforderungszins: Basiszins + 3 PP (bayerisch) ═════════════════════
    def test_interest_rate_is_base_plus_three(self):
        """Default-Zinssatz = Basiszins (0,0) + 3 PP = 3,0 % p. a.
        (ANBest-P Nr. 8.4 i. V. m. Art. 49a Abs. 3 BayVwVfG – NICHT +5 PP)."""
        self.assertEqual(self.Settlement._default_interest_rate(), 3.0)

    def test_repayment_interest_calculation(self):
        """Rückforderung 100 €, 3 % p. a., exakt 365 Tage Verzug → 3,00 € Zinsen,
        Gesamtforderung 103,00 €."""
        app = self._app('kjr_grant.grant_type_4_1a', tn_count=20,
                        cost_accommodation=500.0, grant_approved=100.0)
        # Abrechnung ohne Ist-Teilnehmer/-Kosten → Neuberechnung 0 € → volle Rückforderung.
        settlement = self.Settlement.create({
            'application_id': app.id,
            'actual_tn_count': 0,
            'repayment_due_date': '2025-01-01',
            'interest_reference_date': '2026-01-01',
        })
        self.assertEqual(settlement.interest_rate, 3.0)
        self.assertEqual(settlement.repayment_amount, 100.0)
        self.assertEqual(settlement.interest_days, 365)
        self.assertEqual(settlement.interest_amount, 3.0)
        self.assertEqual(settlement.total_reclaim, 103.0)

    # ══ Jahreslimit: § 4.1 ein- und mehrtägig gemeinsam max. 4/Jahr ══════════
    def test_yearly_limit_shared_group(self):
        """4.1a und 4.1b teilen sich das Limit (max. 4 Freizeitmaßnahmen/Jahr).
        Nach 4 bewilligten Anträgen (gemischt) wird der 5. blockiert."""
        for i in range(2):
            self._app('kjr_grant.grant_type_4_1a', tn_count=10,
                      cost_accommodation=200.0, state='approved')
            self._app('kjr_grant.grant_type_4_1b', tn_count=10,
                      cost_accommodation=200.0, state='approved')
        fifth = self._app('kjr_grant.grant_type_4_1a', tn_count=10, cost_accommodation=200.0)
        with self.assertRaises(UserError):
            fifth._check_yearly_limit()

    # ══ BJR § 33: Vollversammlung – Beschlussfähigkeit & Mehrheit ════════════
    def test_assembly_repeat_session_quorum(self):
        """§ 33 Abs. 3: Eine Wiederholungssitzung ist mit jedem anwesenden
        Stimmberechtigten beschlussfähig (quorum-unabhängig)."""
        a = self.env['kjr.assembly'].create({
            'name': 'Wiederholungs-VV',
            'date': '2026-03-01 18:00:00',
            'is_repeat_session': True,
            'attendee_ids': [(6, 0, [self.assoc.id])],
        })
        self.assertTrue(a.quorum_reached)
        a.attendee_ids = [(5, 0, 0)]
        self.assertFalse(a.quorum_reached)

    def test_assembly_decision_majority_ignores_abstentions(self):
        """§ 33 Abs. 1: Mehrheit der Ja-/Nein-Stimmen entscheidet; Enthaltungen
        zählen nicht. 3 Ja : 2 Nein bei 5 Enthaltungen → angenommen."""
        a = self.env['kjr.assembly'].create({
            'name': 'VV 2026', 'date': '2026-03-01 18:00:00',
        })
        d = self.env['kjr.assembly.decision'].create({
            'assembly_id': a.id, 'name': 'Haushalt 2026',
            'vote_yes': 3, 'vote_no': 2, 'vote_abstain': 5,
        })
        self.assertEqual(d.result, 'accepted')
        d.write({'vote_yes': 2, 'vote_no': 3})
        self.assertEqual(d.result, 'rejected')

    # ══ Juleica-Lifecycle: Gültigkeit 3 Jahre ════════════════════════════════
    def test_juleica_validity_three_years(self):
        """Ausstellung + 3 Jahre = Ablaufdatum; aktuelle Karte ist 'gültig'."""
        card = self.env['kjr.juleica'].create({
            'partner_id': self.person.id,
            'issue_date': '2026-01-01',
            'validity_years': 3,
        })
        self.assertEqual(str(card.expiry_date), '2029-01-01')
        self.assertEqual(card.state, 'valid')

    def test_juleica_expired(self):
        """Eine vor über 3 Jahren ausgestellte Karte ist abgelaufen."""
        card = self.env['kjr.juleica'].create({
            'partner_id': self.person.id,
            'issue_date': '2020-01-01',
            'validity_years': 3,
        })
        self.assertEqual(str(card.expiry_date), '2023-01-01')
        self.assertEqual(card.state, 'expired')
