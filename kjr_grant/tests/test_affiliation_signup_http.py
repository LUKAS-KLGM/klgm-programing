# -*- coding: utf-8 -*-
"""HTTP-Tests des Registrierungsformulars (/web/signup) mit Vereinsangaben.

Formularprüfung und Neubefüllung des Formulars nach einem Fehler lassen sich nur
über HTTP prüfen: beides hängt an KjrAuthSignupHome (controllers/signup.py) und
am qcontext von auth_signup. Muster: auth_signup/tests/test_auth_signup.py.
Die Captcha-Kette (reCAPTCHA, Turnstile, kjr_website_antispam) wird
ausgeschaltet; die Registrierung ist im Spam-Schutz ohnehin ausgenommen.
"""
import re
from unittest.mock import patch

from odoo import http
from odoo.tests import tagged
from odoo.tests.common import HttpCase

PASSWORD = 'KjrTest-2026!x'


@tagged('post_install', '-at_install')
class TestKjrAffiliationSignupHttp(HttpCase):

    def setUp(self):
        super().setUp()
        self.env.ref('website.default_website').auth_signup_uninvited = 'b2c'
        self.authenticate(None, None)
        self.csrf_token = http.Request.csrf_token(self)
        patcher = patch.object(
            self.env.registry['ir.http'], '_verify_request_recaptcha_token',
            lambda self, action: True)
        self.startPatcher(patcher)

    def _post(self, login, **kjr):
        payload = {
            'login': login,
            'name': 'Test Person',
            'password': PASSWORD,
            'confirm_password': PASSWORD,
            'csrf_token': self.csrf_token,
        }
        payload.update(kjr)
        return self.url_open('/web/signup', data=payload)

    def _assert_signup_ok(self, response):
        """Erfolg = kein erneutes Formular. Nach dem Signup ruft auth_signup
        web_login auf; mit portal/website leitet Odoo Portalnutzer nach /my
        (website/controllers/main.py, portal/controllers/web.py), nicht nach
        /web/login_successful."""
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('/web/signup', response.url)

    def _user(self, login):
        return self.env['res.users'].with_context(active_test=False).search(
            [('login', '=', login)])

    def test_verein_ohne_namen_zeigt_fehler(self):
        login = 'http.verein.leer@example.com'
        response = self._post(login, kjr_signup_type='club', kjr_club_name='')
        self.assertIn('Bitte geben Sie den Namen', response.text)
        radio = re.search(r'<input[^>]*id="kjr_signup_club"[^>]*>', response.text)
        self.assertTrue(radio, 'Die Wahl "für einen Verein" fehlt im Formular.')
        self.assertIn('checked', radio.group(0))
        self.assertFalse(self._user(login))

    def test_verein_mit_namen_legt_antrag_an(self):
        login = 'http.verein@example.com'
        response = self._post(login, kjr_signup_type='club',
                              kjr_club_name='Schützenverein Musterdorf',
                              kjr_club_function='Kassier')
        self._assert_signup_ok(response)
        user = self._user(login)
        self.assertTrue(user)
        self.assertFalse(user.partner_id.parent_id)
        req = self.env['kjr.affiliation.request'].search(
            [('partner_id', '=', user.partner_id.id)])
        self.assertEqual(req.state, 'requested')
        self.assertEqual(req.requested_name, 'Schützenverein Musterdorf')
        # Der Signup läuft hier wirklich als Public-User (auth_signup-Controller):
        # Antrag, Follower und Notizen dürfen ihm nicht zugeordnet sein.
        public_user = self.env.ref('base.public_user')
        self.assertNotEqual(req.create_uid, public_user)
        self.assertNotIn(public_user.partner_id, req.message_partner_ids)
        self.assertFalse(req.message_ids.filtered(
            lambda m: m.author_id == public_user.partner_id))

    def test_verein_kurzname_erlaubt(self):
        """Abkürzungen wie „SV“ sind gültige Vereinsnamen."""
        login = 'http.verein.sv@example.com'
        response = self._post(login, kjr_signup_type='club', kjr_club_name='SV')
        self._assert_signup_ok(response)
        req = self.env['kjr.affiliation.request'].search(
            [('partner_id', '=', self._user(login).partner_id.id)])
        self.assertEqual(req.requested_name, 'SV')

    def test_verein_ein_zeichen_eigene_meldung(self):
        """Ein einzelnes Zeichen: eigene Meldung, nicht „bitte angeben“."""
        login = 'http.verein.x@example.com'
        response = self._post(login, kjr_signup_type='club', kjr_club_name='X')
        self.assertIn('vollständigen Namen', response.text)
        self.assertNotIn('Bitte geben Sie den Namen', response.text)
        self.assertFalse(self._user(login))

    def test_privatperson_wie_bisher(self):
        login = 'http.privat@example.com'
        response = self._post(login, kjr_signup_type='private')
        self._assert_signup_ok(response)
        user = self._user(login)
        self.assertTrue(user)
        self.assertFalse(self.env['kjr.affiliation.request'].search(
            [('partner_id', '=', user.partner_id.id)]))

    def test_falsche_auswahl_abgelehnt(self):
        login = 'http.foo@example.com'
        response = self._post(login, kjr_signup_type='foo')
        self.assertIn('Bitte wählen Sie, ob Sie sich als Privatperson', response.text)
        self.assertFalse(self._user(login))

    def test_datenschutzhinweis_loeschfrist(self):
        """Der Hinweis nennt dieselbe Frist, die der Lösch-Cron anwendet."""
        Param = self.env['ir.config_parameter'].sudo()
        Param.set_param('kjr_grant.affiliation_rejected_retention_days', '90')
        text = self.url_open('/web/signup').text
        self.assertIn('Bei Ablehnung nach 90 Tagen', text)
        # Zweckerweiterung und Empfänger bei Genehmigung (Funktion in den Stammdaten)
        self.assertIn('in Ihre Kontaktdaten übernommen', text)
        self.assertIn('die anderen Zugänge Ihres Verbands', text)
        # Sichtbarkeit für den Dachverband und Verbleib des Telefons offengelegt
        self.assertIn('auch die Portal-Zugänge dieses', text)
        self.assertIn('Die Telefonnummer steht in Ihren Kontaktdaten und bleibt dort', text)

        Param.set_param('kjr_grant.affiliation_rejected_retention_days', '0')
        text = self.url_open('/web/signup').text
        self.assertNotIn('nach 0 Tagen', text)
        self.assertIn('aufbewahrt, bis die Geschäftsstelle sie löscht', text)

        Param.set_param('kjr_grant.affiliation_rejected_retention_days', 'abc')
        self.assertIn('Bei Ablehnung nach 180 Tagen', self.url_open('/web/signup').text)
