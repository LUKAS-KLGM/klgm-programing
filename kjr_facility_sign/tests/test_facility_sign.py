# -*- coding: utf-8 -*-
"""Tests der Brücke Einrichtungen ↔ E-Signatur (kjr_facility_sign).

Das Vertrags-PDF wird gepatcht (im Testmodus liefert Odoo für Berichte HTML
statt PDF); ein Test prüft genau diesen Rückfall ohne Patch. Mails entstehen
im Testmodus als mail.mail und werden nicht versendet.
``_send_completed_documents`` wird beim Unterschreiben gemockt, damit kein
fertiges PDF erzeugt werden muss; die Kopie des unterschriebenen PDF an der
Buchung wird deshalb erst bei der Kalibrierung auf der Instanz geprüft.
"""
import io
from datetime import timedelta
from unittest.mock import patch

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from odoo import SUPERUSER_ID, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user
from odoo.tools.pdf import PdfFileReader

from odoo.addons.kjr_facility_sign.models.kjr_facility_booking import (
    PARAM_ENABLED,
    PARAM_REMINDER,
    PARAM_SENDER,
)
from odoo.addons.kjr_facility_sign.tools import sign_page

CONTACT_EMAIL = 'leitung.test@example.com'
CONTACT_NAME = 'Max Leitung'

# 1x1-PNG, gültiges Base64 für das Unterschriftsfeld
PNG_1X1 = (
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA'
    '60e6kgAAAABJRU5ErkJggg==')


def _one_page_pdf():
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(100, 750, 'Buchungsvertrag Test')
    c.showPage()
    c.save()
    return buf.getvalue()


