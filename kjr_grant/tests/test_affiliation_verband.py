# -*- coding: utf-8 -*-
"""Tests: Dachverband und Delegierte bei der Vereinsregistrierung (19.0.17.0.0).

B45: Bei der Registrierung wählt eine Gruppe zusätzlich ihren Dachverband; der
Genehmigungsassistent legt eine neue Gruppe als Kind des Dachverbands an, mit
eigener Anschrift (Ansprechpersonen pflegt bis zur Mitgliedschaft die
Geschäftsstelle; „Mein Verband“ im Portal nur für Mitgliedsverbände).
B46: Ankreuzfeld „Ich bin Delegierte/r“; in die Delegiertenliste des Verbands
kommt die Person erst mit der Genehmigung.
B48: Telefon ist für Delegierte Pflicht (Registrierung, Genehmigung, Portal).
"""
import re
from unittest.mock import patch

from odoo import http
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import HttpCase, TransactionCase, new_test_user

PASSWORD = 'KjrTest-2026!x'


@tagged('post_install', '-at_install')
class TestKjrAffiliationVerband(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        website = cls.env['website'].get_current_website()
        website.auth_signup_uninvited = 'b2c'
        website.company_id.email = 'geschaeftsstelle@example.com'
        cls.env.company.email = 'geschaeftsstelle@example.com'
        cls.Partner = cls.env['res.partner']
        cls.Request = cls.env['kjr.affiliation.request']
        cls.dachverband = cls.Partner.create({
            'name': 'Kreisjugendfeuerwehr Test',
            'is_company': True,
            'is_kjr_member': True,
            'kjr_vr_right': True,
            'street': 'Dachweg 1',
            'zip': '87527',
            'city': 'Sonthofen',
        })
        cls.verband_ohne_vr = cls.Partner.create({
            'name': 'Verband ohne Stimmrecht',
            'is_company': True,
            'is_kjr_member': True,
            'street': 'Weg 2',
            'zip': '87509',
            'city': 'Immenstadt',
        })
        cls.fremde_firma = cls.Partner.create({
            'name': 'Fremdfirma GmbH', 'is_company': True,
        })
        cls.reviewer = new_test_user(
            cls.env, login='kjr_sb_verband',
            groups='base.group_user,kjr_grant.group_kjr_reviewer')
        cls.public_user = cls.env.ref('base.public_user')

    def _signup(self, login, **affiliation):
        data = {'name': 'Feuerwehr Hindelang', 'function': 'Jugendwart', 'place': 'Hindelang'}
        data.update(affiliation)
        self.env['res.users'].with_user(self.public_user).sudo().signup({
            'login': login, 'name': 'Test Person', 'password': PASSWORD,
            'kjr_affiliation': data,
        })
        user = self.env['res.users'].sudo().search([('login', '=', login)])
        req = self.Request.search([('partner_id', '=', user.partner_id.id)])
        self.assertEqual(len(req), 1)
        return user, req

    def _wizard(self, req, **vals):
        vals['request_id'] = req.id
        return self.env['kjr.affiliation.approve.wizard'].with_user(self.reviewer).create(vals)

    # ── Registrierung ───────────────────────────────────────────────────────

    def test_registrierung_speichert_dachverband_delegiert_telefon(self):
        user, req = self._signup('dv1@example.com', parent_id=self.dachverband.id,
                                 delegate=True, phone='08321 1234-0')
        self.assertEqual(req.requested_parent_id, self.dachverband)
        self.assertTrue(req.requested_delegate)
        self.assertEqual(user.partner_id.phone, '08321 1234-0')
        # Vor der Genehmigung: keine Zuordnung und NICHT in der Delegiertenliste.
        self.assertFalse(user.partner_id.parent_id)
        self.assertNotIn(user.partner_id, self.dachverband.kjr_vr_delegate_ids)
        self.assertFalse(req.delegate_partner_id)

    def test_dachverband_nur_aus_auswahlliste(self):
        """Ein Nicht-Mitglied als „Dachverband“ fällt still weg."""
        _user, req = self._signup('dv2@example.com', parent_id=self.fremde_firma.id)
        self.assertFalse(req.requested_parent_id)

    # ── Genehmigung: neue Ortsgruppe unter dem Dachverband ──────────────────

    def test_neue_gruppe_als_kind_des_dachverbands(self):
        user, req = self._signup('dv3@example.com', parent_id=self.dachverband.id)
        wizard = self._wizard(req)
        self.assertEqual(wizard.mode, 'new', 'Mit Dachverband und ohne Treffer: neue Gruppe.')
        self.assertEqual(wizard.new_parent_id, self.dachverband)
        wizard.write({'new_street': 'Ortsweg 5', 'new_zip': '87541', 'new_city': 'Bad Hindelang'})
        wizard.action_confirm()
        gruppe = user.partner_id.parent_id
        self.assertTrue(gruppe.is_company)
        self.assertEqual(gruppe.parent_id, self.dachverband)
        self.assertEqual(gruppe.name, 'Feuerwehr Hindelang')
        # Eigene Anschrift, keine Übernahme vom und kein Schreiben in den Dachverband
        self.assertEqual(gruppe.street, 'Ortsweg 5')
        self.assertEqual(self.dachverband.street, 'Dachweg 1')
        self.assertEqual(self.dachverband.city, 'Sonthofen')
        # Eigene Ansprechpersonen: die Gruppe ist ihr eigener commercial partner
        self.assertEqual(gruppe.commercial_partner_id, gruppe)
        self.assertEqual(user.partner_id.commercial_partner_id, gruppe)
        self.assertFalse(gruppe.is_kjr_member)
        # Spätere Adressänderung des Dachverbands wandert nicht in die Gruppe
        self.dachverband.street = 'Neuer Dachweg 9'
        self.assertEqual(gruppe.street, 'Ortsweg 5')

    def test_vorschlag_bestehende_gruppe_unter_dachverband(self):
        gruppe = self.Partner.create({
            'name': 'Feuerwehr Hindelang', 'is_company': True, 'type': 'other',
            'parent_id': self.dachverband.id,
            'street': 'Ortsweg 5', 'zip': '87541', 'city': 'Bad Hindelang',
        })
        _user, req = self._signup('dv4@example.com', parent_id=self.dachverband.id)
        wizard = self._wizard(req)
        self.assertEqual(wizard.mode, 'existing')
        self.assertEqual(wizard.target_partner_id, gruppe)

    # ── Delegierte erst nach Genehmigung ────────────────────────────────────

    def test_delegierte_nach_genehmigung_aufgenommen(self):
        user, req = self._signup('dv5@example.com', parent_id=self.dachverband.id,
                                 delegate=True, phone='0831 555')
        wizard = self._wizard(req, new_street='Ortsweg 5', new_zip='87541',
                              new_city='Bad Hindelang')
        self.assertTrue(wizard.add_delegate)
        self.assertEqual(wizard.delegate_partner_id, self.dachverband,
                         'Vorschlag: nächster Verband mit Vertretungsrecht über der Gruppe.')
        wizard.action_confirm()
        self.assertIn(user.partner_id, self.dachverband.kjr_vr_delegate_ids)
        self.assertEqual(req.delegate_partner_id, self.dachverband)

    def test_delegiertenhinweis_nur_bei_gewaehlter_organisation(self):
        """Warnung „kein Vertretungsrecht“ nur, wenn das für die Auswahl stimmt."""
        _user, req = self._signup('dv10@example.com', name='Unbekannte Gruppe',
                                  delegate=True, phone='0831 555')
        wizard = self._wizard(req)
        self.assertEqual(wizard.mode, 'existing')
        self.assertFalse(wizard.target_partner_id)
        self.assertEqual(wizard.delegate_base_state, 'none')
        wizard.target_partner_id = self.verband_ohne_vr
        self.assertEqual(wizard.delegate_base_state, 'no_vr')
        self.assertFalse(wizard.delegate_partner_id)
        wizard.target_partner_id = self.dachverband
        self.assertEqual(wizard.delegate_base_state, 'ok')
        self.assertEqual(wizard.delegate_partner_id, self.dachverband)

    def test_ablehnung_ohne_delegiertenstatus(self):
        user, req = self._signup('dv6@example.com', parent_id=self.dachverband.id,
                                 delegate=True, phone='0831 555')
        self.env['kjr.affiliation.reject.wizard'].with_user(self.reviewer).create(
            {'request_id': req.id}).action_confirm()
        self.assertNotIn(user.partner_id, self.dachverband.kjr_vr_delegate_ids)

    def test_delegierte_ohne_telefon_nicht_genehmigt(self):
        """Backend-Antrag ohne Telefon: als Delegierte/r nicht genehmigbar."""
        person = self.Partner.create({'name': 'Ohne Telefon', 'email': 'ot@example.com'})
        req = self.Request.with_user(self.reviewer).create({
            'partner_id': person.id, 'requested_name': 'Kreisjugendfeuerwehr Test',
            'requested_delegate': True,
        })
        wizard = self._wizard(req, mode='existing', target_partner_id=self.dachverband.id)
        self.assertTrue(wizard.add_delegate)
        with self.assertRaises(UserError):
            wizard.action_confirm()
        self.assertEqual(req.state, 'requested')
        self.assertNotIn(person, self.dachverband.kjr_vr_delegate_ids)

    def test_telefon_im_assistenten_nachgetragen(self):
        """Sachbearbeiter ohne Kontaktrecht tragen das Pflicht-Telefon im Assistenten nach."""
        person = self.Partner.create({'name': 'Ohne Telefon 2', 'email': 'ot2@example.com'})
        req = self.Request.with_user(self.reviewer).create({
            'partner_id': person.id, 'requested_name': 'Kreisjugendfeuerwehr Test',
            'requested_delegate': True,
        })
        wizard = self._wizard(req, mode='existing', target_partner_id=self.dachverband.id,
                              new_phone='0831 777')
        wizard.action_confirm()
        self.assertEqual(req.state, 'approved')
        self.assertEqual(person.phone, '0831 777')
        self.assertIn(person, self.dachverband.kjr_vr_delegate_ids)

    def test_nachgetragenes_telefon_ueberschreibt_nichts(self):
        user, req = self._signup('dv11@example.com', delegate=True, phone='0831 555')
        req.with_user(self.reviewer)._kjr_do_approve(
            self.dachverband, notify=False, delegate_for=self.dachverband, phone='0831 999')
        self.assertEqual(user.partner_id.phone, '0831 555')

    def test_nachgetragenes_telefon_wird_geprueft(self):
        person = self.Partner.create({'name': 'Ohne Telefon 3', 'email': 'ot3@example.com'})
        req = self.Request.with_user(self.reviewer).create({
            'partner_id': person.id, 'requested_name': 'Kreisjugendfeuerwehr Test',
        })
        with self.assertRaises(UserError):
            req.with_user(self.reviewer)._kjr_do_approve(
                self.dachverband, notify=False, phone='keine Nummer')
        self.assertEqual(req.state, 'requested')

    def test_delegiert_nur_fuer_verband_mit_vertretungsrecht_darueber(self):
        user, req = self._signup('dv7@example.com', delegate=True, phone='0831 555')
        # Verband ohne Vertretungsrecht
        with self.assertRaises(UserError):
            req.with_user(self.reviewer)._kjr_do_approve(
                self.dachverband, notify=False, delegate_for=self.verband_ohne_vr)
        # Verband mit Vertretungsrecht, aber nicht über der zugeordneten Organisation
        with self.assertRaises(UserError):
            req.with_user(self.reviewer)._kjr_do_approve(
                self.verband_ohne_vr, notify=False, delegate_for=self.dachverband)
        self.assertEqual(req.state, 'requested')
        self.assertFalse(user.partner_id.parent_id)

    def test_delegiertenangabe_nach_entscheidung_gesperrt(self):
        _user, req = self._signup('dv8@example.com', delegate=True, phone='0831 555')
        self._wizard(req, mode='existing', target_partner_id=self.dachverband.id,
                     add_delegate=False).action_confirm()
        from odoo.exceptions import AccessError
        with self.assertRaises(AccessError):
            req.with_user(self.reviewer).write({'requested_delegate': False})
        with self.assertRaises(AccessError):
            req.with_user(self.reviewer).write({'delegate_partner_id': self.dachverband.id})

    def test_genehmigungsmail_nennt_delegiertenstatus(self):
        _user, req = self._signup('dv9@example.com', delegate=True, phone='0831 555')
        self._wizard(req, mode='existing', target_partner_id=self.dachverband.id).action_confirm()
        mail = self.env['mail.mail'].search([
            ('model', '=', 'kjr.affiliation.request'), ('res_id', '=', req.id)], limit=1)
        self.assertIn('als Delegierte/r', str(mail.body_html))

    def test_migration_ergaenzt_delegiertenabsatz(self):
        import importlib.util
        from odoo.tools.misc import file_path
        spec = importlib.util.spec_from_file_location(
            'kjr_grant_mig_verband', file_path('kjr_grant/migrations/19.0.17.0.0/post-verband.py'))
        mig = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mig)
        alt = '<div><p>Hallo</p><p>Mit freundlichen Grüßen<br/>X</p></div>'
        neu, geaendert = mig._ergaenze_delegiertenabsatz(alt)
        self.assertTrue(geaendert)
        self.assertIn('object.delegate_partner_id', neu)
        self.assertLess(neu.index('delegate_partner_id'), neu.index('Mit freundlichen Grüßen'))
        # idempotent
        self.assertEqual(mig._ergaenze_delegiertenabsatz(neu), (neu, False))
        # gepflegter Text ohne Grußzeile bleibt unangetastet
        self.assertEqual(mig._ergaenze_delegiertenabsatz('<p>Eigen</p>'), ('<p>Eigen</p>', False))


