# -*- coding: utf-8 -*-
"""Termin 13.10.2026: Endreinigung/Kurbeitrag je Einrichtung, Buchungsvorlauf
18 Monate und Anfrage ohne Konto (Schalter je Einrichtung)."""
import re
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import HttpCase, new_test_user, tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestKjrFacilityFees(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'RF Gruppe'})
        cls.facility = cls.env['kjr.facility'].create({
            'name': 'RF Haus', 'capacity': 50,
        })
        cls.tariff = cls.env['kjr.facility.tariff'].create({
            'name': 'RF Standard', 'facility_id': cls.facility.id,
            'price_per_person_night': 10.0,
        })

    def _booking(self, **kw):
        vals = {
            'facility_id': self.facility.id, 'partner_id': self.partner.id,
            'tariff_id': self.tariff.id,
            'check_in': '2026-08-01', 'check_out': '2026-08-05',
            'participant_count': 10, 'leader_count': 2,
        }
        vals.update(kw)
        return self.env['kjr.facility.booking'].create(vals)

    def test_standard_ohne_betraege(self):
        """Ohne gepflegte Beträge entstehen keine Positionen (nichts erfunden)."""
        self.assertEqual(self.facility.final_cleaning_fee, 0.0)
        self.assertEqual(self.facility.visitor_tax_per_person_night, 0.0)
        self.assertEqual(self.facility.visitor_tax_exempt_age, 0)
        booking = self._booking()
        self.assertEqual(booking.amount_cleaning, 0.0)
        self.assertEqual(booking.amount_visitor_tax, 0.0)
        self.assertEqual(booking.amount_untaxed, 400.0)

    def test_betraege_der_einrichtung(self):
        """Endreinigung einmalig, Kurbeitrag je beitragspflichtiger Person und Nacht."""
        self.facility.write({'final_cleaning_fee': 50.0,
                             'visitor_tax_per_person_night': 2.0})
        booking = self._booking(visitor_tax_exempt_count=2)
        self.assertEqual(booking.amount_cleaning, 50.0)
        # (10 Teilnehmende − 2 befreit) × 4 Nächte × 2 € = 64 €; Betreuende frei.
        self.assertEqual(booking.amount_visitor_tax, 64.0)
        self.assertEqual(booking.amount_untaxed, 400.0 + 50.0 + 64.0)

    def test_tarif_geht_vor(self):
        """Ein Betrag am Tarif (> 0) ersetzt den Betrag der Einrichtung."""
        self.facility.write({'final_cleaning_fee': 50.0,
                             'visitor_tax_per_person_night': 2.0})
        self.tariff.write({'final_cleaning_fee': 80.0,
                           'visitor_tax_per_person_night': 1.5})
        booking = self._booking()
        self.assertEqual(booking.amount_cleaning, 80.0)
        self.assertEqual(booking.amount_visitor_tax, 10 * 4 * 1.5)
        self.assertEqual(self.facility._fee_rates(self.tariff)['cleaning'], 80.0)
        self.assertEqual(self.facility._fee_rates()['cleaning'], 50.0)

    def test_spaeter_gepflegter_betrag_aendert_alte_buchung_nicht(self):
        """Nachgetragene Beträge der Einrichtung ändern bestehende Buchungen nicht
        stillschweigend, wohl aber bei der nächsten Änderung der Buchung."""
        booking = self._booking()
        self.assertEqual(booking.amount_cleaning, 0.0)
        self.env.flush_all()
        self.facility.final_cleaning_fee = 50.0
        self.env.flush_all()
        self.assertEqual(booking.amount_cleaning, 0.0)
        booking.participant_count = 11
        self.assertEqual(booking.amount_cleaning, 50.0)

    def test_keine_negativen_werte(self):
        with self.assertRaises(ValidationError):
            self.facility.final_cleaning_fee = -1.0
        with self.assertRaises(ValidationError):
            self.facility.visitor_tax_exempt_age = -1

    # ── Buchungsvorlauf ─────────────────────────────────────────────────────
    def test_vorlauf_standard_18_monate(self):
        today = fields.Date.from_string('2026-10-22')
        self.assertEqual(self.facility.max_advance_months, 18)
        self.assertEqual(self.facility._latest_check_in(today),
                         fields.Date.from_string('2028-04-22'))
        self.facility.max_advance_months = 0
        self.assertIsNone(self.facility._latest_check_in(today))

    def test_vorlauf_hinweis_im_backend(self):
        """Im Backend bleibt der Vorlauf ein Hinweis (Ausnahmen möglich)."""
        today = fields.Date.today()
        too_late = today + relativedelta(months=18, days=5)
        booking = self._booking(check_in=too_late, check_out=too_late + timedelta(days=2))
        self.assertIn('Buchungsvorlauf', booking.occupancy_warning or '')
        ok = today + relativedelta(months=17)
        booking = self._booking(check_in=ok, check_out=ok + timedelta(days=2))
        self.assertNotIn('Buchungsvorlauf', booking.occupancy_warning or '')


