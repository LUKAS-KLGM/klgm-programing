# -*- coding: utf-8 -*-
"""Höchstbetrag pro Jahr und Verband (19.0.18.0.1).

Zuschussrichtlinie (Fassung ab 01.12.2022):
  § 4.5  „Der Zuschuss beträgt 8 € pro Tag und Teilnehmer, jedoch max. 700 € pro Jahr.“
  § 4.6  „Die jährliche Höchstfördersumme beträgt 300 €.“
  § 4.8a „… mit 2 € pro Teilnehmer, jedoch max. 400 € jährlich bezuschusst.“

Gezählt wird je Verband, Maßnahmenjahr und Förderart über eingereichte, in
Prüfung befindliche, bewilligte und ausgezahlte Anträge, in der Reihenfolge
des Eingangs.
"""
import importlib.util

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import HttpCase, TransactionCase, new_test_user
from odoo.tools.misc import file_path

MIGRATION = 'kjr_grant/migrations/19.0.18.0.1/post-jahreshoechstbetrag.py'


@tagged('post_install', '-at_install')
class TestKjrGrantYearCap(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Application = cls.env['kjr.grant.application']
        Partner = cls.env['res.partner']
        cls.assoc = Partner.create({
            'name': 'Jahresgrenze Verband e. V.', 'is_company': True,
            'is_kjr_member': True, 'kjr_vr_right': True,
        })
        cls.other_assoc = Partner.create({
            'name': 'Anderer Verband e. V.', 'is_company': True,
            'is_kjr_member': True, 'kjr_vr_right': True,
        })

    def _app_4_5(self, partner=None, start='2026-07-01', end='2026-07-03', tn=30, **kw):
        """30 TN × 3 Tage × 8 € = 720 €, je Antrag gedeckelt auf 700 €."""
        vals = {
            'partner_id': (partner or self.assoc).id,
            'grant_type_id': self.env.ref('kjr_grant.grant_type_4_5').id,
            'measure_name': 'Jugendbegegnung',
            'measure_start': start,
            'measure_end': end,
            'tn_count': tn,
            'cost_accommodation': 5000.0,
        }
        vals.update(kw)
        return self.Application.create(vals)

    def test_stammdaten_aus_richtlinie(self):
        self.assertEqual(self.env.ref('kjr_grant.grant_type_4_5').max_amount_per_year, 700.0)
        self.assertEqual(self.env.ref('kjr_grant.grant_type_4_6').max_amount_per_year, 300.0)
        self.assertEqual(self.env.ref('kjr_grant.grant_type_4_8a').max_amount_per_year, 400.0)
        # Ohne Jahresgrenze laut Richtlinie: z. B. § 4.1b (Grenze je Maßnahme).
        self.assertEqual(self.env.ref('kjr_grant.grant_type_4_1b').max_amount_per_year, 0.0)

    def test_einzelantrag_unveraendert(self):
        app = self._app_4_5()
        self.assertEqual(app.grant_calculated, 700.0)
        self.assertIn('verbleibend: 700,00 €', app.year_cap_info)

    def test_zweiter_antrag_erhaelt_nur_rest(self):
        """Bewilligt 500 € → ein weiterer Antrag im selben Jahr erhält max. 200 €."""
        self._app_4_5(state='approved', date_submitted='2026-07-10', grant_approved=500.0)
        app = self._app_4_5(start='2026-08-01', end='2026-08-03')
        self.assertEqual(app.grant_calculated, 200.0)
        self.assertIn('bereits gebunden: 500,00 €', app.year_cap_info)
        self.assertIn('gekappt', app.year_cap_info)

    def test_eingereichte_zaehlen_mit(self):
        """Auch eingereichte (noch nicht bewilligte) Anträge binden den Betrag."""
        self._app_4_5(state='submitted', date_submitted='2026-07-10', tn=10)  # 240 €
        app = self._app_4_5(start='2026-08-01', end='2026-08-03')
        self.assertEqual(app.grant_calculated, 460.0)

    def test_entwurf_abgelehnt_anderes_jahr_anderer_verband_zaehlen_nicht(self):
        self._app_4_5()  # Entwurf
        self._app_4_5(state='rejected', date_submitted='2026-07-10')
        self._app_4_5(state='approved', date_submitted='2025-07-10',
                      start='2025-07-01', end='2025-07-03', grant_approved=700.0)
        self._app_4_5(partner=self.other_assoc, state='approved',
                      date_submitted='2026-07-10', grant_approved=700.0)
        app = self._app_4_5(start='2026-08-01', end='2026-08-03')
        self.assertEqual(app.grant_calculated, 700.0)

    def test_reihenfolge_nach_eingang(self):
        """Der früher eingegangene Antrag behält seinen Betrag, auch wenn er
        später neu berechnet wird; der spätere erhält nur den Rest."""
        first = self._app_4_5(state='submitted', date_submitted='2026-07-10')
        second = self._app_4_5(state='submitted', date_submitted='2026-08-10',
                               start='2026-08-01', end='2026-08-03')
        self.assertEqual(first.grant_calculated, 700.0)
        self.assertEqual(second.grant_calculated, 0.0)
        first.tn_count = 31  # erneute Berechnung des früheren Antrags
        self.assertEqual(first.grant_calculated, 700.0)
        second.tn_count = 29
        self.assertEqual(second.grant_calculated, 0.0)

    def test_einreichen_gesperrt_wenn_ausgeschoepft(self):
        self._app_4_5(state='approved', date_submitted='2026-07-10', grant_approved=700.0)
        app = self._app_4_5(start='2026-08-01', end='2026-08-03')
        self.assertEqual(app.grant_calculated, 0.0)
        self.assertIn('kein Zuschuss mehr möglich', app.year_cap_info)
        with self.assertRaisesRegex(UserError, 'ausgeschöpft'):
            app._check_year_cap()

    def test_nachberechnung_bei_bewilligung(self):
        """Wird ein früherer Antrag nach der Berechnung bewilligt, zieht
        _recompute_year_cap den Rest vor der Bewilligung nach."""
        app = self._app_4_5(state='submitted', date_submitted='2026-08-10',
                            start='2026-08-01', end='2026-08-03')
        self.assertEqual(app.grant_calculated, 700.0)
        self._app_4_5(state='approved', date_submitted='2026-07-10', grant_approved=300.0)
        app._recompute_year_cap()
        self.assertEqual(app.grant_calculated, 400.0)

    def test_4_6_materialien(self):
        gt = self.env.ref('kjr_grant.grant_type_4_6')
        vals = {
            'partner_id': self.assoc.id, 'grant_type_id': gt.id,
            'measure_name': 'Zelt', 'measure_start': '2026-03-01', 'measure_end': '2026-03-01',
            'cost_materials': 400.0,
        }
        first = self.Application.create(dict(vals, state='approved',
                                             date_submitted='2026-03-05', grant_approved=200.0))
        self.assertEqual(first.grant_calculated, 200.0)  # 50 % von 400 €
        second = self.Application.create(vals)
        self.assertEqual(second.grant_calculated, 100.0)

    def test_ohne_jahresgrenze_keine_kappung(self):
        gt = self.env.ref('kjr_grant.grant_type_4_5')
        gt.max_amount_per_year = 0.0
        self._app_4_5(state='approved', date_submitted='2026-07-10', grant_approved=700.0)
        app = self._app_4_5(start='2026-08-01', end='2026-08-03')
        self.assertEqual(app.grant_calculated, 700.0)
        self.assertFalse(app.year_cap_info)

    def test_migration(self):
        spec = importlib.util.spec_from_file_location('kjr_grant_jahreshoechstbetrag', file_path(MIGRATION))
        mig = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mig)
        t45 = self.env.ref('kjr_grant.grant_type_4_5')
        t46 = self.env.ref('kjr_grant.grant_type_4_6')
        t48a = self.env.ref('kjr_grant.grant_type_4_8a')
        t42 = self.env.ref('kjr_grant.grant_type_4_2')
        t45.max_amount_per_year = 0.0
        t46.max_amount_per_year = 250.0  # im Backend gepflegt: bleibt
        t48a.max_amount_per_year = 0.0
        t42.description = 'Maßnahmen die dem Verbandszweck dienen (z. B. Probentage).'
        t46.description = 'Nur für Gegenstände die ausschließlich für Jugendarbeit genutzt werden.'
        mig.migrate(self.env.cr, '19.0.18.0.0')
        self.assertEqual(t45.max_amount_per_year, 700.0)
        self.assertEqual(t46.max_amount_per_year, 250.0)
        self.assertEqual(t48a.max_amount_per_year, 400.0)
        self.assertIn('Maßnahmen, die dem', t42.description)
        self.assertIn('Gegenstände, die ausschließlich', t46.description)
        vorher = (t42.description, t46.description)
        mig.migrate(self.env.cr, '19.0.18.0.0')
        self.assertEqual(vorher, (t42.description, t46.description))


