# -*- coding: utf-8 -*-
"""Tests: Einladung zur Vollversammlung, Delegiertenverzeichnis, Anmeldung (19.0.17.0.0).

B47: Eingeladene Verbände erfassen, Einladung per E-Mail an die Delegierten
(sonst an den Verband) versenden, Versand protokollieren, kein Doppelversand,
Delegierte als Ansprechpartner an der Vollversammlung sichtbar.
B48: Bei der Anmeldung zur Vollversammlung ist die Telefonnummer Pflicht.
Prüfbefunde: Anmeldung nur innerhalb der eigenen Einladung wiederfinden, keine
ungeprüfte Kontaktzuordnung, Versandnachweis bleibt (auto_delete aus) und
Zustellstatus, Löschfrist der Anmeldungen, Datenschutzhinweis und
Barrierefreiheit der Anmeldeseite.
"""
from datetime import timedelta

from odoo import fields, http
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import HttpCase, TransactionCase


class _AssemblyMixin:

    @classmethod
    def _kjr_setup_data(cls, env):
        env.company.email = 'geschaeftsstelle@example.com'
        Partner = env['res.partner']
        cls.member_dv = Partner.create({
            'name': 'Verband mit Delegierten', 'is_company': True, 'is_kjr_member': True,
            'kjr_vr_right': True, 'email': 'verband1@example.com',
        })
        cls.delegate_a = Partner.create({
            'name': 'Delegierte A', 'email': 'dv.a@example.com', 'phone': '0831 111',
            'parent_id': cls.member_dv.id,
        })
        cls.delegate_b = Partner.create({
            'name': 'Delegierter B', 'email': 'dv.b@example.com',
            'parent_id': cls.member_dv.id,
        })
        cls.member_dv.kjr_vr_delegate_ids = [(6, 0, (cls.delegate_a | cls.delegate_b).ids)]
        cls.member_mail = Partner.create({
            'name': 'Verband ohne Delegierte', 'is_company': True, 'is_kjr_member': True,
            'kjr_vr_right': True, 'email': 'verband2@example.com',
        })
        cls.member_none = Partner.create({
            'name': 'Verband ohne Adresse', 'is_company': True, 'is_kjr_member': True,
            'kjr_vr_right': True,
        })
        cls.assembly = env['kjr.assembly'].create({
            'name': 'Frühjahrsvollversammlung Test',
            'date': fields.Datetime.now() + timedelta(days=30),
            'location': 'Sonthofen',
            'invited_member_ids': [(6, 0, (cls.member_dv | cls.member_mail | cls.member_none).ids)],
        })