@tagged('post_install', '-at_install')
class TestKjrAffiliationVerbandHttp(HttpCase):
    """Registrierungsformular: Dachverband, Delegierten-Häkchen und Telefon."""

    def setUp(self):
        super().setUp()
        self.env.ref('website.default_website').auth_signup_uninvited = 'b2c'
        self.dachverband = self.env['res.partner'].create({
            'name': 'Kreisjugendfeuerwehr HTTP', 'is_company': True, 'is_kjr_member': True,
            'kjr_vr_right': True, 'street': 'Dachweg 1', 'zip': '87527', 'city': 'Sonthofen',
        })
        self.env.flush_all()
        self.authenticate(None, None)
        self.csrf_token = http.Request.csrf_token(self)
        patcher = patch.object(
            self.env.registry['ir.http'], '_verify_request_recaptcha_token',
            lambda self, action: True)
        self.startPatcher(patcher)

    def _post(self, login, **kjr):
        payload = {
            'login': login, 'name': 'Test Person', 'password': PASSWORD,
            'confirm_password': PASSWORD, 'csrf_token': self.csrf_token,
            'kjr_signup_type': 'club', 'kjr_club_name': 'Feuerwehr Hindelang',
        }
        payload.update(kjr)
        return self.url_open('/web/signup', data=payload)

    def _user(self, login):
        return self.env['res.users'].with_context(active_test=False).search(
            [('login', '=', login)])

    def test_formular_zeigt_dachverband_und_delegiertenfeld(self):
        text = self.url_open('/web/signup').text
        self.assertIn('name="kjr_club_parent_id"', text)
        self.assertIn('Kreisjugendfeuerwehr HTTP', text)
        self.assertIn('name="kjr_club_delegate"', text)
        self.assertIn('name="kjr_club_phone"', text)

    def test_delegierte_ohne_telefon_abgelehnt(self):
        login = 'http.dv.ohne@example.com'
        response = self._post(login, kjr_club_delegate='1', kjr_club_phone='')
        self.assertIn('Telefonnummer an', response.text)
        box = re.search(r'<input[^>]*id="kjr_club_delegate"[^>]*>', response.text)
        self.assertTrue(box and 'checked' in box.group(0))
        self.assertFalse(self._user(login))

    def test_delegierte_mit_telefon_und_dachverband(self):
        login = 'http.dv.ok@example.com'
        response = self._post(login, kjr_club_delegate='1', kjr_club_phone='08321 1234',
                              kjr_club_parent_id=str(self.dachverband.id))
        self.env.invalidate_all()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('/web/signup', response.url)
        user = self._user(login)
        req = self.env['kjr.affiliation.request'].search([('partner_id', '=', user.partner_id.id)])
        self.assertEqual(req.requested_parent_id, self.dachverband)
        self.assertTrue(req.requested_delegate)
        self.assertEqual(user.partner_id.phone, '08321 1234')
        self.assertNotIn(user.partner_id, self.dachverband.kjr_vr_delegate_ids)

    def test_ungueltiger_dachverband_abgelehnt(self):
        login = 'http.dv.falsch@example.com'
        fremd = self.env['res.partner'].create({'name': 'Fremd GmbH', 'is_company': True})
        self.env.flush_all()
        response = self._post(login, kjr_club_parent_id=str(fremd.id))
        self.assertIn('Dachverband aus der Liste', response.text)
        self.assertFalse(self._user(login))

    def test_portal_delegierte_ohne_telefon_abgelehnt(self):
        """Im Portal „Mein Verband“: Häkchen Delegierte/r verlangt Telefon."""
        verbandsperson = self.env['res.partner'].create({
            'name': 'Vorstand Portal', 'parent_id': self.dachverband.id,
            'email': 'vorstand.portal@example.com',
        })
        new_test_user(self.env, login='kjr_portal_dv', groups='base.group_portal',
                      partner_id=verbandsperson.id, password=PASSWORD,
                      name='Vorstand Portal', email='vorstand.portal@example.com')
        self.env.flush_all()
        self.authenticate('kjr_portal_dv', PASSWORD)
        csrf = http.Request.csrf_token(self)
        response = self.url_open('/my/verband', data={
            'csrf_token': csrf, 'action': 'contact_create',
            'contact_name': 'Neue Delegierte', 'contact_email': 'neu.dv@example.com',
            'contact_phone': '', 'contact_is_delegate': '1',
        })
        self.assertIn('für Delegierte Pflicht', response.text)
        self.env.invalidate_all()
        self.assertFalse(self.env['res.partner'].search([('name', '=', 'Neue Delegierte')]))
        response = self.url_open('/my/verband', data={
            'csrf_token': csrf, 'action': 'contact_create',
            'contact_name': 'Neue Delegierte', 'contact_email': 'neu.dv@example.com',
            'contact_phone': '0831 777', 'contact_is_delegate': '1',
        })
        self.env.invalidate_all()
        neu = self.env['res.partner'].search([('name', '=', 'Neue Delegierte')])
        self.assertTrue(neu)
        self.assertIn(neu, self.dachverband.kjr_vr_delegate_ids)

    def test_portal_kennzeichnet_delegierte_aus_ortsgruppe(self):
        """Delegierte/r aus einer Ortsgruppe: nicht unter „Ansprechpersonen“ pflegbar.

        Die Delegiertentabelle verlinkt keinen fehlenden Anker und verweist auf
        die Geschäftsstelle statt auf „oben bei der Person“.
        """
        verbandsperson = self.env['res.partner'].create({
            'name': 'Vorstand Dach', 'parent_id': self.dachverband.id,
            'email': 'vorstand.dach@example.com',
        })
        ortsgruppe = self.env['res.partner'].create({
            'name': 'Ortsgruppe Hindelang', 'is_company': True, 'type': 'other',
            'parent_id': self.dachverband.id, 'street': 'Ortsweg 2', 'zip': '87541',
            'city': 'Bad Hindelang',
        })
        fremd = self.env['res.partner'].create({
            'name': 'Delegierte Ortsgruppe', 'parent_id': ortsgruppe.id,
            'email': 'dv.ort@example.com',
        })
        self.dachverband.kjr_vr_delegate_ids = [(4, fremd.id)]
        new_test_user(self.env, login='kjr_portal_dach', groups='base.group_portal',
                      partner_id=verbandsperson.id, password=PASSWORD,
                      name='Vorstand Dach', email='vorstand.dach@example.com')
        self.env.flush_all()
        self.authenticate('kjr_portal_dach', PASSWORD)
        text = self.url_open('/my/verband').text
        self.assertIn('Delegierte Ortsgruppe', text)
        self.assertIn('gehört zu Ortsgruppe Hindelang', text)
        self.assertIn('Änderungen über die Geschäftsstelle', text)
        self.assertIn('fehlt, bitte der Geschäftsstelle melden', text)
        self.assertNotIn('#kontakt_%s"' % fremd.id, text)