@tagged('post_install', '-at_install')
class TestKjrFacilitySign(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Booking = cls.env['kjr.facility.booking']
        cls.SignRequest = cls.env['sign.request']
        cls.Partner = cls.env['res.partner']
        cls.ICP = cls.env['ir.config_parameter'].sudo()
        cls.sender = new_test_user(
            cls.env, login='kjr_fac_sign_sender', name='Geschäftsstelle Test',
            email='geschaeftsstelle.test@example.com', groups='base.group_user')
        cls.fac_user = new_test_user(
            cls.env, login='kjr_fac_sign_user', name='Sachbearbeitung Test',
            email='sachbearbeitung.test@example.com',
            groups='kjr_facility.group_kjr_facility_user')
        cls.org = cls.Partner.create({'name': 'Jugendgruppe Test', 'is_company': True})
        cls.facility = cls.env['kjr.facility'].create({
            'name': 'Testhaus Sign', 'facility_type': 'house',
            'capacity': 42, 'supervision_ratio': 5,
        })
        cls.ICP.set_param(PARAM_SENDER, str(cls.sender.id))
        cls.ICP.set_param(cls.Booking._AUTOMATION_ACTIVE_FROM, '2000-01-01 00:00:00')
        cls.today = fields.Date.today()
        cls.pdf = _one_page_pdf()

    def setUp(self):
        super().setUp()
        self.ICP.set_param(PARAM_ENABLED, 'True')
        self.pdf_patcher = patch.object(
            type(self.Booking), '_kjr_sign_contract_pdf_base', return_value=self.pdf)
        self.pdf_patcher.start()
        self.addCleanup(self.pdf_patcher.stop)

    # ── Hilfen ──────────────────────────────────────────────────────────────

    def _booking(self, env=None, **kw):
        vals = {
            'facility_id': self.facility.id,
            'partner_id': self.org.id,
            'check_in': self.today + timedelta(days=30),
            'check_out': self.today + timedelta(days=33),
            'participant_count': 10,
            'contact_person': CONTACT_NAME,
            'contact_email': CONTACT_EMAIL,
        }
        vals.update(kw)
        return (env or self.env)['kjr.facility.booking'].create(vals)

    def _confirmed(self, **kw):
        booking = self._booking(**kw)
        booking.action_confirm()
        req = self.SignRequest.browse(booking.sudo().kjr_sign_request_id.id)
        self.assertTrue(req, 'Es muss eine Unterschriftsanfrage entstanden sein.')
        return booking, req

    def _requests(self, booking):
        return self.SignRequest.with_context(active_test=False).search([
            ('reference_doc', '=', 'kjr.facility.booking,%d' % booking.id)])

    def _sign_values(self, req):
        # Odoo 19 kennt kein item_type 'date': sign.sign_item_type_date ist ein
        # gewöhnlicher Text-Typ und nur über die XML-ID erkennbar
        # (ent-19 sign/data/sign_data.xml, sign_document.py).
        date_type = self.env.ref('sign.sign_item_type_date')
        values = {}
        for item in req.template_id.sign_item_ids:
            if item.type_id.item_type == 'signature':
                values[str(item.id)] = 'data:image/png;base64,' + PNG_1X1
            elif item.type_id == date_type:
                values[str(item.id)] = self.today.strftime('%d.%m.%Y')
            else:
                values[str(item.id)] = 'Sonthofen'
        return values

    def _sign(self, req):
        item = req.request_item_ids[:1]
        with patch.object(type(self.SignRequest), '_send_completed_documents', autospec=True):
            item.sudo().sign(self._sign_values(req))

    def _mails(self, subject_prefix):
        return self.env['mail.mail'].sudo().search([
            ('subject', '=like', subject_prefix + '%')])

    def _notes(self, booking, text):
        return booking.message_ids.filtered(lambda m: text in (m.body or ''))

    def _activities(self, booking, summary):
        return booking.activity_ids.filtered(lambda a: a.summary == summary)

    # ── Modus und Versand ────────────────────────────────────────────────────

    def test_default_off_uses_mail(self):
        """Ohne Systemparameter: Vertragsmail wie bisher, keine Anfrage."""
        self.ICP.set_param(PARAM_ENABLED, False)
        booking = self._booking()
        booking.action_confirm()
        self.assertFalse(self._requests(booking))
        self.assertEqual(len(self._mails('Buchungsvertrag %s' % booking.name)), 1)
        self.assertEqual(booking.kjr_sign_state, 'none')
        self.assertFalse(booking.kjr_sign_available)

    def test_enabled_creates_request(self):
        """Eingeschaltet: genau eine Anfrage, Vorlage archiviert, Felder auf der letzten Seite."""
        booking, req = self._confirmed()
        self.assertEqual(self._requests(booking), req)
        self.assertEqual(req.state, 'sent')
        self.assertEqual(req.reference_doc, booking)
        self.assertEqual(req.create_uid, self.sender)
        self.assertEqual(req.request_item_ids.partner_id.email_normalized, CONTACT_EMAIL)
        self.assertTrue(req.reminder_enabled)
        self.assertEqual(req.reminder, 3)
        self.assertEqual(req.validity, self.today + timedelta(days=14))
        template = req.template_id
        self.assertFalse(template.active, 'Die Einmal-Vorlage muss archiviert sein.')
        doc = template.document_ids
        self.assertEqual(len(doc), 1)
        self.assertEqual(doc.num_pages, 2, 'Vertrag (1 Seite) plus Unterschriftsseite.')
        items = template.sign_item_ids
        self.assertEqual(len(items), 3)
        self.assertEqual(items.responsible_id, self.env.ref('kjr_facility_sign.sign_item_role_tenant'))
        self.assertEqual(set(items.mapped('page')), {doc.num_pages})
        self.assertEqual(
            items.type_id,
            self.env.ref('sign.sign_item_type_text')
            | self.env.ref('sign.sign_item_type_date')
            | self.env.ref('sign.sign_item_type_signature'))
        self.assertEqual(set(items.type_id.mapped('item_type')), {'text', 'signature'})
        for item in items:
            self.assertTrue(0 <= item.posX and item.posX + item.width <= 1)
            self.assertTrue(0 <= item.posY and item.posY + item.height <= 1)
        self.assertEqual(booking.kjr_sign_state, 'sent')
        self.assertTrue(booking.kjr_sign_available)
        self.assertEqual(booking.contract_sent_date, self.today)
        self.assertTrue(booking.contract_followup_sent)
        self.assertEqual(booking.state, 'confirmed')
        # Keine Vertragsmail aus kjr_facility, aber Buchungsbestätigung und Sign-Mail.
        self.assertFalse(self._mails('Buchungsvertrag %s' % booking.name))
        self.assertEqual(len(self._mails('Buchungsbestätigung %s' % booking.name)), 1)
        sign_mails = self._mails('Bitte unterschreiben: Buchungsvertrag %s' % booking.name)
        self.assertEqual(len(sign_mails), 1)
        self.assertEqual(sign_mails.state, 'outgoing', 'Sign-Mail nur in der Warteschlange.')
        self.assertTrue(self._notes(booking, 'Unterschriftsanfrage zum Vertrag versendet'))

    def test_facility_disabled_uses_mail(self):
        """An der Einrichtung abgeschaltet: Mailweg, keine Anfrage."""
        self.facility.kjr_sign_disabled = True
        booking = self._booking()
        booking.action_confirm()
        self.assertFalse(self._requests(booking))
        self.assertEqual(len(self._mails('Buchungsvertrag %s' % booking.name)), 1)
        self.assertFalse(booking.kjr_sign_available)

    def test_no_email_falls_back(self):
        """Ohne E-Mail-Adresse: Rückfall auf Mail, Aufgabe, kein Fehler."""
        booking = self._booking(contact_email=False)
        booking.action_confirm()
        self.assertFalse(self._requests(booking))
        self.assertEqual(booking.state, 'confirmed')
        self.assertEqual(booking.kjr_sign_state, 'none')
        self.assertEqual(len(self._activities(
            booking, 'Vertrag ohne digitale Unterschrift versendet: %s' % booking.name)), 1)

    def test_report_html_in_testmode_falls_back(self):
        """Ohne Patch liefert der Testmodus HTML: Rückfall auf Mail plus Aufgabe."""
        self.pdf_patcher.stop()
        booking = self._booking()
        booking.action_confirm()
        self.assertFalse(self._requests(booking))
        self.assertEqual(booking.state, 'confirmed')
        self.assertEqual(len(self._activities(
            booking, 'Vertrag ohne digitale Unterschrift versendet: %s' % booking.name)), 1)

    # ── Unterschrift, Ablehnung, Ablauf ─────────────────────────────────────

    def test_sign_marks_contract(self):
        """Unterschrift setzt „Vertrag unterschrieben“ (digital, heute), Status bleibt."""
        booking, req = self._confirmed()
        self._sign(req)
        self.assertEqual(req.state, 'signed')
        self.assertTrue(booking.contract_signed)
        self.assertEqual(booking.contract_signed_source, 'digital')
        self.assertEqual(booking.contract_signed_date, self.today)
        self.assertEqual(booking.state, 'confirmed', 'Die Unterschrift ändert den Status nicht.')
        self.assertEqual(booking.kjr_sign_state, 'signed')
        self.assertFalse(booking.contract_followup_sent)

    def test_digital_source_needs_signed_request(self):
        """Der Kontextschlüssel allein (z. B. per RPC) macht keine digitale Unterschrift."""
        booking, req = self._confirmed()
        booking.with_user(self.fac_user).with_context(kjr_facility_sign_digital=True).write(
            {'contract_signed': True})
        self.assertEqual(booking.contract_signed_source, 'paper')
        self.assertEqual(req.state, 'canceled', 'Papierweg storniert die offene Anfrage.')
        self.assertEqual(booking.kjr_sign_state, 'canceled')

    def test_stale_request_no_effect(self):
        """Nach „erneut anfordern“ ist die alte Anfrage storniert und ohne Wirkung."""
        booking, old_req = self._confirmed()
        booking.with_user(self.fac_user).action_kjr_sign_request_resend()
        new_req = self.SignRequest.browse(booking.sudo().kjr_sign_request_id.id)
        self.assertNotEqual(new_req, old_req)
        self.assertEqual(old_req.state, 'canceled')
        self.assertEqual(new_req.state, 'sent')
        self.assertFalse(old_req._kjr_facility_booking())
        self.assertEqual(new_req._kjr_facility_booking(), booking)
        with self.assertRaises(UserError):
            self._sign(old_req)
        self.assertFalse(booking.contract_signed)
        self.assertTrue(self._notes(booking, 'wird neu versendet'))

    def test_sign_on_cancelled_booking_only_activity(self):
        """Storniert (ohne action_cancel): Unterschrift setzt nichts, nur Aufgabe."""
        booking, req = self._confirmed()
        booking.write({'state': 'cancelled'})
        self._sign(req)
        self.assertFalse(booking.contract_signed)
        self.assertEqual(len(self._activities(
            booking, 'Vertrag zu stornierter Buchung unterschrieben: %s' % booking.name)), 1)

    def test_refuse_once(self):
        """Ablehnung: Stand 'refused', eine Notiz, eine Aufgabe, keine Begründung im Chatter."""
        booking, req = self._confirmed()
        item = req.request_item_ids[:1]
        item.sudo()._refuse('sent', 'Grund geheim')
        self.assertEqual(req.state, 'canceled')
        self.assertTrue(booking.kjr_sign_refused)
        self.assertEqual(booking.kjr_sign_state, 'refused')
        self.assertEqual(len(self._notes(booking, 'abgelehnt')), 1)
        self.assertFalse(self._notes(booking, 'storniert'))
        self.assertFalse(self._notes(booking, 'Grund geheim'))
        self.assertEqual(len(self._activities(
            booking, 'Vertragsunterschrift abgelehnt: %s' % booking.name)), 1)

    def test_refuse_public_written_as_sender(self):
        """Ablehnung über den Mail-Link (öffentlicher Benutzer): Notiz, Aufgabe und
        write_uid im Namen des Absenders, nicht „Public user“."""
        booking, req = self._confirmed()
        public = self.env.ref('base.public_user')
        item = req.request_item_ids[:1]
        item.with_user(public).sudo()._refuse('sent', 'Grund geheim')
        self.assertEqual(booking.kjr_sign_state, 'refused')
        note = self._notes(booking, 'abgelehnt')
        self.assertEqual(len(note), 1)
        self.assertEqual(note.author_id, self.sender.partner_id)
        activity = self._activities(booking, 'Vertragsunterschrift abgelehnt: %s' % booking.name)
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity.create_uid, self.sender)
        self.assertEqual(booking.write_uid, self.sender)

    def test_expired_activity_once(self):
        """Ablauf: Stand 'expired', eine Notiz und eine Aufgabe, auch bei weiterem Schreiben."""
        booking, req = self._confirmed()
        req.write({'validity': self.today - timedelta(days=1)})
        self.assertEqual(req.state, 'expired')
        self.assertEqual(booking.kjr_sign_state, 'expired')
        summary = 'Vertragsunterschrift abgelaufen: %s' % booking.name
        self.assertEqual(len(self._activities(booking, summary)), 1)
        self.assertEqual(len(self._notes(booking, 'abgelaufen')), 1)
        req.write({'validity': self.today - timedelta(days=2)})
        self.assertEqual(len(self._activities(booking, summary)), 1)
        self.assertEqual(len(self._notes(booking, 'abgelaufen')), 1)

    # ── Papierweg, Storno, Löschen ──────────────────────────────────────────

    def test_paper_button_cancels_request(self):
        """Papier-Knopf: Anfrage storniert, Quelle Papier, Notiz."""
        booking, req = self._confirmed()
        booking.with_user(self.fac_user).action_kjr_contract_paper()
        self.assertEqual(req.state, 'canceled')
        self.assertTrue(booking.contract_signed)
        self.assertEqual(booking.contract_signed_source, 'paper')
        self.assertEqual(booking.contract_signed_date, self.today)
        self.assertEqual(len(self._notes(booking, 'auf Papier')), 1)

    def test_paper_after_refused_or_expired(self):
        """Papier nach Ablehnung bzw. Ablauf: kein „Abgelehnt“/„Abgelaufen“ mehr."""
        booking, req = self._confirmed()
        req.request_item_ids[:1].sudo()._refuse('sent', 'Grund')
        self.assertEqual(booking.kjr_sign_state, 'refused')
        booking.with_user(self.fac_user).action_kjr_contract_paper()
        self.assertFalse(booking.kjr_sign_refused)
        self.assertEqual(booking.contract_signed_source, 'paper')
        self.assertEqual(booking.kjr_sign_state, 'canceled')
        booking2, req2 = self._confirmed()
        req2.write({'validity': self.today - timedelta(days=1)})
        self.assertEqual(booking2.kjr_sign_state, 'expired')
        booking2.with_user(self.fac_user).action_kjr_contract_paper()
        self.assertEqual(req2.state, 'expired')
        self.assertEqual(booking2.kjr_sign_state, 'canceled')

    def test_manual_checkbox_counts_as_paper(self):
        """Häkchen von Hand = Papierweg; zweites Setzen ändert das Datum nicht."""
        booking, req = self._confirmed()
        booking.write({'contract_signed': True})
        self.assertEqual(req.state, 'canceled')
        self.assertEqual(booking.contract_signed_source, 'paper')
        earlier = self.today - timedelta(days=3)
        booking.write({'contract_signed_date': earlier})
        booking.write({'contract_signed': True})
        self.assertEqual(booking.contract_signed_date, earlier)
        booking.write({'contract_signed': False})
        self.assertFalse(booking.contract_signed_date)
        self.assertFalse(booking.contract_signed_source)

    def test_booking_cancel_and_reset_cancel_request(self):
        """Storno bzw. Zurücksetzen der Buchung storniert die Anfrage."""
        booking, req = self._confirmed()
        booking.action_cancel()
        self.assertEqual(req.state, 'canceled')
        self.assertTrue(self._notes(booking, 'Buchung storniert'))
        booking2, req2 = self._confirmed()
        booking2.action_reset_draft()
        self.assertEqual(req2.state, 'canceled')
        self.assertFalse(booking2.contract_followup_sent,
                         'Nach dem Zurücksetzen wirkt der Papier-Nachfass wieder.')
        self.assertTrue(self._notes(booking2, 'zurückgesetzt'))

    def test_unlink_cancels_request_without_note(self):
        """Löschen der Buchung (Administration) storniert die offene Anfrage."""
        manager = new_test_user(
            self.env, login='kjr_fac_sign_manager', email='verwaltung.test@example.com',
            groups='kjr_facility.group_kjr_facility_manager')
        booking, req = self._confirmed()
        booking.with_user(manager).unlink()
        self.assertEqual(req.state, 'canceled')

    def test_followup_cron_skips_pending(self):
        """Der Papier-Nachfass erinnert nicht, solange die digitale Anfrage läuft."""
        booking, _req = self._confirmed()
        booking.write({'contract_sent_date': self.today - timedelta(days=11)})
        self.Booking._cron_contract_followup()
        self.assertFalse(self._mails('Erinnerung: Vertrag %s' % booking.name))

    def test_orphan_cron(self):
        """Täglicher Lauf storniert Anfragen stornierter bzw. nicht mehr zuständiger Buchungen."""
        booking, req = self._confirmed()
        booking.write({'state': 'cancelled'})
        booking2, req2 = self._confirmed()
        booking2.sudo().write({'kjr_sign_request_id': False})
        booking3, req3 = self._confirmed()
        self.Booking._cron_kjr_facility_sign()
        self.assertEqual(req.state, 'canceled')
        self.assertEqual(req2.state, 'canceled')
        self.assertEqual(req3.state, 'sent', 'Eine gültige Anfrage bleibt unberührt.')
        self.assertTrue(self._notes(booking2, 'nicht mehr zur aktuellen Buchung'))

    def test_orphan_cron_ignores_foreign_requests(self):
        """Andere Anfragen, die mit der Buchung verknüpft sind (z. B. Hausordnung),
        bleiben vom täglichen Lauf und von den Hooks unberührt."""
        booking, req = self._confirmed()
        self.assertTrue(req.kjr_facility_contract)
        signer = req.request_item_ids.partner_id
        foreign = self.SignRequest.with_user(self.sender).sudo().with_context(
            no_sign_mail=True).create({
                'template_id': req.template_id.id,
                'reference': 'Hausordnung',
                'reference_doc': 'kjr.facility.booking,%d' % booking.id,
                'request_item_ids': [(0, 0, {
                    'partner_id': signer.id,
                    'role_id': self.env.ref('kjr_facility_sign.sign_item_role_tenant').id,
                })],
            })
        self.assertFalse(foreign.kjr_facility_contract)
        self.assertFalse(foreign._kjr_facility_reference_booking())
        self.Booking._cron_kjr_facility_sign()
        self.assertEqual(foreign.state, 'sent', 'Fremde Anfrage darf nicht storniert werden.')
        self.assertEqual(req.state, 'sent')
        self.assertFalse(self._notes(booking, 'nicht mehr zur aktuellen Buchung'))
        # Ablehnung der fremden Anfrage wirkt nicht auf die Buchung.
        foreign.request_item_ids[:1].sudo()._refuse('sent', 'Grund')
        self.assertFalse(booking.kjr_sign_refused)
        self.assertEqual(booking.kjr_sign_state, 'sent')
        self.assertFalse(self._notes(booking, 'Unterschrift des Vertrags abgelehnt'))
        # Kopien einer Vertragsanfrage gelten nicht als Vertragsanfrage.
        self.assertFalse(req.sudo().copy_data()[0].get('kjr_facility_contract'))

    # ── Unterzeichner und Absender ──────────────────────────────────────────

    def test_signer_partner_choice(self):
        """Unterzeichner nur aus der eigenen Organisation oder der buchende Portalbenutzer."""
        category = self.env.ref('kjr_facility_sign.partner_category_signer')
        # (a) Kontakt unter der Organisation mit gleicher E-Mail
        contact = self.Partner.create({
            'name': 'Kontakt Leitung', 'parent_id': self.org.id, 'email': CONTACT_EMAIL})
        self.assertEqual(self._booking()._kjr_sign_signer_partner(), contact)
        # (b) Firma selbst mit gleicher E-Mail -> neuer Kontakt unter der Firma
        org2 = self.Partner.create({
            'name': 'Verein Zwei', 'is_company': True, 'email': 'verein.zwei@example.com'})
        booking_b = self._booking(partner_id=org2.id, contact_email='verein.zwei@example.com')
        signer_b = booking_b._kjr_sign_signer_partner()
        self.assertNotEqual(signer_b, org2)
        self.assertEqual(signer_b.parent_id, org2)
        self.assertIn(category, signer_b.category_id)
        self.assertEqual(signer_b.name, CONTACT_NAME)
        self.assertFalse(signer_b.is_company)
        # (c) fremder Kontakt mit gleicher E-Mail wird nicht genommen
        foreign = self.Partner.create({'name': 'Fremd', 'email': 'fremd.test@example.com'})
        org3 = self.Partner.create({'name': 'Verein Drei', 'is_company': True})
        booking_c = self._booking(partner_id=org3.id, contact_email='fremd.test@example.com')
        signer_c = booking_c._kjr_sign_signer_partner()
        self.assertNotEqual(signer_c, foreign)
        self.assertEqual(signer_c.parent_id, org3)
        # (d) buchender Portalbenutzer mit gleicher E-Mail
        portal = new_test_user(
            self.env, login='kjr_fac_sign_portal', email='portal.leitung@example.com',
            groups='base.group_portal')
        portal.partner_id.parent_id = self.org
        booking_d = self._booking(
            env=self.env(user=portal.id, su=True), contact_email='portal.leitung@example.com')
        self.assertEqual(booking_d.create_uid, portal)
        self.assertEqual(booking_d._kjr_sign_signer_partner(), portal.partner_id)

    def test_sender_fallback_and_error(self):
        """Absender: Parameter, sonst verantwortliche Person; ohne E-Mail überall Fehler."""
        responsible = new_test_user(
            self.env, login='kjr_fac_sign_resp', email='verantwortlich.test@example.com',
            groups='base.group_user')
        self.ICP.set_param(PARAM_SENDER, False)
        self.facility.responsible_user_id = responsible
        booking = self._booking()
        self.assertEqual(booking._kjr_sign_sender_user(), responsible)
        # Ohne E-Mail überall: Fehler beim Knopf (kein stiller Rückfall).
        no_mail_user = new_test_user(
            self.env, login='kjr_fac_sign_nomail', email=False,
            groups='kjr_facility.group_kjr_facility_user')
        self.facility.responsible_user_id = False
        admin = self.env.ref('base.user_admin')
        admin.partner_id.email = False
        booking.write({'state': 'confirmed'})
        with self.assertRaises(UserError):
            booking.with_user(no_mail_user).action_kjr_sign_request_send()
        self.assertEqual(booking.kjr_sign_state, 'none')

    # ── Einstellungen und reine Funktionen ──────────────────────────────────

    def test_settings_reminder_zero_stored(self):
        """Erinnerung 0 wird als '0' gespeichert und schaltet die Sign-Erinnerung ab."""
        settings = self.env['res.config.settings'].create({
            'kjr_facility_sign_reminder_days': 0,
        })
        settings.set_values()
        self.assertEqual(self.ICP.get_param(PARAM_REMINDER), '0')
        _booking, req = self._confirmed()
        self.assertFalse(req.reminder_enabled)

    def test_geometry_pure(self):
        """Felder liegen auf der Seite, überlappen nicht und passen zur Zeichnung."""
        for width, height in ((595.28, 841.89), (612.0, 792.0)):
            geos = sign_page.field_geometry(width, height)
            self.assertEqual([g['key'] for g in geos], ['place', 'date', 'signature'])
            for geo, (_key, top, _h) in zip(geos, sign_page.FIELDS):
                self.assertTrue(0 <= geo['posX'] and geo['posX'] + geo['width'] <= 1)
                self.assertTrue(0 <= geo['posY'] and geo['posY'] + geo['height'] <= 1)
                self.assertLessEqual(abs(geo['posY'] * height - top * mm), 0.5 * height / 1000)
            for upper, lower in zip(geos, geos[1:]):
                self.assertLessEqual(upper['posY'] + upper['height'], lower['posY'])
            # Sign stempelt Text mit Schriftgröße Seitenhöhe * height * 0.8 (pt):
            # Ort/Datum dürfen nicht deutlich größer als Fließtext werden.
            for geo in geos:
                if geo['key'] in ('place', 'date'):
                    self.assertLessEqual(height * geo['height'] * 0.8, 12.5)
            texts = {key: 'Test' for key in (
                'title', 'label_facility', 'facility', 'label_period', 'period',
                'label_party', 'party', 'label_company', 'company', 'declaration',
                'label_place', 'label_date', 'label_signature', 'caption', 'footer_page')}
            pdf = sign_page.build_signature_page(width, height, texts)
            reader = PdfFileReader(io.BytesIO(pdf), strict=False)
            self.assertEqual(reader.getNumPages(), 1)
            box = reader.getPage(0).mediaBox
            self.assertAlmostEqual(float(box.getWidth()), width, places=1)
            self.assertAlmostEqual(float(box.getHeight()), height, places=1)

    # ── Portal und Rechte ───────────────────────────────────────────────────

    def test_portal_url_only_for_signer(self):
        """Link zur Unterschrift nur für den Unterzeichner selbst."""
        portal = new_test_user(
            self.env, login='kjr_fac_sign_portal2', email='portal.signer@example.com',
            groups='base.group_portal')
        portal.partner_id.parent_id = self.org
        other = new_test_user(
            self.env, login='kjr_fac_sign_portal3', email='portal.other@example.com',
            groups='base.group_portal')
        other.partner_id.parent_id = self.org
        booking = self._booking(
            env=self.env(user=portal.id, su=True), contact_email='portal.signer@example.com')
        booking = booking.with_env(self.env)
        booking.action_confirm()
        req = booking.sudo().kjr_sign_request_id
        item = req.request_item_ids
        self.assertEqual(item.partner_id, portal.partner_id)
        # Wie im Portal-Controller: Buchung als with_user(SUPERUSER_ID)
        # (_document_check_access), Betrachter kommt aus request.env.user.
        booking_su = booking.with_user(SUPERUSER_ID)
        self.assertEqual(booking_su._kjr_sign_portal_url_for(portal),
                         '/my/signature/%d' % item.id)
        self.assertFalse(booking_su._kjr_sign_portal_url_for(other))
        self.assertFalse(booking_su._kjr_sign_portal_url_for(self.env.ref('base.public_user')))
        self.assertFalse(booking_su._kjr_sign_portal_url_for(booking_su.env.user))

    def test_buttons_access(self):
        """Ohne Einrichtungsgruppe: kein Zugriff auf die Knöpfe."""
        employee = new_test_user(
            self.env, login='kjr_fac_sign_employee', email='mitarbeit.test@example.com',
            groups='base.group_user')
        booking, _req = self._confirmed()
        with self.assertRaises(AccessError):
            booking.with_user(employee).action_kjr_contract_paper()
        with self.assertRaises(AccessError):
            booking.with_user(employee).action_kjr_sign_request_cancel()

    def test_open_request_button_non_sender(self):
        """Smart-Button: einfacher Sign-Benutzer, der nicht Absender ist, bekommt einen
        klaren Hinweis statt eines Zugriffsfehlers; Absender und Sign-Admin öffnen."""
        booking, req = self._confirmed()
        sign_user = new_test_user(
            self.env, login='kjr_fac_sign_signuser', email='signuser.test@example.com',
            groups='kjr_facility.group_kjr_facility_user,sign.group_sign_user')
        with self.assertRaises(UserError):
            booking.with_user(sign_user).action_kjr_open_sign_request()
        sign_manager = new_test_user(
            self.env, login='kjr_fac_sign_signmgr', email='signmgr.test@example.com',
            groups='kjr_facility.group_kjr_facility_user,sign.group_sign_manager')
        action = booking.with_user(sign_manager).action_kjr_open_sign_request()
        self.assertEqual(action['res_id'], req.id)
