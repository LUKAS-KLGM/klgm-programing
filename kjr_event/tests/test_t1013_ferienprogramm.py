# -*- coding: utf-8 -*-
"""Termin 13.10.2026 (19.0.5.11.0): Alterskulanz, Postleitzahlen,
"Anmeldung ab", neues Anmeldeformular und Rechnungskontakt."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.kjr_event.controllers import website_event as kjr_website_event


@tagged('post_install', '-at_install')
class TestKjrT1013(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.controller = kjr_website_event.KjrWebsiteEventController()
        cls.Event = cls.env['event.event']
        cls.Registration = cls.env['event.registration']
        cls.event = cls.Event.create({
            'name': 'Ferienprogramm T1013',
            'is_kjr': True,
            'kjr_event_type': 'ferienprogramm',
            'date_begin': '2027-07-10 09:00:00',
            'date_end': '2027-07-15 17:00:00',
            'kjr_min_age': 8,
            'kjr_max_age': 12,
        })
        cls.env['ir.config_parameter'].sudo().set_param('kjr_event.allowed_zips', '87527, 87509')

    def _ctl(self, method, *args):
        with patch.object(kjr_website_event, 'request', SimpleNamespace(env=self.env)):
            return getattr(self.controller, method)(*args)

    def _post(self, **overrides):
        post = {
            '1-event_ticket_id': '0',
            '1-name-1': 'Mia Muster',
            '1-kjr_gender': 'female',
            '1-birthdate': '2017-03-01',
            '1-kjr_street': 'Bahnhofstraße 1',
            '1-kjr_zip': '87527',
            '1-kjr_city': 'Sonthofen',
            '1-kjr_medical_note': 'keine',
            '1-guardian_name': 'Eva Muster',
            '1-guardian_email': 'eva@example.com',
            '1-guardian_phone': '0831 123',
            '1-guardian_same_address': '1',
            '1-emergency_contact': 'Opa Muster',
            '1-kjr_emergency_phone': '0831 456',
            'kjr_privacy_accepted': '1',
            'kjr_terms_accepted': '1',
            'kjr_data_confirmed': '1',
        }
        post.update(overrides)
        return {k: v for k, v in post.items() if v is not None}

    # ------------------------------------------------------------------
    # Punkt 3: Alterskulanz
    # ------------------------------------------------------------------
    def test_age_tolerance_min_age(self):
        """8. Geburtstag 22 Tage nach Beginn: ohne Kulanz zu jung, mit 42 Tagen ok."""
        self.assertEqual(self.event._kjr_age_check('2019-08-01'), 'too_young')
        self.event.kjr_age_tolerance_days = 42
        self.assertIsNone(self.event._kjr_age_check('2019-08-01'))
        # 50 Tage nach Beginn bleibt auch mit Kulanz zu jung.
        self.assertEqual(self.event._kjr_age_check('2019-08-29'), 'too_young')

    def test_age_tolerance_max_age(self):
        """13. Geburtstag 25 Tage vor Beginn: ohne Kulanz zu alt, mit 42 Tagen ok."""
        self.assertEqual(self.event._kjr_age_check('2014-06-15'), 'too_old')
        self.event.kjr_age_tolerance_days = 42
        self.assertIsNone(self.event._kjr_age_check('2014-06-15'))

    def test_age_tolerance_flag_and_constraint(self):
        reg = self.Registration.create({'event_id': self.event.id, 'name': 'Tim',
                                        'birthdate': '2019-08-01'})
        self.assertTrue(reg.age_out_of_range)
        self.event.kjr_age_tolerance_days = 42
        self.assertFalse(reg.age_out_of_range)
        self.event.write({'kjr_age_tolerance_days': 0, 'kjr_enforce_age_range': True})
        with self.assertRaises(ValidationError):
            self.Registration.create({'event_id': self.event.id, 'name': 'Tom',
                                      'birthdate': '2019-08-01'})
        self.event.kjr_age_tolerance_days = 42
        self.Registration.create({'event_id': self.event.id, 'name': 'Tom',
                                  'birthdate': '2019-08-01'})

    def test_form_rejects_age_when_enforced(self):
        self.event.kjr_enforce_age_range = True
        post = self._post(**{'1-birthdate': '2019-08-01'})
        self.assertEqual(self._ctl('_kjr_form_precheck', self.event, post),
                         'kjr_age_out_of_range')
        self.event.kjr_age_tolerance_days = 42
        self.assertIsNone(self._ctl('_kjr_form_precheck', self.event, post))

    # ------------------------------------------------------------------
    # Punkt 4: Postleitzahlen
    # ------------------------------------------------------------------
    def test_zip_unrestricted_by_default(self):
        self.assertTrue(self.event._kjr_zip_allowed('80331'))

    def test_zip_default_list_plus_event_list(self):
        self.event.write({'kjr_zip_restricted': True, 'kjr_zip_extra': '88161\n88167'})
        self.assertTrue(self.event._kjr_zip_allowed('87527'))
        self.assertTrue(self.event._kjr_zip_allowed(' 88167 '))
        self.assertFalse(self.event._kjr_zip_allowed('80331'))
        post = self._post(**{'1-kjr_zip': '80331'})
        self.assertEqual(self._ctl('_kjr_form_precheck', self.event, post),
                         'kjr_zip_not_allowed')

    def test_zip_restricted_but_empty_lists(self):
        self.env['ir.config_parameter'].sudo().set_param('kjr_event.allowed_zips', '')
        self.event.kjr_zip_restricted = True
        self.assertTrue(self.event._kjr_zip_allowed('80331'))

    # ------------------------------------------------------------------
    # Punkt 5: Anmeldung ab
    # ------------------------------------------------------------------
    def test_registration_start_in_future(self):
        start = fields.Datetime.now() + timedelta(days=10)
        self.event.kjr_registration_start = start
        self.assertEqual(self.event.start_sale_datetime, start)
        self.assertFalse(self.event.event_registrations_started)
        self.assertFalse(self.event.event_registrations_open)
        self.assertEqual(self._ctl('_kjr_form_precheck', self.event, self._post()),
                         'kjr_registration_not_started')

    def test_registration_start_in_past(self):
        self.event.kjr_registration_start = fields.Datetime.now() - timedelta(days=1)
        self.assertTrue(self.event.event_registrations_started)
        self.assertIsNone(self._ctl('_kjr_form_precheck', self.event, self._post()))

    # ------------------------------------------------------------------
    # Punkt 1: Anmeldeformular
    # ------------------------------------------------------------------
    def test_form_complete_minor(self):
        self.assertIsNone(self._ctl('_kjr_form_precheck', self.event, self._post()))

    def test_form_confirmations_required(self):
        for key in ('kjr_privacy_accepted', 'kjr_terms_accepted', 'kjr_data_confirmed'):
            self.assertEqual(
                self._ctl('_kjr_form_precheck', self.event, self._post(**{key: None})),
                'kjr_confirmations_missing', key)

    def test_form_required_participant_fields(self):
        for key in ('1-kjr_street', '1-kjr_zip', '1-kjr_city', '1-kjr_medical_note',
                    '1-emergency_contact', '1-kjr_emergency_phone', '1-kjr_gender'):
            self.assertEqual(
                self._ctl('_kjr_form_precheck', self.event, self._post(**{key: ''})),
                'kjr_required_missing', key)
        self.assertEqual(
            self._ctl('_kjr_form_precheck', self.event, self._post(**{'1-birthdate': ''})),
            'kjr_birthdate_missing')

    def test_form_guardian_required_for_minor(self):
        for key in ('1-guardian_name', '1-guardian_email', '1-guardian_phone'):
            self.assertEqual(
                self._ctl('_kjr_form_precheck', self.event, self._post(**{key: ''})),
                'kjr_guardian_missing', key)
        # Abweichende Anschrift: dann Pflicht.
        post = self._post(**{'1-guardian_same_address': None})
        self.assertEqual(self._ctl('_kjr_form_precheck', self.event, post),
                         'kjr_guardian_missing')
        post.update({'1-guardian_street': 'Weg 2', '1-guardian_zip': '87509',
                     '1-guardian_city': 'Immenstadt'})
        self.assertIsNone(self._ctl('_kjr_form_precheck', self.event, post))

    def test_form_adult_needs_own_contact(self):
        self.event.write({'kjr_min_age': 0, 'kjr_max_age': 0})
        post = self._post(**{'1-birthdate': '2000-01-01', '1-guardian_name': None,
                             '1-guardian_email': None, '1-guardian_phone': None})
        self.assertEqual(self._ctl('_kjr_form_precheck', self.event, post),
                         'kjr_contact_missing')
        post.update({'1-kjr_participant_email': 'mia@example.com',
                     '1-kjr_participant_phone': '0170 1'})
        self.assertIsNone(self._ctl('_kjr_form_precheck', self.event, post))
        mapped = self._ctl('_kjr_prepare_contact_post', self.event, dict(post))
        self.assertEqual(mapped['1-email'], 'mia@example.com')
        self.assertEqual(mapped['1-phone'], '0170 1')

    def test_contact_mapping_minor_uses_guardian(self):
        mapped = self._ctl('_kjr_prepare_contact_post', self.event, self._post())
        self.assertEqual(mapped['1-email'], 'eva@example.com')
        self.assertEqual(mapped['1-phone'], '0831 123')

    def test_extract_values_confirmations_and_consent(self):
        values = dict(self._ctl('_kjr_extract_attendee_values', self._post()))[1]
        self.assertTrue(values['kjr_terms_accepted'])
        self.assertTrue(values['kjr_privacy_accepted'])
        self.assertTrue(values['kjr_data_confirmed'])
        self.assertTrue(values['parental_consent'])
        self.assertTrue(values['guardian_same_address'])
        self.assertNotIn('guardian_street', values)
        self.assertEqual(values['kjr_medical_note'], 'keine')

    def test_extract_values_adult_drops_guardian(self):
        self.event.write({'kjr_min_age': 0, 'kjr_max_age': 0})
        post = self._post(**{'1-birthdate': '2000-01-01'})
        values = self._ctl('_kjr_drop_adult_guardian_values', self.event,
                           self._ctl('_kjr_extract_attendee_values', post))
        self.assertNotIn('guardian_name', dict(values)[1])

    def test_event_page_questions_are_optional(self):
        """Eigene Fragen sind im Formular nie Pflicht (Theresa 14.10.)."""
        question = self.env['event.question'].create({
            'title': 'Testfrage', 'question_type': 'text_box', 'is_mandatory_answer': True})
        html = str(self.env['ir.qweb']._render('website_event.registration_event_question', {
            'question': question, 'registration_index': 1, 'counter': 1,
            'default_first_attendee': {}, 'input_type_by_question_type': {}}))
        self.assertNotIn('required', html)

    # ------------------------------------------------------------------
    # Punkt 2: Rechnungs-/Kontaktpartner
    # ------------------------------------------------------------------
    def _reg(self, **vals):
        base = {'event_id': self.event.id, 'name': 'Mia Muster', 'birthdate': '2017-03-01',
                'kjr_street': 'Bahnhofstraße 1', 'kjr_zip': '87527', 'kjr_city': 'Sonthofen',
                'guardian_name': 'Eva Muster', 'guardian_email': 'eva@example.com',
                'guardian_phone': '0831 123', 'guardian_same_address': True,
                'email': 'eva@example.com'}
        base.update(vals)
        return self.Registration.sudo().create(base)

    def test_invoice_partner_minor_is_guardian_with_address(self):
        reg = self._reg()
        reg._kjr_apply_invoice_partner()
        partner = reg.kjr_invoice_partner_id
        self.assertEqual(partner.name, 'Eva Muster')
        self.assertEqual((partner.street, partner.zip, partner.city),
                         ('Bahnhofstraße 1', '87527', 'Sonthofen'))
        self.assertEqual(partner.email, 'eva@example.com')
        self.assertEqual(reg.partner_id, partner)

    def test_invoice_partner_minor_other_address(self):
        reg = self._reg(guardian_same_address=False, guardian_street='Weg 2',
                        guardian_zip='87509', guardian_city='Immenstadt')
        reg._kjr_apply_invoice_partner()
        self.assertEqual(reg.kjr_invoice_partner_id.city, 'Immenstadt')

    def test_invoice_partner_adult_is_participant(self):
        self.event.write({'kjr_min_age': 0, 'kjr_max_age': 0})
        reg = self._reg(birthdate='2000-01-01', email='mia@example.com',
                        guardian_name=False, guardian_email=False)
        reg._kjr_apply_invoice_partner()
        self.assertEqual(reg.kjr_invoice_partner_id.name, 'Mia Muster')
        self.assertEqual(reg.kjr_invoice_partner_id.email, 'mia@example.com')

    def test_invoice_partner_reused_only_on_full_match(self):
        first = self._reg()
        first._kjr_apply_invoice_partner()
        second = self._reg(name='Max Muster')
        second._kjr_apply_invoice_partner()
        self.assertEqual(first.kjr_invoice_partner_id, second.kjr_invoice_partner_id)
        third = self._reg(kjr_street='Andere Straße 5')
        third._kjr_apply_invoice_partner()
        self.assertNotEqual(first.kjr_invoice_partner_id, third.kjr_invoice_partner_id)

    def test_invoice_partner_needs_address(self):
        reg = self._reg(kjr_street=False)
        reg._kjr_apply_invoice_partner()
        self.assertFalse(reg.kjr_invoice_partner_id)

    def test_training_invoice_uses_invoice_partner_and_fee_tax(self):
        product = self.env['product.product'].create({
            'name': 'Teilnahmegebühr T1013', 'type': 'service', 'list_price': 50.0})
        tax = self.env['account.tax'].create({
            'name': '0 % Teilnahmegebühr T1013', 'amount': 0.0, 'type_tax_use': 'sale'})
        self.env['ir.config_parameter'].sudo().set_param('kjr_event.fee_tax_id', str(tax.id))
        self.event.write({'payment_required': True, 'training_product_id': product.id})
        reg = self._reg()
        reg._kjr_apply_invoice_partner()
        reg.action_create_training_invoice()
        move = reg.kjr_training_invoice_id
        self.assertEqual(move.partner_id, reg.kjr_invoice_partner_id)
        self.assertEqual(move.invoice_line_ids.tax_ids, tax)

    # ------------------------------------------------------------------
    # Punkt 8: Einordnung
    # ------------------------------------------------------------------
    def test_event_types(self):
        keys = [k for k, _l in self.Event._fields['kjr_event_type'].selection]
        self.assertEqual(keys, ['ferienprogramm', 'training'])