@tagged('post_install', '-at_install')
class TestKjrAssemblyInvitation(_AssemblyMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._kjr_setup_data(cls.env)

    def _mails(self, invitation):
        return self.env['mail.mail'].search([
            ('model', '=', 'kjr.assembly.invitation'), ('res_id', 'in', invitation.ids)])

    def _inv(self, member):
        return self.assembly.invitation_ids.filtered(lambda i: i.member_id == member)

    def test_einladen_versendet_an_delegierte_sonst_verband(self):
        self.assembly.action_invite()
        self.assertEqual(self.assembly.state, 'invited')
        self.assertTrue(self.assembly.invitation_date)
        inv_dv = self._inv(self.member_dv)
        self.assertEqual(inv_dv.state, 'sent')
        self.assertEqual(inv_dv.recipient_type, 'delegates')
        self.assertEqual(inv_dv.recipient_ids, self.delegate_a | self.delegate_b)
        mail = self._mails(inv_dv)
        self.assertEqual(len(mail), 1)
        self.assertEqual(mail.recipient_ids, self.delegate_a | self.delegate_b)
        self.assertIn('/vollversammlung/anmeldung/%s/' % inv_dv.id, str(mail.body_html))
        self.assertIn('Frühjahrsvollversammlung Test', mail.subject)
        # Ohne Delegierte: an die E-Mail des Verbands
        inv_mail = self._inv(self.member_mail)
        self.assertEqual(inv_mail.state, 'sent')
        self.assertEqual(inv_mail.recipient_type, 'member')
        self.assertEqual(self._mails(inv_mail).recipient_ids, self.member_mail)
        # Ohne jede Adresse: kein Versand, sichtbar als „Keine E-Mail-Adresse“
        inv_none = self._inv(self.member_none)
        self.assertEqual(inv_none.state, 'no_address')
        self.assertFalse(self._mails(inv_none))
        self.assertEqual(self.assembly.invitation_sent_count, 2)
        self.assertEqual(self.assembly.invitation_open_count, 1)
        # Protokoll: Versandzeitpunkt, Absender, Notiz an der Vollversammlung
        self.assertTrue(inv_dv.date_sent)
        self.assertEqual(inv_dv.sent_by_id, self.env.user)
        # Nachweis: Mail bleibt erhalten und steht im Verlauf der Einladung;
        # Zustellung noch offen (Warteschlange)
        self.assertFalse(mail.auto_delete)
        self.assertEqual(inv_dv.sudo().mail_id, mail)
        self.assertEqual(inv_dv.delivery_state, 'queued')
        self.assertIn(mail.mail_message_id, inv_dv.message_ids)
        self.assertEqual(inv_none.delivery_state, 'none')
        self.assertTrue(self.assembly.message_ids.filtered(
            lambda m: 'Einladung per E-Mail' in str(m.body)))

    def test_kein_doppelversand(self):
        self.assembly.action_invite()
        count = len(self._mails(self.assembly.invitation_ids))
        self.assembly.action_send_invitations()
        self.assertEqual(len(self._mails(self.assembly.invitation_ids)), count)
        # Nachträglich eingeladener Verband bekommt seine Einladung, sonst niemand
        spaet = self.env['res.partner'].create({
            'name': 'Später eingeladen', 'is_company': True, 'is_kjr_member': True,
            'email': 'spaet@example.com',
        })
        self.assembly.invited_member_ids = [(4, spaet.id)]
        self.assembly.action_send_invitations()
        self.assertEqual(len(self._mails(self.assembly.invitation_ids)), count + 1)
        self.assertEqual(self._inv(spaet).state, 'sent')
        self.assertEqual(self._inv(self.member_dv).send_count, 1)

    def test_fehlgeschlagene_zustellung_wird_erneut_versandt(self):
        self.assembly.action_invite()
        inv = self._inv(self.member_dv)
        mail = self._mails(inv)
        # Versand an den Mailserver gescheitert: bleibt mit auto_delete=False erhalten
        mail.sudo().write({'state': 'exception'})
        inv.invalidate_recordset(['delivery_state'])
        self.assertEqual(inv.delivery_state, 'failed')
        self.assembly.invalidate_recordset(['invitation_open_count'])
        self.assertEqual(self.assembly.invitation_open_count, 2,
                         'Fehlgeschlagene Einladung zählt als offen (dazu der Verband ohne Adresse).')
        self.assembly.action_send_invitations()
        self.assertEqual(len(self._mails(inv)), 2)
        self.assertEqual(inv.send_count, 2)
        self.assertEqual(inv.delivery_state, 'queued')
        # Erfolgreich zugestellte Einladungen bleiben unberührt
        self.assertEqual(self._inv(self.member_mail).send_count, 1)

    def test_erneut_senden_nur_ausdruecklich(self):
        self.assembly.action_invite()
        inv = self._inv(self.member_dv)
        inv.action_resend()
        self.assertEqual(len(self._mails(inv)), 2)
        self.assertEqual(inv.send_count, 2)

    def test_entfernter_verband_bekommt_keine_erneute_einladung(self):
        """Zustellung gescheitert, Verband aus der Liste genommen: kein erneuter Versand."""
        self.assembly.action_invite()
        inv = self._inv(self.member_mail)
        self._mails(inv).sudo().write({'state': 'exception'})
        self.assembly.invited_member_ids = [(3, self.member_mail.id)]
        spaet = self.env['res.partner'].create({
            'name': 'Neu dazu', 'is_company': True, 'is_kjr_member': True,
            'email': 'neu.dazu@example.com',
        })
        self.assembly.invited_member_ids = [(4, spaet.id)]
        self.assembly.action_send_invitations()
        self.assertEqual(len(self._mails(inv)), 1)
        self.assertEqual(inv.send_count, 1)
        self.assertTrue(inv.exists(), 'Der versandte Nachweis bleibt stehen.')
        self.assertEqual(self._inv(spaet).state, 'sent')
        # „Erneut senden“ ist für den entfernten Verband gesperrt
        self.assertFalse(inv.can_resend)
        with self.assertRaises(UserError):
            inv.action_resend()
        self.assertEqual(len(self._mails(inv)), 1)

    def test_erneut_senden_nur_fuer_offene_versammlung(self):
        self.assembly.action_invite()
        inv = self._inv(self.member_dv)
        self.assertTrue(inv.can_resend)
        self.assembly.action_cancel()
        inv.invalidate_recordset(['can_resend'])
        self.assertFalse(inv.can_resend)
        with self.assertRaises(UserError):
            inv.action_resend()
        self.assertEqual(len(self._mails(inv)), 1)

    def test_vergangener_termin_kein_versand(self):
        # Bestandsversammlung: noch „Eingeladen“, Termin vorbei, keine Nachweise
        self.assembly.write({
            'state': 'invited', 'date': fields.Datetime.now() - timedelta(days=3)})
        self.assertTrue(self.assembly.date_in_past)
        with self.assertRaises(UserError):
            self.assembly.action_send_invitations()
        self.assertFalse(self.assembly.invitation_ids)
        # Nachträglich erfasste Sitzung: „Einladen“ setzt nur den Status
        alt = self.env['kjr.assembly'].create({
            'name': 'Nacherfasst', 'date': fields.Datetime.now() - timedelta(days=100)})
        alt.action_invite()
        self.assertEqual(alt.state, 'invited')
        self.assertTrue(alt.invited_member_ids)
        self.assertFalse(alt.invitation_ids)
        self.assertFalse(alt.invitation_date)

    def test_kopie_ohne_eingeladene_verbaende(self):
        kopie = self.assembly.copy({'date': fields.Datetime.now() + timedelta(days=400)})
        self.assertFalse(kopie.invited_member_ids)
        ausgetreten = self.member_none
        ausgetreten.is_kjr_member = False
        kopie.action_invite()
        self.assertNotIn(ausgetreten, kopie.invited_member_ids)
        self.assertIn(self.member_dv, kopie.invited_member_ids)

    def test_delegierte_ohne_email_sichtbar_und_verband_in_kopie(self):
        ohne = self.env['res.partner'].create({
            'name': 'Delegierte C ohne Mail', 'phone': '0831 555',
            'parent_id': self.member_dv.id,
        })
        self.member_dv.kjr_vr_delegate_ids = [(4, ohne.id)]
        self.assertEqual(self.assembly.delegate_missing_email_count, 1)
        self.assembly.action_invite()
        inv = self._inv(self.member_dv)
        self.assertEqual(inv.recipient_type, 'delegates_member')
        self.assertEqual(inv.recipient_ids, self.delegate_a | self.delegate_b | self.member_dv)
        mail = self._mails(inv)
        self.assertIn('nicht für alle Delegierten', str(mail.body_html))
        self.assertTrue(self.assembly.message_ids.filtered(
            lambda m: 'Delegierte ohne E-Mail-Adresse' in str(m.body)
            and 'Verband mit Delegierten: 1' in str(m.body)))

    def test_manuelle_auswahl_bleibt_beim_einladen(self):
        weiterer = self.env['res.partner'].create({
            'name': 'Nicht eingeladen', 'is_company': True, 'is_kjr_member': True,
            'kjr_vr_right': True, 'email': 'nicht@example.com',
        })
        self.assembly.action_invite()
        self.assertNotIn(weiterer, self.assembly.invited_member_ids)
        leer = self.env['kjr.assembly'].create({
            'name': 'Leere Liste', 'date': fields.Datetime.now() + timedelta(days=10)})
        leer.action_invite()
        self.assertIn(weiterer, leer.invited_member_ids,
                      'Ohne Auswahl werden alle stimmberechtigten Verbände eingeladen.')

    def test_delegiertenverzeichnis(self):
        self.assertEqual(self.assembly.delegate_ids, self.delegate_a | self.delegate_b)
        self.assertEqual(self.assembly.delegate_missing_phone_count, 1)
        self.delegate_b.phone = '0831 222'
        self.assertEqual(self.assembly.delegate_missing_phone_count, 0)

    def test_anmeldung_telefon_pflicht(self):
        Registration = self.env['kjr.assembly.registration']
        with self.assertRaises(ValidationError):
            Registration.create({
                'assembly_id': self.assembly.id, 'member_id': self.member_dv.id,
                'name': 'Ohne Telefon', 'email': 'x@example.com', 'phone': ' ',
            })
        with self.assertRaises(ValidationError):
            Registration.create({
                'assembly_id': self.assembly.id, 'member_id': self.member_dv.id,
                'name': 'Buchstaben', 'email': 'y@example.com', 'phone': 'keine Nummer',
            })
        reg = Registration.create({
            'assembly_id': self.assembly.id, 'member_id': self.member_dv.id,
            'name': 'Mit Telefon', 'email': 'z@example.com', 'phone': '0831 333',
        })
        self.assertEqual(self.assembly.registration_count, 1)
        self.assertEqual(reg.origin, 'office')

    def test_anmeldung_ueber_einladung_ohne_dubletten(self):
        self.assembly.action_invite()
        inv = self._inv(self.member_dv)
        reg = inv._kjr_register('Delegierte A', 'DV.A@example.com', '0831 999')
        # Eingetippte Adresse ist ungeprüft: kein Kontakt, nur ein Vorschlag
        self.assertFalse(reg.partner_id)
        self.assertFalse(reg.is_delegate)
        self.assertEqual(reg.suggested_partner_id, self.delegate_a)
        reg.action_assign_suggested_partner()
        self.assertEqual(reg.partner_id, self.delegate_a)
        self.assertTrue(reg.is_delegate)
        self.assertEqual(reg.origin, 'online')
        again = inv._kjr_register('Delegierte A', 'dv.a@example.com', '0831 000')
        self.assertEqual(again, reg)
        self.assertEqual(reg.phone, '0831 000')
        self.assertEqual(len(self.assembly.registration_ids), 1)
        # Erneute Anmeldung ohne Login löscht die Zuordnung der Geschäftsstelle nicht
        self.assertEqual(reg.partner_id, self.delegate_a)
        self.assertTrue(reg.is_delegate)
        # Unterstrich in der Adresse ist kein Platzhalter
        other = inv._kjr_register('Andere', 'dv_a@example.com', '0831 444')
        self.assertNotEqual(other, reg)

    def test_angemeldete_person_wird_eigenem_kontakt_zugeordnet(self):
        self.assembly.action_invite()
        inv = self._inv(self.member_dv)
        reg = inv._kjr_register('Delegierte A', 'dv.a@example.com', '0831 999',
                                partner=self.delegate_a)
        self.assertEqual(reg.partner_id, self.delegate_a)
        self.assertTrue(reg.is_delegate)

    def test_anmeldung_ueber_fremden_link_ueberschreibt_nichts(self):
        self.assembly.action_invite()
        inv_dv = self._inv(self.member_dv)
        inv_mail = self._inv(self.member_mail)
        reg = inv_dv._kjr_register('Delegierte A', 'dv.a@example.com', '0831 999')
        # Gleiche Adresse über den Link eines anderen Verbands: neue Anmeldung,
        # die bestehende bleibt beim Verband A
        fremd = inv_mail._kjr_register('Jemand', 'dv.a@example.com', '0831 000')
        self.assertNotEqual(fremd, reg)
        self.assertEqual(reg.member_id, self.member_dv)
        self.assertEqual(reg.invitation_id, inv_dv)
        self.assertEqual(reg.name, 'Delegierte A')
        self.assertEqual(reg.phone, '0831 999')
        self.assertEqual(fremd.member_id, self.member_mail)

    def test_anmeldung_der_geschaeftsstelle_bleibt_unveraendert(self):
        self.assembly.action_invite()
        inv = self._inv(self.member_dv)
        office = self.env['kjr.assembly.registration'].create({
            'assembly_id': self.assembly.id, 'member_id': self.member_dv.id,
            'invitation_id': inv.id, 'name': 'Erfasst', 'email': 'dv.a@example.com',
            'phone': '0831 111', 'partner_id': self.delegate_a.id,
        })
        self.assertEqual(office.origin, 'office')
        online = inv._kjr_register('Online', 'dv.a@example.com', '0831 222')
        self.assertNotEqual(online, office)
        self.assertEqual(office.origin, 'office')
        self.assertEqual(office.name, 'Erfasst')
        self.assertEqual(office.phone, '0831 111')
        self.assertEqual(office.partner_id, self.delegate_a)

    def test_loeschfrist_der_anmeldungen(self):
        Registration = self.env['kjr.assembly.registration']
        Param = self.env['ir.config_parameter'].sudo()
        reg = Registration.create({
            'assembly_id': self.assembly.id, 'member_id': self.member_dv.id,
            'name': 'Alt', 'email': 'alt@example.com', 'phone': '0831 333',
        })
        Param.set_param('kjr_grant.assembly_registration_retention_days', '30')
        self.assertEqual(Registration._kjr_retention_days(), 30)
        # Versammlung noch offen: nichts löschen
        self.assembly.date = fields.Datetime.now() - timedelta(days=60)
        self.assertEqual(Registration._cron_purge_expired(), 0)
        self.assertTrue(reg.exists())
        # Durchgeführt, Termin älter als die Frist: löschen
        self.assembly.state = 'done'
        self.assertEqual(Registration._cron_purge_expired(), 1)
        self.assertFalse(reg.exists())
        # 0 = aus, ungültig = Vorgabe
        Param.set_param('kjr_grant.assembly_registration_retention_days', '0')
        self.assertEqual(Registration._kjr_retention_days(), 0)
        self.assertEqual(Registration._cron_purge_expired(), 0)
        Param.set_param('kjr_grant.assembly_registration_retention_days', 'abc')
        self.assertEqual(Registration._kjr_retention_days(), 365)

    def test_sachbearbeitung_sieht_anmeldelink(self):
        """Der Link steht ohnehin in der versandten Mail im Verlauf: keine Scheinsperre."""
        from odoo.tests.common import new_test_user
        reviewer = new_test_user(self.env, login='kjr_sb_anmeldelink',
                                 groups='base.group_user,kjr_grant.group_kjr_reviewer')
        self.assembly.action_invite()
        inv = self._inv(self.member_dv).with_user(reviewer)
        self.assertIn('/vollversammlung/anmeldung/%s/' % inv.id, inv.registration_url)

    def test_migration_schaltet_auto_delete_ab(self):
        import importlib.util
        from odoo.tools.misc import file_path
        spec = importlib.util.spec_from_file_location(
            'kjr_grant_mig_verband_assembly',
            file_path('kjr_grant/migrations/19.0.17.0.0/post-verband.py'))
        mig = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mig)
        template = self.env.ref('kjr_grant.mail_template_assembly_invitation')
        self.assertFalse(template.auto_delete)
        template.auto_delete = True
        self.assertTrue(mig._behalte_einladungsmails(self.env))
        self.assertFalse(template.auto_delete)
        self.assertFalse(mig._behalte_einladungsmails(self.env))


