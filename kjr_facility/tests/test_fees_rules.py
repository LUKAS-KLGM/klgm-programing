# -*- coding: utf-8 -*-
"""Termin 13.10.2026: Endreinigung/Kurbeitrag je Einrichtung, Buchungsvorlauf
18 Monate und Anfrage ohne Konto (Schalter je Einrichtung).

Rückmeldung KJR 11/2026: eigener Hinweis zum Kurbeitrag, Telefon und E-Mail
immer Pflicht, Anzahlung je Einrichtung mit Frist und Bankverbindung im Vertrag.

Rückmeldung 05.11.2026: keine Anzahlung als Standard, Hinweis zu den Befreiten
pflegbar, Befreiung der Betreuenden als Einstellung."""
import re
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
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


    def test_anzahlung_aus_einrichtung(self):
        """Neue Buchungen übernehmen den Anzahlungssatz der Einrichtung."""
        # Standard: keine Anzahlung (Rückmeldung KJR 05.11.2026).
        self.assertEqual(self.facility.deposit_pct_default, 0.0)
        self.assertEqual(self._booking().deposit_pct, 0.0)
        self.facility.deposit_pct_default = 30.0
        booking = self._booking()
        self.assertEqual(booking.deposit_pct, 30.0)
        self.assertEqual(booking.deposit_amount, booking.amount_total * 0.3)
        self.facility.deposit_pct_default = 0.0
        self.assertEqual(self._booking().deposit_amount, 0.0)
        # Von Hand übergebener Satz bleibt.
        self.assertEqual(self._booking(deposit_pct=50.0).deposit_pct, 50.0)
        with self.assertRaises(ValidationError):
            self.facility.deposit_pct_default = 120.0

    def test_anzahlung_faelligkeit_beim_bestaetigen(self):
        today = fields.Date.today()
        self.facility.write({'deposit_pct_default': 20.0, 'deposit_due_days': 14})
        booking = self._booking(check_in=today + timedelta(days=60),
                                check_out=today + timedelta(days=62))
        booking._set_deposit_due_date()
        self.assertEqual(booking.deposit_due_date, today + timedelta(days=14))
        # Kurz vor der Anreise: höchstens Vortag der Anreise.
        short = self._booking(check_in=today + timedelta(days=5),
                              check_out=today + timedelta(days=7))
        short._set_deposit_due_date()
        self.assertEqual(short.deposit_due_date, today + timedelta(days=4))
        # Von Hand gesetztes Datum bleibt, ohne Anzahlung kein Datum.
        manual = self._booking(check_in=today + timedelta(days=60),
                               check_out=today + timedelta(days=62),
                               deposit_due_date=today + timedelta(days=30))
        manual._set_deposit_due_date()
        self.assertEqual(manual.deposit_due_date, today + timedelta(days=30))
        none = self._booking(check_in=today + timedelta(days=60),
                             check_out=today + timedelta(days=62), deposit_pct=0.0)
        none._set_deposit_due_date()
        self.assertFalse(none.deposit_due_date)

    def test_vertrag_nennt_anzahlung_frist_und_konto(self):
        today = fields.Date.today()
        bank = self.env['res.partner.bank'].create({
            'partner_id': self.env.company.partner_id.id,
            'acc_number': 'DE02120300000000202051',
        })
        booking = self._booking(check_in=today + timedelta(days=60),
                                check_out=today + timedelta(days=62), deposit_pct=20.0,
                                deposit_due_date=today + timedelta(days=14))
        html = self.env['ir.actions.report']._render_qweb_html(
            'kjr_facility.action_report_booking_contract', booking.ids)[0].decode()
        self.assertIn('Bitte überweisen Sie die Anzahlung', html)
        self.assertIn((today + timedelta(days=14)).strftime('%d.%m.%Y'), html)
        self.assertIn(bank.acc_number, html)
        self.assertIn(booking.name, html)
        booking.deposit_pct = 0.0
        html = self.env['ir.actions.report']._render_qweb_html(
            'kjr_facility.action_report_booking_contract', booking.ids)[0].decode()
        self.assertNotIn('Bitte überweisen Sie die Anzahlung', html)
        self.assertNotIn('Anzahlung (', html)

    def test_ohne_anzahlung_keine_anforderung(self):
        """Bei 0 % lässt sich keine Anzahlung anfordern, der Mahn-Cron greift nicht."""
        today = fields.Date.today()
        booking = self._booking(check_in=today + timedelta(days=60),
                                check_out=today + timedelta(days=62))
        booking.action_confirm()
        self.assertEqual(booking.state, 'confirmed')
        self.assertFalse(booking.deposit_due_date)
        with self.assertRaises(UserError):
            booking.action_request_deposit()
        self.assertEqual(booking.state, 'confirmed')

    def test_onchange_uebernimmt_anzahlung_der_einrichtung(self):
        """Im Backend-Formular kommt der Satz beim Wählen der Einrichtung mit."""
        self.facility.deposit_pct_default = 25.0
        form = self.env['kjr.facility.booking'].new({'state': 'draft', 'deposit_pct': 0.0})
        form.facility_id = self.facility
        form._onchange_facility_deposit()
        self.assertEqual(form.deposit_pct, 25.0)

    def test_betreuende_nicht_befreit(self):
        """Einstellung aus: Betreuende zählen beim Kurbeitrag mit."""
        self.facility.write({'visitor_tax_per_person_night': 2.0,
                             'visitor_tax_leaders_exempt': False})
        booking = self._booking(visitor_tax_exempt_count=2)
        # (10 Teilnehmende + 2 Betreuende − 2 befreit) × 4 Nächte × 2 € = 80 €.
        self.assertEqual(booking.amount_visitor_tax, 80.0)
        booking.leader_count = 3
        self.assertEqual(booking.amount_visitor_tax, 88.0)
        # Spätere Änderung an der Einrichtung lässt die Buchung (und ihre Rechnung) stehen.
        self.facility.visitor_tax_leaders_exempt = True
        self.assertFalse(booking.visitor_tax_leaders_exempt)
        self.assertEqual(booking._visitor_tax_person_count(), 11)
        self.assertEqual(booking.amount_visitor_tax, 88.0)


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
        # Serverseitig: Anreise jenseits des Vorlaufs wird abgewiesen.
        too_late = latest + timedelta(days=1)
        response = self.url_open(self.url, data={
            'csrf_token': self._csrf(html), 'action': 'submit',
            'check_in': too_late.isoformat(),
            'check_out': (too_late + timedelta(days=2)).isoformat(),
            'participant_count': '10', 'leader_count': '2',
            'group_name': 'RF Gruppe', 'privacy_ack': '1', 'contact_person': 'RF Leitung',
            'contact_email': 'rf.leitung@example.com', 'contact_phone': '0123 1',
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
            'participant_count': '10', 'leader_count': '2',
            'group_name': 'RF Gruppe', 'privacy_ack': '1', 'contact_person': 'RF Gast Leitung',
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

    def test_kostenvorschau_ohne_action_legt_nichts_an(self):
        """reCAPTCHA schickt per form.submit() ab, ohne den Knopf (name="action").

        Die Vorschau muss trotzdem über kjr_preview erkannt werden und darf keine
        Buchung anlegen. Angemeldete Nutzer bekommen kein data-captcha.
        """
        self.authenticate('rf_portal', 'rf_portal_pw_1')
        html = self.url_open(self.url).text
        self.assertNotIn('data-captcha', html)
        self.assertIn('name="kjr_preview"', html)
        check_in = fields.Date.today() + timedelta(days=30)
        response = self.url_open(self.url, data={
            'csrf_token': self._csrf(html), 'kjr_preview': '1',
            'check_in': check_in.isoformat(),
            'check_out': (check_in + timedelta(days=2)).isoformat(),
            'participant_count': '10', 'leader_count': '2',
            'group_name': 'RF Gruppe', 'privacy_ack': '1', 'contact_person': 'RF Vorschau',
            'contact_email': 'rf.vorschau@example.com', 'contact_phone': '0123 2',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.env['kjr.facility.booking'].search(
            [('facility_id', '=', self.facility.id)]))

    def test_gastformular_hat_captcha(self):
        self.facility.allow_guest_request = True
        html = self.url_open(self.url).text
        self.assertIn('data-captcha="kjr_facility_request"', html)

    def test_betraege_deutsch_formatiert(self):
        """Gebührenhinweis und Kostenvorschau: „1.240,00 €" mit geschütztem
        Leerzeichen vor dem €, nie „1240.00 €"."""
        lang = self.env['res.lang']._activate_lang('de_DE')
        websites = self.env['website'].search([])
        for website in websites:
            website.language_ids |= lang
        websites.write({'default_lang_id': lang.id})
        self.facility.final_cleaning_fee = 1240.0
        self.authenticate('rf_portal', 'rf_portal_pw_1')
        html = self.url_open(self.url).text
        self.assertIn('1.240,00</span>\N{NO-BREAK SPACE}€', html)
        self.assertIn('2,00</span>\N{NO-BREAK SPACE}€', html)
        self.assertNotIn('1240.00', html)
        check_in = fields.Date.today() + timedelta(days=30)
        response = self.url_open(self.url, data={
            'csrf_token': self._csrf(html), 'kjr_preview': '1',
            'check_in': check_in.isoformat(),
            'check_out': (check_in + timedelta(days=2)).isoformat(),
            'participant_count': '10', 'leader_count': '2',
            'group_name': 'RF Gruppe', 'privacy_ack': '1', 'contact_person': 'RF Vorschau',
            'contact_email': 'rf.vorschau@example.com', 'contact_phone': '0123 2',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('1.240,00</span>\N{NO-BREAK SPACE}€', response.text)
        self.assertNotRegex(response.text, r'\d\.\d\d €')

    def test_kurbeitrag_eigener_hinweis(self):
        """Eigener Hinweis ersetzt den Standardtext, leer gilt der Standard."""
        self.authenticate('rf_portal', 'rf_portal_pw_1')
        html = self.url_open(self.url).text
        self.assertIn('Den Beitrag führen wir an die Gemeinde ab.', html)
        self.assertNotIn('als Begleitpersonen befreit', html)
        self.facility.visitor_tax_note = '<p>RF eigener Kurbeitrag-Hinweis</p>'
        html = self.url_open(self.url).text
        self.assertIn('RF eigener Kurbeitrag-Hinweis', html)
        self.assertNotIn('Den Beitrag führen wir an die Gemeinde ab.', html)

    def test_formular_ohne_befreite_mit_pflicht_betreuende_gruppe(self):
        """Termin 05.11.2026: kein Befreiten-Feld mehr; Betreuende und Gruppe Pflicht."""
        self.authenticate('rf_portal', 'rf_portal_pw_1')
        html = self.url_open(self.url).text
        self.assertNotIn('name="visitor_tax_exempt_count"', html)
        self.assertNotIn('befreite', html)
        self.assertRegex(html, r'name="leader_count"[^>]*required')
        self.assertRegex(html, r'name="group_name"[^>]*required')
        check_in = fields.Date.today() + timedelta(days=30)
        data = {
            'csrf_token': self._csrf(html), 'action': 'submit',
            'check_in': check_in.isoformat(),
            'check_out': (check_in + timedelta(days=2)).isoformat(),
            'participant_count': '10', 'contact_person': 'RF Pflicht2',
            'privacy_ack': '1',
            'contact_email': 'rf.p2@example.com', 'contact_phone': '0123 9',
        }
        response = self.url_open(self.url, data=data)
        self.assertIn('Anzahl der Betreuenden ist ein Pflichtfeld', response.text)
        self.assertIn('Gruppenbezeichnung ist ein Pflichtfeld', response.text)
        self.assertFalse(self.env['kjr.facility.booking'].search(
            [('facility_id', '=', self.facility.id)]))
        data.update({'csrf_token': self._csrf(response.text),
                     'leader_count': '0', 'group_name': 'RF Klasse 7b'})
        self.url_open(self.url, data=data)
        booking = self.env['kjr.facility.booking'].search(
            [('facility_id', '=', self.facility.id)])
        self.assertEqual((booking.group_name, booking.leader_count), ('RF Klasse 7b', 0))

    def test_datenschutz_aufklappbar_und_bestaetigung_pflicht(self):
        """Termin 05.11.2026: Datenschutz aufklappbar, Bestätigung per Checkbox Pflicht."""
        self.authenticate('rf_portal', 'rf_portal_pw_1')
        html = self.url_open(self.url).text
        self.assertIn('<details class="o_kjr_privacy_details">', html)
        self.assertRegex(html, r'name="privacy_ack"[^>]*required')
        check_in = fields.Date.today() + timedelta(days=30)
        data = {
            'csrf_token': self._csrf(html), 'action': 'submit',
            'check_in': check_in.isoformat(),
            'check_out': (check_in + timedelta(days=2)).isoformat(),
            'participant_count': '10', 'leader_count': '1', 'group_name': 'RF DS',
            'contact_person': 'RF DS', 'contact_email': 'rf.ds@example.com',
            'contact_phone': '0123 7',
        }
        response = self.url_open(self.url, data=data)
        self.assertIn('Datenschutzerklärung gelesen und', response.text)
        self.assertIn('is-invalid', response.text)
        self.assertFalse(self.env['kjr.facility.booking'].search(
            [('facility_id', '=', self.facility.id)]))
        data.update({'csrf_token': self._csrf(response.text), 'privacy_ack': '1'})
        self.url_open(self.url, data=data)
        self.assertTrue(self.env['kjr.facility.booking'].search(
            [('facility_id', '=', self.facility.id)]))

    def test_telefon_und_email_pflicht_mit_konto(self):
        """Auch mit Konto sind Telefon und E-Mail Pflicht (vorbelegt aus dem Konto)."""
        self.authenticate('rf_portal', 'rf_portal_pw_1')
        html = self.url_open(self.url).text
        self.assertRegex(html, r'type="email" name="contact_email"[^>]*required')
        self.assertRegex(html, r'type="tel" name="contact_phone"[^>]*required')
        check_in = fields.Date.today() + timedelta(days=30)
        data = {
            'csrf_token': self._csrf(html), 'action': 'submit',
            'check_in': check_in.isoformat(),
            'check_out': (check_in + timedelta(days=2)).isoformat(),
            'participant_count': '10', 'leader_count': '2',
            'group_name': 'RF Gruppe', 'privacy_ack': '1', 'contact_person': 'RF Pflicht',
            'contact_email': '', 'contact_phone': '',
        }
        response = self.url_open(self.url, data=data)
        self.assertIn('Telefon ist ein Pflichtfeld', response.text)
        self.assertIn('E-Mail ist ein Pflichtfeld', response.text)
        self.assertFalse(self.env['kjr.facility.booking'].search(
            [('facility_id', '=', self.facility.id)]))
        data.update({'csrf_token': self._csrf(response.text),
                     'contact_email': 'rf.pflicht@example.com', 'contact_phone': '0123 3'})
        # Mit Konto führt das Absenden auf die Buchungsdetailseite im Portal.
        response = self.url_open(self.url, data=data)
        self.assertEqual(response.status_code, 200)
        booking = self.env['kjr.facility.booking'].search(
            [('facility_id', '=', self.facility.id)])
        self.assertEqual((booking.contact_email, booking.contact_phone),
                         ('rf.pflicht@example.com', '0123 3'))
