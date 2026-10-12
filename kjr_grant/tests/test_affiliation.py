# -*- coding: utf-8 -*-
"""Tests der Vereinsregistrierung (seit 19.0.16.0.0).

Bei der Registrierung wählt man „als Privatperson“ oder „für einen Verein /
Verband“. Ein Vereinskonto ist sofort nutzbar, wird aber erst durch die
Genehmigung der Geschäftsstelle dem Verband zugeordnet (parent_id). Alle
Vereinsrechte hängen am commercial partner (is_kjr_member bzw. Mitgliedsverband
im Teilbaum, res.partner._kjr_grants_member_rights); geprüft wird
deshalb vor allem, dass VOR der Genehmigung keine Zuordnung entsteht, dass nur
die Geschäftsstelle entscheidet und dass Signup-Token unter einem
Mitgliedsverband kein Konto mehr ohne Freigabe erzeugen (Lücke G1).
"""
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from psycopg2 import IntegrityError

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user
from odoo.tools import mute_logger

from odoo.addons.kjr_grant import hooks
from odoo.addons.kjr_grant.models.kjr_affiliation_request import ACTIVITY_SUMMARY

PASSWORD = 'KjrTest-2026!x'


@tagged('post_install', '-at_install')
class TestKjrAffiliation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        website = cls.env['website'].get_current_website()
        website.auth_signup_uninvited = 'b2c'
        # Absender der Mails (email_from aus company_id.email)
        website.company_id.email = 'geschaeftsstelle@example.com'
        cls.env.company.email = 'geschaeftsstelle@example.com'
        cls.Partner = cls.env['res.partner']
        cls.Request = cls.env['kjr.affiliation.request']
        cls.verband = cls.Partner.create({
            'name': 'Testverband',
            'is_company': True,
            'is_kjr_member': True,
            'street': 'Hauptstraße 1',
            'zip': '87527',
            'city': 'Sonthofen',
        })
        cls.reviewer = new_test_user(
            cls.env, login='kjr_sb',
            groups='base.group_user,kjr_grant.group_kjr_reviewer')
        cls.public_user = cls.env.ref('base.public_user')

    # ── Helfer ──────────────────────────────────────────────────────────────

    def _signup(self, login, affiliation=None):
        vals = {'login': login, 'name': 'Test Person', 'password': PASSWORD}
        if affiliation:
            vals['kjr_affiliation'] = affiliation
        # Wie im Controller: Public-User mit sudo (sudo behält die uid). Nur so
        # ist die Zuordnung von create_uid, Followern und Notizen echt geprüft.
        self.env['res.users'].with_user(self.public_user).sudo().signup(vals)
        return self.env['res.users'].sudo().search([('login', '=', login)])

    def _signup_club(self, login, name='Skiclub Musterdorf', function='Jugendleitung',
                     place='Musterdorf'):
        user = self._signup(login, {'name': name, 'function': function, 'place': place})
        req = self.Request.search([('partner_id', '=', user.partner_id.id)])
        self.assertEqual(len(req), 1)
        return user, req

    def _mails(self, req):
        return self.env['mail.mail'].search([
            ('model', '=', 'kjr.affiliation.request'), ('res_id', '=', req.id)])

    def _token(self, partner):
        partner.sudo().signup_prepare()
        return partner.sudo()._generate_signup_token()

    # ── Registrierung ───────────────────────────────────────────────────────

    def test_privatperson_ohne_antrag(self):
        """Privatperson: Konto wie bisher, kein Antrag, keine Zuordnung."""
        user = self._signup('privat@example.com')
        self.assertTrue(user)
        self.assertFalse(self.Request.search([('partner_id', '=', user.partner_id.id)]))
        self.assertFalse(user.partner_id.parent_id)

    def test_verein_legt_beantragten_antrag_an(self):
        """Verein: Antrag „beantragt“ aus der Registrierung, Person bleibt ihr
        eigener commercial partner, Aktivität für die Geschäftsstelle."""
        user, req = self._signup_club('verein1@example.com')
        partner = user.partner_id
        self.assertEqual(req.state, 'requested')
        self.assertEqual(req.origin, 'signup')
        self.assertEqual(req.user_id, user)
        self.assertEqual(req.requested_name, 'Skiclub Musterdorf')
        self.assertEqual(req.requested_function, 'Jugendleitung')
        self.assertEqual(req.requested_place, 'Musterdorf')
        self.assertEqual(partner.commercial_partner_id, partner)
        activity = req.activity_ids
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity.summary, ACTIVITY_SUMMARY)
        self.assertTrue(activity.user_id)
        self.assertNotEqual(req.create_uid, self.public_user)
        self.assertNotIn(self.public_user.partner_id, req.message_partner_ids)

    def test_keine_rechte_vor_genehmigung(self):
        """Vor der Genehmigung kein Mitgliedsverband in der Rechtekette."""
        user, _req = self._signup_club('verein2@example.com')
        self.assertFalse(user.partner_id.commercial_partner_id.is_kjr_member)
        self.assertFalse(user.partner_id._kjr_grants_member_rights())

    # ── Entscheidungen ──────────────────────────────────────────────────────

    def test_genehmigung_setzt_verband(self):
        user, req = self._signup_club('verein3@example.com')
        wizard = self.env['kjr.affiliation.approve.wizard'].with_user(self.reviewer).create({
            'request_id': req.id, 'mode': 'existing', 'target_partner_id': self.verband.id,
        })
        wizard.action_confirm()
        partner = user.partner_id
        self.assertEqual(partner.parent_id, self.verband)
        self.assertTrue(partner.commercial_partner_id.is_kjr_member)
        self.assertEqual(req.state, 'approved')
        self.assertEqual(req.target_partner_id, self.verband)
        self.assertEqual(req.decided_by_id, self.reviewer)
        self.assertTrue(req.date_decided)
        self.assertTrue(self._mails(req), 'Die Person muss eine Mail erhalten.')
        self.assertFalse(req.activity_ids, 'Die Aktivität muss erledigt sein.')
        # Funktion aus der Registrierung übernommen, weil am Kontakt leer
        self.assertEqual(partner.function, 'Jugendleitung')

    def test_genehmigung_vorschlag_exakter_treffer(self):
        """Der Assistent schlägt einen Mitgliedsverband mit genau diesem Namen vor."""
        _user, req = self._signup_club('verein3b@example.com', name='testverband')
        wizard = self.env['kjr.affiliation.approve.wizard'].with_user(self.reviewer).create({
            'request_id': req.id})
        self.assertEqual(wizard.target_partner_id, self.verband)

    def test_genehmigung_neue_organisation(self):
        user, req = self._signup_club('verein4@example.com')
        wizard = self.env['kjr.affiliation.approve.wizard'].with_user(self.reviewer).create({
            'request_id': req.id, 'mode': 'new', 'new_name': 'Neuer Verein e.V.',
            'new_street': 'Vereinsweg 2', 'new_zip': '87509', 'new_city': 'Immenstadt',
        })
        wizard.action_confirm()
        org = user.partner_id.parent_id
        self.assertTrue(org)
        self.assertTrue(org.is_company)
        self.assertFalse(org.is_kjr_member)
        self.assertEqual(org.name, 'Neuer Verein e.V.')
        self.assertEqual(req.state, 'approved')

    def test_ablehnung_mit_grund(self):
        user, req = self._signup_club('verein5@example.com')
        wizard = self.env['kjr.affiliation.reject.wizard'].with_user(self.reviewer).create({
            'request_id': req.id, 'reason': 'Bitte über den Vorstand melden.'})
        wizard.action_confirm()
        self.assertEqual(req.state, 'rejected')
        self.assertEqual(req.rejection_reason, 'Bitte über den Vorstand melden.')
        self.assertFalse(user.partner_id.parent_id)
        self.assertTrue(self._mails(req))
        self.assertTrue(user.active, 'Das Konto bleibt als persönliches Konto bestehen.')

    def test_nur_geschaeftsstelle_entscheidet(self):
        _user, req = self._signup_club('verein6@example.com')
        intern = new_test_user(self.env, login='kjr_intern', groups='base.group_user')
        with self.assertRaises(AccessError):
            req.with_user(intern)._kjr_do_approve(self.verband)
        portal = new_test_user(self.env, login='kjr_portal_x', groups='base.group_portal')
        with self.assertRaises(AccessError):
            self.env['kjr.affiliation.request'].with_user(portal).search([])
        self.assertEqual(req.state, 'requested')

    def test_status_nicht_frei_schreibbar(self):
        _user, req = self._signup_club('verein7@example.com')
        with self.assertRaises(AccessError):
            req.with_user(self.reviewer).write({'state': 'approved'})
        with self.assertRaises(AccessError):
            req.with_user(self.reviewer).write({'target_partner_id': self.verband.id})
        with self.assertRaises(AccessError):
            req.with_user(self.reviewer).write({'rejection_reason': 'frei geschrieben'})

    def test_angaben_bis_zur_entscheidung_aenderbar(self):
        _user, req = self._signup_club('verein_angaben@example.com')
        req.with_user(self.reviewer).write({'requested_name': 'Skiclub Musterdorf e.V.'})
        self.assertEqual(req.requested_name, 'Skiclub Musterdorf e.V.')
        req.with_user(self.reviewer)._kjr_do_reject('Unbekannter Verein')
        for vals in ({'requested_name': 'Anderer Verein'},
                     {'requested_function': 'Kassier'},
                     {'requested_place': 'Anderswo'},
                     {'company_id': req.company_id.id},
                     {'rejection_reason': 'Nachträglich geändert'}):
            with self.assertRaises(AccessError):
                req.with_user(self.reviewer).write(vals)
        self.assertEqual(req.requested_name, 'Skiclub Musterdorf e.V.')
        self.assertEqual(req.rejection_reason, 'Unbekannter Verein')

    def test_registrierungen_nur_fuer_sachbearbeiter_sichtbar(self):
        intern = new_test_user(self.env, login='kjr_intern_felder', groups='base.group_user')
        self.assertNotIn('kjr_affiliation_request_ids',
                         self.Partner.with_user(intern).fields_get())
        self.assertIn('kjr_affiliation_request_ids',
                      self.Partner.with_user(self.reviewer).fields_get())

    def test_adressschutz_organisation_ohne_anschrift(self):
        user, req = self._signup_club('verein8@example.com')
        partner = user.partner_id
        partner.write({'street': 'Privatweg 5', 'zip': '87509', 'city': 'Immenstadt'})
        firma = self.Partner.create({
            'name': 'Firma ohne Anschrift', 'is_company': True,
            'country_id': self.env.ref('base.de').id,
        })
        with self.assertRaises(UserError):
            req.with_user(self.reviewer)._kjr_do_approve(firma)
        self.assertFalse(partner.parent_id)
        self.assertFalse(firma.street)
        self.assertFalse(firma.city)
        self.assertEqual(req.state, 'requested')

        # Gegenprobe: Person ohne Anschrift, dann klappt die Genehmigung.
        user2, req2 = self._signup_club('verein8b@example.com')
        user2.partner_id.write({'street': False, 'street2': False, 'zip': False,
                                'city': False, 'state_id': False, 'country_id': False})
        req2.with_user(self.reviewer)._kjr_do_approve(firma, notify=False)
        self.assertEqual(user2.partner_id.parent_id, firma)
        self.assertFalse(firma.street)

    def test_ust_id_wandert_nicht_zum_verband(self):
        if self.env['ir.module.module'].search_count(
                [('name', '=', 'base_vat'), ('state', '=', 'installed')]):
            self.skipTest('base_vat prüft die USt-IdNr.; der Test braucht eine freie Nummer.')
        user, req = self._signup_club('verein9@example.com')
        user.partner_id.vat = 'DE123456789'
        self.assertFalse(self.verband.vat)
        req.with_user(self.reviewer)._kjr_do_approve(self.verband, notify=False)
        self.assertFalse(self.verband.vat)
        self.assertEqual(user.partner_id.parent_id, self.verband)

    # ── Lücke G1: Signup-Token ──────────────────────────────────────────────

    def test_token_unter_mitgliedsverband_gesperrt(self):
        Users = self.env['res.users'].with_context(active_test=False)
        contact = self.Partner.create({
            'name': 'Kontakt Verband', 'email': 'kontakt.verband@example.com',
            'parent_id': self.verband.id})
        with self.assertRaises(UserError):
            self.env['res.users'].sudo().signup(
                {'login': contact.email, 'password': PASSWORD}, self._token(contact))
        self.assertFalse(Users.search([('login', '=', contact.email)]))

        # Ebenso für den Verbandspartner selbst
        self.verband.email = 'verband@example.com'
        with self.assertRaises(UserError):
            self.env['res.users'].sudo().signup(
                {'login': self.verband.email, 'password': PASSWORD}, self._token(self.verband))
        self.assertFalse(Users.search([('login', '=', self.verband.email)]))

        # Gegenprobe: Kontakt unter einer Firma ohne Mitgliedschaft
        firma = self.Partner.create({
            'name': 'Partnerfirma', 'is_company': True, 'street': 'Weg 1',
            'zip': '87527', 'city': 'Sonthofen'})
        other = self.Partner.create({
            'name': 'Kontakt Firma', 'email': 'kontakt.firma@example.com',
            'parent_id': firma.id})
        self.env['res.users'].sudo().signup(
            {'login': other.email, 'password': PASSWORD}, self._token(other))
        self.assertEqual(Users.search([('login', '=', other.email)]).partner_id, other)

    def test_token_aus_signup_url_gesperrt(self):
        """Shop-Weg: Token aus _get_signup_url (Bestellbestätigung von website_sale)."""
        contact = self.Partner.create({
            'name': 'Shop Kontakt', 'email': 'shop.kontakt@example.com',
            'parent_id': self.verband.id})
        url = contact.sudo().with_context(signup_valid=True)._get_signup_url()
        token = parse_qs(urlparse(url).query)['token'][0]
        with self.assertRaises(UserError):
            self.env['res.users'].sudo().signup(
                {'login': contact.email, 'password': PASSWORD}, token)

    def test_einladung_mit_bestehendem_benutzer_weiter_moeglich(self):
        contact = self.Partner.create({
            'name': 'Eingeladene Person', 'email': 'eingeladen@example.com',
            'parent_id': self.verband.id})
        wizard = self.env['portal.wizard'].create({'partner_ids': [Command.set(contact.ids)]})
        wizard.user_ids.action_grant_access()
        self.assertTrue(contact.user_ids)
        token = self._token(contact)
        # Der Vereinsschlüssel muss vor partner_user.write entfernt werden, sonst
        # schlüge write mit einem unbekannten Feld fehl.
        self.env['res.users'].sudo().signup(
            {'password': PASSWORD, 'kjr_affiliation': {'name': 'Irgendwas'}}, token)
        self.assertFalse(self.Request.search([('partner_id', '=', contact.id)]))
        self.assertEqual(contact.parent_id, self.verband)

    def test_archivierter_benutzer_unter_verband_gesperrt(self):
        user = new_test_user(self.env, login='kjr_archiv@example.com', groups='base.group_portal')
        partner = user.partner_id
        partner.parent_id = self.verband
        user.active = False
        with self.assertRaises(UserError):
            self.env['res.users'].sudo().signup({'password': PASSWORD}, self._token(partner))

    def test_kein_signup_token_fuer_verbandskontakt(self):
        contact = self.Partner.create({
            'name': 'Kontakt ohne Token', 'email': 'ohne.token@example.com',
            'parent_id': self.verband.id})
        other = self.Partner.create({'name': 'Einzelperson', 'email': 'einzel@example.com'})
        res = (contact | other).signup_get_auth_param()
        self.assertNotIn('auth_signup_token', res.get(contact.id, {}))
        self.assertIn('auth_signup_token', res.get(other.id, {}))

    def test_token_unter_dachverband_ohne_mitgliedschaft_gesperrt(self):
        """Dachverband D (Firma, kein Mitglied) mit Mitgliedsorganisation O darunter.

        O ist Firma und damit ihr eigener commercial partner; ein Konto unter D
        hätte über child_of trotzdem Zuschussrechte für O
        (controllers/website.py, _allowed_member_domain)."""
        Users = self.env['res.users'].with_context(active_test=False)
        dach = self.Partner.create({
            'name': 'Dachverband', 'is_company': True, 'email': 'dach@example.com',
            'street': 'Dachweg 1', 'zip': '87527', 'city': 'Sonthofen'})
        mitglied = self.Partner.create({
            'name': 'Mitgliedsorganisation', 'is_company': True, 'is_kjr_member': True,
            'parent_id': dach.id})
        self.assertEqual(mitglied.commercial_partner_id, mitglied)
        self.assertFalse(dach.is_kjr_member)
        contact = self.Partner.create({
            'name': 'Kontakt Dach', 'email': 'kontakt.dach@example.com',
            'parent_id': dach.id})
        self.assertTrue(contact._kjr_grants_member_rights())
        with self.assertRaises(UserError):
            self.env['res.users'].sudo().signup(
                {'login': contact.email, 'password': PASSWORD}, self._token(contact))
        self.assertFalse(Users.search([('login', '=', contact.email)]))
        with self.assertRaises(UserError):
            self.env['res.users'].sudo().signup(
                {'login': dach.email, 'password': PASSWORD}, self._token(dach))
        self.assertFalse(Users.search([('login', '=', dach.email)]))
        res = contact.signup_get_auth_param()
        self.assertNotIn('auth_signup_token', res.get(contact.id, {}))

    # ── Zuständigkeit und Rechtewache ───────────────────────────────────────

    def test_zustaendige_person_nur_sachbearbeiter(self):
        """Der Parameter darf keine Person ohne Leserecht auf die Registrierung
        wählen (mail.activity.create prüft das nicht)."""
        intern = new_test_user(self.env, login='kjr_intern_ohne_sb', groups='base.group_user')
        Param = self.env['ir.config_parameter'].sudo()
        Param.set_param('kjr_grant.affiliation_responsible_user_id', str(intern.id))
        with mute_logger('odoo.addons.kjr_grant.models.kjr_affiliation_request'):
            responsible = self.Request._kjr_office_responsible()
        self.assertNotEqual(responsible, intern)
        self.assertTrue(responsible.has_group('kjr_grant.group_kjr_reviewer'))
        with mute_logger('odoo.addons.kjr_grant.models.kjr_affiliation_request'):
            _user, req = self._signup_club('verein_zust@example.com')
        activity = req.sudo().activity_ids.filtered(lambda a: a.summary == ACTIVITY_SUMMARY)
        self.assertEqual(len(activity), 1)
        self.assertTrue(activity.user_id.has_group('kjr_grant.group_kjr_reviewer'))

        # Gültiger Parameter wird übernommen.
        Param.set_param('kjr_grant.affiliation_responsible_user_id', str(self.reviewer.id))
        self.assertEqual(self.Request._kjr_office_responsible(), self.reviewer)

    def test_rechtewache_sachbearbeiter(self):
        """Sachbearbeiter ohne Kontaktrecht ordnen über eine Backend-Registrierung
        weder interne Benutzer zu noch hängen sie Kontakte anderer Organisationen um."""
        intern = new_test_user(self.env, login='kjr_intern_ziel', groups='base.group_user')
        req = self.Request.with_user(self.reviewer).create({
            'partner_id': intern.partner_id.id, 'requested_name': 'Testverband'})
        with self.assertRaises(UserError):
            req.with_user(self.reviewer)._kjr_do_approve(self.verband, notify=False)
        self.assertNotEqual(intern.partner_id.parent_id, self.verband)
        self.assertEqual(req.state, 'requested')

        andere = self.Partner.create({
            'name': 'Anderer Verband', 'is_company': True, 'is_kjr_member': True,
            'street': 'Nebenweg 2', 'zip': '87527', 'city': 'Sonthofen'})
        kontakt = self.Partner.create({'name': 'Kontakt Anderer', 'parent_id': andere.id})
        req2 = self.Request.with_user(self.reviewer).create({
            'partner_id': kontakt.id, 'requested_name': 'Testverband'})
        with self.assertRaises(UserError):
            req2.with_user(self.reviewer)._kjr_do_approve(self.verband, notify=False)
        self.assertEqual(kontakt.parent_id, andere)

        # Mit Kontaktrecht ist das Umhängen erlaubt.
        self.reviewer.group_ids = [Command.link(self.env.ref('base.group_partner_manager').id)]
        req2.with_user(self.reviewer)._kjr_do_approve(self.verband, notify=False)
        self.assertEqual(kontakt.parent_id, self.verband)

    def test_ablehnungsmail_ohne_kontaktdaten(self):
        """Ohne E-Mail und Telefon der Firma kein abgebrochener Satz „unter .“."""
        _user, req = self._signup_club('verein_mail@example.com')
        template = self.env.ref('kjr_grant.mail_template_affiliation_rejected')
        req.company_id.write({'email': False, 'phone': False})
        body = template._render_field('body_html', req.ids, engine='qweb')[req.id]
        self.assertNotIn('unter .', body)
        self.assertIn('wenden Sie sich bitte an die Geschäftsstelle', body)
        req.company_id.write({'email': 'gs@example.com', 'phone': False})
        body = template._render_field('body_html', req.ids, engine='qweb')[req.id]
        self.assertIn('unter gs@example.com.', body)
        self.assertNotIn(' oder ', body)

    # ── Datenhaltung ────────────────────────────────────────────────────────

    def test_doppelter_offener_antrag_verboten(self):
        user, _req = self._signup_club('verein10@example.com')
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self.Request.sudo().create({
                'partner_id': user.partner_id.id, 'requested_name': 'Zweiter Verein'})
            self.env.flush_all()

    def test_migration_bestandsnutzer_genehmigt(self):
        hooks.backfill_affiliation_requests(self.env)  # etwaiger Vorbestand der Datenbank
        portal = new_test_user(self.env, login='kjr_bestand@example.com', groups='base.group_portal')
        portal.partner_id.parent_id = self.verband
        self.assertEqual(hooks.backfill_affiliation_requests(self.env), 1)
        req = self.Request.search([('partner_id', '=', portal.partner_id.id)])
        self.assertEqual(req.state, 'approved')
        self.assertEqual(req.origin, 'migration')
        self.assertEqual(req.target_partner_id, self.verband)
        self.assertEqual(hooks.backfill_affiliation_requests(self.env), 0)

        # Zugang direkt auf dem Verbandspartner: kein Antrag
        direkt = new_test_user(self.env, login='kjr_direkt@example.com',
                               groups='base.group_portal', partner_id=self.verband.id,
                               name='Testverband', email='verband.direkt@example.com')
        self.assertEqual(direkt.partner_id, self.verband)
        # Archivierter Zugang unter dem Verband: kein Antrag
        archiv = new_test_user(self.env, login='kjr_bestand_archiv@example.com',
                               groups='base.group_portal')
        archiv.partner_id.parent_id = self.verband
        archiv.active = False
        self.assertEqual(hooks.backfill_affiliation_requests(self.env), 0)
        self.assertFalse(self.Request.search([('partner_id', 'in', (self.verband | archiv.partner_id).ids)]))

    def test_migration_bestandsnutzer_unter_dachverband(self):
        """Dachverband ohne eigene Mitgliedschaft mit Mitgliedsorganisation darunter:
        der Bestandszugang hat Rechte (child_of) und wird deshalb wie jeder andere
        Verbandszugang als genehmigt übernommen; Ziel ist der Dachverband."""
        hooks.backfill_affiliation_requests(self.env)  # etwaiger Vorbestand der Datenbank
        dach = self.Partner.create({
            'name': 'Dachverband Bestand', 'is_company': True,
            'street': 'Dachweg 2', 'zip': '87527', 'city': 'Sonthofen'})
        self.Partner.create({
            'name': 'Mitgliedsorganisation Bestand', 'is_company': True,
            'is_kjr_member': True, 'parent_id': dach.id})
        self.assertFalse(dach.is_kjr_member)
        portal = new_test_user(self.env, login='kjr_bestand_dach@example.com',
                               groups='base.group_portal')
        portal.partner_id.parent_id = dach
        self.assertTrue(portal.partner_id._kjr_grants_member_rights())
        self.assertEqual(hooks.backfill_affiliation_requests(self.env), 1)
        req = self.Request.search([('partner_id', '=', portal.partner_id.id)])
        self.assertEqual(req.state, 'approved')
        self.assertEqual(req.origin, 'migration')
        self.assertEqual(req.target_partner_id, dach)

        # Organisation ohne Mitgliedsverband im Teilbaum: keine Übernahme
        firma = self.Partner.create({
            'name': 'Firma ohne Mitgliedschaft', 'is_company': True,
            'street': 'Weg 3', 'zip': '87527', 'city': 'Sonthofen'})
        fremd = new_test_user(self.env, login='kjr_bestand_firma@example.com',
                              groups='base.group_portal')
        fremd.partner_id.parent_id = firma
        self.assertEqual(hooks.backfill_affiliation_requests(self.env), 0)
        self.assertFalse(self.Request.search([('partner_id', '=', fremd.partner_id.id)]))

    def test_loeschung_abgelehnter_antraege(self):
        _u1, alt = self._signup_club('verein11@example.com')
        _u2, frisch = self._signup_club('verein12@example.com')
        u3, genehmigt = self._signup_club('verein13@example.com')
        alt._kjr_do_reject('Alt', notify=False)
        frisch._kjr_do_reject(False, notify=False)
        genehmigt._kjr_do_approve(self.verband, notify=False)
        vor_200_tagen = fields.Datetime.now() - timedelta(days=200)
        alt.sudo().write({'date_decided': vor_200_tagen})
        genehmigt.sudo().write({'date_decided': vor_200_tagen})
        alt_id = alt.id
        Message = self.env['mail.message']
        self.assertTrue(Message.search_count([
            ('model', '=', 'kjr.affiliation.request'), ('res_id', '=', alt_id)]))

        Param = self.env['ir.config_parameter'].sudo()
        Param.set_param('kjr_grant.affiliation_rejected_retention_days', '0')
        self.assertEqual(self.Request._cron_purge_rejected(), 0)
        self.assertTrue(alt.exists())

        Param.set_param('kjr_grant.affiliation_rejected_retention_days', '180')
        self.Request._cron_purge_rejected()
        self.assertFalse(self.Request.browse(alt_id).exists())
        self.assertFalse(Message.search_count([
            ('model', '=', 'kjr.affiliation.request'), ('res_id', '=', alt_id)]))
        self.assertTrue(frisch.exists())
        self.assertTrue(genehmigt.exists())
        self.assertEqual(u3.partner_id.parent_id, self.verband)

    def test_portal_info(self):
        user, req = self._signup_club('verein14@example.com')
        info = user.partner_id._kjr_affiliation_portal_info()
        self.assertEqual(info['state'], 'requested')
        self.assertEqual(info['requested_name'], 'Skiclub Musterdorf')
        self.assertFalse(info['is_member'])
        self.assertEqual(info['rejection_reason'], '')
        req._kjr_do_reject('Unbekannter Verein', notify=False)
        info = user.partner_id._kjr_affiliation_portal_info()
        self.assertEqual(info['state'], 'rejected')
        self.assertEqual(info['rejection_reason'], 'Unbekannter Verein')

        privat = self._signup('privat2@example.com')
        self.assertEqual(privat.partner_id._kjr_affiliation_portal_info()['state'], 'none')

    def test_backend_anlage_ist_beantragt(self):
        person = self.Partner.create({'name': 'Person Backend', 'email': 'backend@example.com'})
        req = self.Request.with_user(self.reviewer).create({
            'partner_id': person.id, 'requested_name': 'Backend Verein', 'state': 'approved',
        })
        self.assertEqual(req.state, 'requested')
        self.assertEqual(req.origin, 'backend')
        self.assertTrue(req.sudo().activity_ids)