@tagged('post_install', '-at_install')
class TestKjrAssemblyRegistrationHttp(_AssemblyMixin, HttpCase):

    def setUp(self):
        super().setUp()
        self._kjr_setup_data(self.env)
        self.assembly.action_invite()
        self.inv = self.assembly.invitation_ids.filtered(lambda i: i.member_id == self.member_dv)
        self.url = '/vollversammlung/anmeldung/%s/%s' % (self.inv.id, self.inv.access_token)
        self.env.flush_all()
        self.authenticate(None, None)
        self.csrf_token = http.Request.csrf_token(self)

    def test_falscher_schluessel_404(self):
        response = self.url_open('/vollversammlung/anmeldung/%s/falsch' % self.inv.id)
        self.assertEqual(response.status_code, 404)

    def test_seite_zeigt_formular_mit_pflichttelefon(self):
        text = self.url_open(self.url).text
        self.assertIn('Frühjahrsvollversammlung Test', text)
        self.assertIn('name="phone"', text)
        # Barrierefreiheit: Stern für Screenreader ausgeblendet, Legende vorhanden
        self.assertIn('Telefon <span class="text-danger" aria-hidden="true">*</span>', text)
        self.assertIn('Mit * markierte Felder sind Pflicht.', text)
        # Datenschutzhinweis mit Löschung und Verantwortlichem
        self.assertIn('Löschung', text)
        self.assertIn('365 Tage nach dem Termin', text)
        # Telefon im eigenen Kontakt: Sichtbarkeit und Löschung offengelegt
        self.assertIn('anderen Portal-Zugänge Ihres Verbands', text)
        self.assertIn('die Löschfrist gilt nur für die Anmeldung', text)
        self.assertIn('Verantwortlich', text)

    def test_ohne_telefon_keine_anmeldung(self):
        response = self.url_open(self.url, data={
            'csrf_token': self.csrf_token, 'name': 'Delegierte A',
            'email': 'dv.a@example.com', 'phone': ''})
        self.assertIn('Die Telefonnummer ist Pflicht', response.text)
        # Barrierefreiheit: Fehler am Feld verknüpft, Feld als ungültig markiert
        self.assertIn('id="kjr_reg_phone_err"', response.text)
        self.assertIn('aria-describedby="kjr_reg_phone_err kjr_reg_phone_help"', response.text)
        self.assertIn('aria-invalid="true"', response.text)
        self.env.invalidate_all()
        self.assertFalse(self.assembly.registration_ids)

    def test_mit_telefon_angemeldet(self):
        response = self.url_open(self.url, data={
            'csrf_token': self.csrf_token, 'name': 'Delegierte A',
            'email': 'dv.a@example.com', 'phone': '0831 123'})
        self.assertIn('Ihre Anmeldung ist gespeichert', response.text)
        # Kein Versprechen „jederzeit“; Abmeldung über die Geschäftsstelle
        self.assertNotIn('jederzeit', response.text)
        self.assertIn('Bis zum Termin', response.text)
        self.assertIn('Wenn Sie nicht teilnehmen können', response.text)
        self.env.invalidate_all()
        reg = self.assembly.registration_ids
        self.assertEqual(len(reg), 1)
        self.assertEqual(reg.phone, '0831 123')
        self.assertEqual(reg.member_id, self.member_dv)

    def test_nach_der_versammlung_keine_anmeldung(self):
        self.assembly.date = fields.Datetime.now() - timedelta(days=1)
        self.env.flush_all()
        response = self.url_open(self.url, data={
            'csrf_token': self.csrf_token, 'name': 'Delegierte A',
            'email': 'dv.a@example.com', 'phone': '0831 123'})
        self.assertIn('keine Online-Anmeldung', response.text)
        self.env.invalidate_all()
        self.assertFalse(self.assembly.registration_ids)
