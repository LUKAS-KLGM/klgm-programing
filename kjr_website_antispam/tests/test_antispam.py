# -*- coding: utf-8 -*-
"""Tests des KJR-Spam-Schutzes (Honeypot und signiertes Zeittoken).

Ohne HTTP-Server: ``request`` wird per unittest.mock durch ein schlichtes
Objekt mit ``params``, ``httprequest`` und ``env`` ersetzt. Ersetzt wird es in
ALLEN Modulen der Hook-Kette, die ``request`` selbst importieren (dieses Modul,
google_recaptcha und, falls geladen, website_cf_turnstile), weil der Override
zuerst super() aufruft. Damit die Kette nie ins Netz geht, werden die
Captcha-Secrets im Test geleert (beide Module melden dann 'no_secret').
"""
import sys
import time
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.kjr_website_antispam.models import ir_http as antispam_ir_http

HOOK_MODULES = (
    'odoo.addons.kjr_website_antispam.models.ir_http',
    'odoo.addons.google_recaptcha.models.ir_http',
    'odoo.addons.website_cf_turnstile.models.ir_http',
)
LOGGER_NAME = antispam_ir_http.__name__


@tagged('post_install', '-at_install')
class TestKjrWebsiteAntispam(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.IrHttp = cls.env['ir.http']
        icp = cls.env['ir.config_parameter'].sudo()
        # Keine Netzaufrufe aus der Captcha-Kette (siehe Moduldocstring).
        icp.set_param('recaptcha_private_key', False)
        icp.set_param('cf.turnstile_secret_key', False)
        # Feste Werte statt der Seeds: die Seeds stehen unter noupdate und
        # dürfen auf einer Instanz gepflegt sein.
        icp.set_param('kjr_website_antispam.mode', 'enforce')
        icp.set_param('kjr_website_antispam.min_seconds', '3')
        icp.set_param('kjr_website_antispam.min_seconds_exempt', 'website_event_registration')
        icp.set_param('kjr_website_antispam.max_age_hours', '24')
        icp.set_param('kjr_website_antispam.actions',
                      'website_form,website_event_registration,kjr_*')

    # ------------------------------------------------------------------
    # Hilfen
    # ------------------------------------------------------------------
    @contextmanager
    def _request(self, params, method='POST'):
        fake = SimpleNamespace(
            env=self.env,
            params=params,
            httprequest=SimpleNamespace(method=method, remote_addr='127.0.0.1'),
        )
        with ExitStack() as stack:
            for name in HOOK_MODULES:
                module = sys.modules.get(name)
                if module is not None and hasattr(module, 'request'):
                    stack.enter_context(patch.object(module, 'request', fake))
            yield fake

    def _token(self, age_seconds):
        return self.IrHttp._kjr_antispam_token(timestamp=int(time.time()) - age_seconds)

    def _verify(self, action, params, method='POST'):
        with self._request(params, method=method):
            self.IrHttp._verify_request_recaptcha_token(action)
        return params

    def _set(self, key, value):
        self.env['ir.config_parameter'].sudo().set_param('kjr_website_antispam.%s' % key, value)

    # ------------------------------------------------------------------
    # Token
    # ------------------------------------------------------------------
    def test_token_format_and_age(self):
        token = self._token(10)
        ts, _sep, signature = token.partition('.')
        self.assertTrue(ts.isdigit())
        self.assertEqual(len(signature), 64, 'HMAC-SHA256 als Hex erwartet')
        age = self.IrHttp._kjr_antispam_token_age(token)
        self.assertIsNotNone(age)
        self.assertGreaterEqual(age, 10)
        self.assertLess(age, 70)

    def test_token_age_rejects_garbage(self):
        for value in (None, '', 'abc', '123', '123.', '.abc', '12a.ffff',
                      '+12.ffff', '1' * 200, '123.äöü'):
            self.assertIsNone(self.IrHttp._kjr_antispam_token_age(value), value)

    def test_valid_token_passes_and_params_are_removed(self):
        params = {'kjr_ts': self._token(10), 'kjr_hp': '', 'name': 'x'}
        self._verify('website_form', params)
        self.assertNotIn('kjr_ts', params)
        self.assertNotIn('kjr_hp', params)
        self.assertEqual(params, {'name': 'x'}, 'fremde Parameter bleiben unberührt')

    def test_token_too_young(self):
        with self.assertRaises(UserError):
            self._verify('website_form', {'kjr_ts': self._token(0)})

    def test_min_seconds_zero_allows_immediate_submit(self):
        self._set('min_seconds', '0')
        self._verify('website_form', {'kjr_ts': self._token(0)})

    def test_min_seconds_default(self):
        # Fehlt der Parameter, gilt der Standard von 2 s.
        self._set('min_seconds', False)
        self.assertEqual(self.IrHttp._kjr_antispam_min_seconds(), 2)
        self.assertEqual(self.IrHttp._kjr_antispam_min_seconds('website_form'), 2)

    def test_event_dialog_has_no_min_seconds(self):
        # Vorausgefüllter Teilnehmerdialog: sofortiges Absenden ist normal.
        self.assertEqual(
            self.IrHttp._kjr_antispam_min_seconds('website_event_registration'), 0)
        self._verify('website_event_registration', {'kjr_ts': self._token(0)})
        # Honeypot, Signatur und Höchstalter gelten weiter.
        with self.assertRaises(UserError):
            self._verify('website_event_registration',
                         {'kjr_ts': self._token(0), 'kjr_hp': 'x'})
        with self.assertRaises(UserError):
            self._verify('website_event_registration', {'kjr_ts': self._token(25 * 3600)})
        with self.assertRaises(UserError):
            self._verify('website_event_registration', {})
        # Andere Aktionen behalten die Mindestzeit.
        with self.assertRaises(UserError):
            self._verify('kjr_spielmobil', {'kjr_ts': self._token(0)})

    def test_min_seconds_exempt_can_be_lifted(self):
        # '-' passt auf keine Aktion: die Mindestzeit gilt dann überall.
        self._set('min_seconds_exempt', '-')
        with self.assertRaises(UserError):
            self._verify('website_event_registration', {'kjr_ts': self._token(0)})
        # Fehlender Parameter: Standardausnahme greift.
        self._set('min_seconds_exempt', False)
        self._verify('website_event_registration', {'kjr_ts': self._token(0)})

    def test_token_expired(self):
        with self.assertRaises(UserError):
            self._verify('website_form', {'kjr_ts': self._token(25 * 3600)})
        # Knapp unter der Grenze ist es noch gültig.
        self._verify('website_form', {'kjr_ts': self._token(23 * 3600)})

    def test_token_tampered(self):
        token = self._token(10)
        ts, _sep, signature = token.partition('.')
        flipped = ('0' if signature[0] != '0' else '1') + signature[1:]
        with self.assertRaises(UserError):
            self._verify('website_form', {'kjr_ts': '%s.%s' % (ts, flipped)})
        # Zeitstempel verändert, Signatur behalten.
        with self.assertRaises(UserError):
            self._verify('website_form', {'kjr_ts': '%d.%s' % (int(ts) - 60, signature)})

    def test_token_missing(self):
        with self.assertRaises(UserError):
            self._verify('website_event_registration', {})

    def test_honeypot_filled(self):
        params = {'kjr_ts': self._token(10), 'kjr_hp': 'https://spam.example'}
        with self.assertRaises(UserError):
            self._verify('website_form', params)
        self.assertNotIn('kjr_hp', params)

    # ------------------------------------------------------------------
    # Aktionen und Modus
    # ------------------------------------------------------------------
    def test_unlisted_action_is_not_checked(self):
        params = {'kjr_hp': 'gefüllt'}
        self._verify('signup', params)
        self.assertFalse(self.IrHttp._kjr_antispam_applies('signup'))
        # Auch ungeprüft werden die Felder entfernt.
        self.assertNotIn('kjr_hp', params)

    def test_fnmatch_kjr_spielmobil(self):
        with self._request({}):
            self.assertTrue(self.IrHttp._kjr_antispam_applies('kjr_spielmobil'))
            self.assertFalse(self.IrHttp._kjr_antispam_applies('spielmobil'))
        with self.assertRaises(UserError):
            self._verify('kjr_spielmobil', {})
        self._verify('kjr_spielmobil', {'kjr_ts': self._token(10)})

    def test_get_request_is_not_checked(self):
        with self._request({}, method='GET'):
            self.assertFalse(self.IrHttp._kjr_antispam_applies('website_form'))
        self._verify('website_form', {}, method='GET')

    def test_mode_log_does_not_raise(self):
        self._set('mode', 'log')
        params = {'kjr_hp': 'geheimer-wert-123'}
        with self.assertLogs(LOGGER_NAME, level='INFO') as logs:
            self._verify('website_form', params)
        output = '\n'.join(logs.output)
        self.assertIn('honeypot', output)
        self.assertIn('website_form', output)
        # Datenschutz: keine Formularwerte und keine IP im Log.
        self.assertNotIn('geheimer-wert-123', output)
        self.assertNotIn('127.0.0.1', output)
        self.assertNotIn('kjr_hp', params)

    def test_mode_off_does_not_check(self):
        self._set('mode', 'off')
        with self._request({}):
            self.assertFalse(self.IrHttp._kjr_antispam_applies('website_form'))
        params = {'kjr_hp': 'x'}
        self._verify('website_form', params)
        self.assertNotIn('kjr_hp', params)

    def test_unknown_mode_falls_back_to_enforce(self):
        self._set('mode', 'irgendwas')
        self.assertEqual(self.IrHttp._kjr_antispam_mode(), 'enforce')
        with self.assertRaises(UserError):
            self._verify('website_form', {})

    def test_precheck_has_no_side_effects(self):
        # Vorabprüfung für äußere Controller: Grund nur im Modus enforce,
        # Parameter bleiben erhalten, kein Log.
        params = {'kjr_ts': self._token(0), 'kjr_hp': ''}
        with self._request(params):
            self.assertEqual(
                self.IrHttp._kjr_antispam_precheck('website_form'), 'too_fast')
            # Teilnehmerdialog: keine Mindestzeit (min_seconds_exempt).
            self.assertIsNone(
                self.IrHttp._kjr_antispam_precheck('website_event_registration'))
        self.assertIn('kjr_ts', params)
        self.assertIn('kjr_hp', params)
        params = {'kjr_ts': self._token(10), 'kjr_hp': 'x'}
        with self._request(params):
            self.assertEqual(
                self.IrHttp._kjr_antispam_precheck('website_event_registration'), 'honeypot')
        self.assertIn('kjr_hp', params)
        with self._request({'kjr_ts': self._token(10)}):
            self.assertIsNone(self.IrHttp._kjr_antispam_precheck('website_event_registration'))
        with self._request({}):
            self.assertIsNone(self.IrHttp._kjr_antispam_precheck('signup'))
        self._set('mode', 'log')
        with self._request({}):
            self.assertIsNone(self.IrHttp._kjr_antispam_precheck('website_event_registration'))
        with self._request({}, method='GET'):
            self.assertIsNone(self.IrHttp._kjr_antispam_precheck('website_event_registration'))

    def test_no_request_is_not_checked(self):
        # Ohne gebundenen Request (Cron, Shell) greift der Schutz nie.
        self.assertFalse(self.IrHttp._kjr_antispam_applies('website_form'))

    # ------------------------------------------------------------------
    # Ansichten
    # ------------------------------------------------------------------
    def test_views_are_applied(self):
        attendee = self.env.ref('website_event.registration_attendee_details')
        self.assertIn('kjr_website_antispam.fields', attendee.get_combined_arch())
        registration = self.env.ref('website_event.registration_template')
        arch = registration.get_combined_arch()
        self.assertIn('Die Anmeldung konnte nicht verarbeitet werden', arch)
        # Kein Neuladen verlangen: die URL behält den Fehlercode, die Meldung
        # erschiene nach dem Neuladen erneut.
        self.assertIn('Tickets erneut aus', arch)
        self.assertNotIn('Seite neu', arch)
        self.assertNotIn('Suspicious activity detected by Google reCaptcha', arch)
        self.assertIn("registration_error_code == 'recaptcha_failed'", arch)