@tagged('post_install', '-at_install')
class TestKjrFacilityRequestForm(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.facility = cls.env['kjr.facility'].create({
            'name': 'RF Formularhaus', 'capacity': 60, 'website_published': True,
            'visitor_tax_per_person_night': 2.0, 'visitor_tax_exempt_age': 6,
        })
        cls.env['kjr.facility.tariff'].create({
            'name': 'RF Formulartarif', 'facility_id': cls.facility.id,
            'tariff_type': 'standard', 'price_per_person_night': 10.0,
        })
        cls.url = '/service/einrichtung/%d/anfrage' % cls.facility.id
        new_test_user(cls.env, login='rf_portal', password='rf_portal_pw_1',
                      groups='base.group_portal', name='RF Portal')

    def _csrf(self, html):
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def test_ohne_konto_standard_anmeldung(self):
        """Standard: ohne Anmeldung geht es zur Anmeldeseite (bisheriges Verhalten)."""
        response = self.url_open(self.url, allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.assertIn('/web/login', response.headers.get('Location', ''))

    def test_formular_datumsgrenze_und_kurbeitrag(self):
        self.authenticate('rf_portal', 'rf_portal_pw_1')
        html = self.url_open(self.url).text
        latest = self.facility._latest_check_in(fields.Date.today())
        self.assertIn('max="%s"' % latest.isoformat(), html)
        self.assertIn('Teilnehmende unter', html)
        self.assertIn('6 Jahren', html)
        # Serverseitig: Anreise jenseits des Vorlaufs wird abgewiesen.
        too_late = latest + timedelta(days=1)
        response = self.url_open(self.url, data={
            'csrf_token': self._csrf(html), 'action': 'submit',
            'check_in': too_late.isoformat(),
            'check_out': (too_late + timedelta(days=2)).isoformat(),
            'participant_count': '10', 'contact_person': 'RF Leitung',
        })
        self.assertIn('höchstens 18 Monate im Voraus', response.text)
        self.assertFalse(self.env['kjr.facility.booking'].search(
            [('facility_id', '=', self.facility.id)]))

    def test_anfrage_ohne_konto_erlaubt(self):
        self.facility.allow_guest_request = True
        html = self.url_open(self.url).text
        self.assertIn('name="street"', html)
        check_in = fields.Date.today() + timedelta(days=30)
        data = {
            'csrf_token': self._csrf(html), 'action': 'submit',
            'check_in': check_in.isoformat(),
            'check_out': (check_in + timedelta(days=2)).isoformat(),
            'participant_count': '10', 'contact_person': 'RF Gast Leitung',
        }
        # Pflichtangaben fehlen: Anschrift, E-Mail, Telefon.
        response = self.url_open(self.url, data=data)
        self.assertIn('Straße und Hausnummer ist ein Pflichtfeld', response.text)
        data.update({'street': 'RF-Weg 1', 'zip': '87527', 'city': 'RF-Ort',
                     'contact_email': 'rf.gast@example.com', 'contact_phone': '0123 456'})
        data['csrf_token'] = self._csrf(response.text)
        response = self.url_open(self.url, data=data)
        self.assertIn('Vielen Dank für Ihre Anfrage', response.text)
        booking = self.env['kjr.facility.booking'].search(
            [('facility_id', '=', self.facility.id)])
        self.assertEqual(len(booking), 1)
        partner = booking.partner_id
        self.assertIn('ungeprüfte Website-Anfrage', partner.name)
        self.assertEqual((partner.street, partner.zip, partner.city, partner.email, partner.phone),
                         ('RF-Weg 1', '87527', 'RF-Ort', 'rf.gast@example.com', '0123 456'))
        self.assertFalse(partner.user_ids)