@tagged('post_install', '-at_install')
class TestKjrGrantYearCapHelp(HttpCase):

    def test_hilfeseite_texte(self):
        text = self.url_open('/service/zuschuss/hilfe').text
        self.assertIn('700,00 € pro Jahr', text)
        self.assertIn('Der Höchstbetrag pro Jahr gilt je Verband', text)
        self.assertIn('stellt trotzdem der Verband', text)
        self.assertIn('privaten Zugang ist kein Antrag möglich', text)
        self.assertNotIn('Zuschussrichtlinien von', text)
        landing = self.url_open('/service/zuschuss').text
        self.assertNotIn('Zuschussantrag bei', landing)

    def test_antragsformular_texte(self):
        """Hinweis Bankverbindung nennt alle Förderarten mit Privatkonto-Freigabe
        (§ 4.4 und § 4.9) aus den Stammdaten; Kopfzeile ohne „Antrag bei“."""
        assoc = self.env['res.partner'].create({
            'name': 'Jahresgrenze Formular e. V.', 'is_company': True,
            'is_kjr_member': True, 'kjr_vr_right': True,
        })
        user = new_test_user(self.env, login='kjr_jahresgrenze_portal', groups='base.group_portal')
        user.partner_id.parent_id = assoc
        self.authenticate('kjr_jahresgrenze_portal', 'kjr_jahresgrenze_portal')
        form = self.url_open('/service/antrag-stellen').text
        self.assertNotIn('Antrag bei', form)
        self.assertIn('Antrag auf Zuschuss', form)
        self.assertIn(self.env.ref('kjr_grant.grant_type_4_4').name, form)
        self.assertIn(self.env.ref('kjr_grant.grant_type_4_9').name, form)
        self.assertIn('ist auch ein Privatkonto möglich. Den Antrag stellt trotzdem der Verband.', form)
