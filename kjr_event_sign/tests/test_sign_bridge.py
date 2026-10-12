# -*- coding: utf-8 -*-
"""Tests der Brücke Veranstaltungen ↔ E-Signatur (kjr_event_sign).

Grundlage ist die mitgelieferte Standardvorlage (seit 19.0.1.1.0 die
vorbefüllte Vorlage ``kjr_event_sign.sign_template_consent_v2``; die alte
Vorlage v1 ``sign_template_consent`` nur in eigens gekennzeichneten Tests).
Gesperrte Anmeldungen entstehen wie
auf der Website über den Kontext ``kjr_consent_hold_event_id`` (kjr_event).
Mails von Odoo Sign entstehen im Testmodus als mail.mail und werden nicht
versendet. ``_send_completed_documents`` wird beim Unterschreiben gemockt,
damit kein PDF erzeugt werden muss.
"""
import base64
from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user

from odoo.addons.kjr_event_sign.models import event_registration as bridge_registration
from odoo.addons.kjr_event_sign.models.event_event import (
    TEMPLATE_V1_LEGACY_NAME,
    TEMPLATE_V1_SHIPPED_NAME,
)

LOGGER_EVENT = 'odoo.addons.kjr_event_sign.models.event_event'
PARAM_DEFAULT_TEMPLATE = 'kjr_event_sign.default_template_id'
GUARDIAN = 'Erika Elternteil'

# 1x1-PNG, gültiges Base64 für das Unterschriftsfeld
PNG_1X1 = (
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA'
    '60e6kgAAAABJRU5ErkJggg==')


@tagged('post_install', '-at_install')
class TestKjrEventSignBridge(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Event = cls.env['event.event']
        cls.Registration = cls.env['event.registration']
        cls.SignRequest = cls.env['sign.request']
        cls.ICP = cls.env['ir.config_parameter'].sudo()
        cls.template = cls.env.ref('kjr_event_sign.sign_template_consent_v2')
        cls.template_v1 = cls.env.ref('kjr_event_sign.sign_template_consent')
        cls.sender = new_test_user(
            cls.env, login='kjr_sign_sender', name='Geschäftsstelle Test',
            email='geschaeftsstelle.test@example.com',
            groups='base.group_user,event.group_event_user')
        cls.ICP.set_param('kjr_event_sign.enabled', 'True')
        cls.ICP.set_param('kjr_event_sign.sender_user_id', str(cls.sender.id))
        begin = fields.Datetime.now().replace(microsecond=0) + timedelta(days=30)
        cls.event = cls.Event.create({
            'name': 'Sommerfreizeit Test',
            'date_begin': begin,
            'date_end': begin + timedelta(days=5),
            'kjr_event_type': 'ferienprogramm',
            'requires_parental_consent': True,
        })
        cls.child_birthdate = (begin - timedelta(days=365 * 10)).date()

    # ── Hilfen ──────────────────────────────────────────────────────────────

    def _held_registration(self, **kw):
        """Gesperrte Anmeldung eines minderjährigen Kindes (wie Website).

        Mit Namen der/des Erziehungsberechtigten: die Website verlangt ihn im
        Verfahren 'sign' (kjr_event 19.0.5.10.0), die Vorlage v2 übernimmt ihn.
        ``guardian_name=False`` bildet ältere bzw. Backend-Anmeldungen ab.
        """
        vals = {
            'event_id': self.event.id,
            'name': 'Kind Mustername',
            'email': 'eltern.test@example.com',
            'birthdate': self.child_birthdate,
            'guardian_name': GUARDIAN,
        }
        vals.update(kw)
        reg = self.Registration.with_context(
            kjr_consent_hold_event_id=self.event.id).create(vals)
        self.assertTrue(reg.kjr_consent_hold, 'Voraussetzung: Anmeldung ist gesperrt.')
        return reg

    def _started(self, **kw):
        reg = self._held_registration(**kw)
        reg._kjr_consent_request_start()
        req = self.SignRequest.browse(reg.sudo().kjr_sign_request_id.id)
        self.assertTrue(req, 'Es muss eine Unterschriftsanfrage entstanden sein.')
        return reg, req

    def _sign_values(self, req):
        values = {}
        for item in req.template_id.sign_item_ids:
            if item.constant:
                # Schreibgeschützt und schon beim Anlegen gefüllt; Odoo Sign
                # lehnt einen abweichenden Wert ab (sign.request.item.value.write).
                continue
            item_type = item.type_id.item_type
            if item_type == 'signature':
                values[str(item.id)] = 'data:image/png;base64,' + PNG_1X1
            elif item_type == 'checkbox':
                values[str(item.id)] = 'on'
            else:
                values[str(item.id)] = 'Testwert'
        return values

    def _sign(self, req):
        item = req.request_item_ids[:1]
        with patch.object(type(self.SignRequest), '_send_completed_documents', autospec=True):
            item.sudo().sign(self._sign_values(req))

    def _notes(self, reg, text):
        return reg.message_ids.filtered(lambda m: text in (m.body or ''))

    # ── Modus ───────────────────────────────────────────────────────────────

    def test_mode_sign_only_when_enabled_and_template_valid(self):
        """'sign' nur mit eingeschaltetem Parameter und gültiger Vorlage."""
        self.assertTrue(self.Event._kjr_consent_template_ok(self.template))
        self.assertEqual(self.event._kjr_consent_mode(), 'sign')
        self.assertEqual(self.event.kjr_consent_mode, 'sign')
        self.ICP.set_param('kjr_event_sign.enabled', False)
        self.assertEqual(self.event._kjr_consent_mode(), 'checkbox',
                         'Ohne Parameter bleibt es bei der Bestätigung im Formular.')
        self.ICP.set_param('kjr_event_sign.enabled', 'True')
        self.event.requires_parental_consent = False
        self.assertEqual(self.event._kjr_consent_mode(), 'none')

    def test_invalid_template_two_roles_falls_back_to_checkbox(self):
        """Eine Vorlage mit zwei Rollen ist ungültig: Rückfall auf 'checkbox'."""
        attachment = self.env['ir.attachment'].create({
            'name': 'zwei_rollen.pdf',
            'raw': base64.b64decode(self.template.document_ids[:1].datas),
        })
        template = self.env['sign.template'].create({'name': 'Zwei Rollen'})
        document = self.env['sign.document'].create({
            'attachment_id': attachment.id, 'template_id': template.id})
        role_a = self.env['sign.item.role'].create({'name': 'Rolle A'})
        role_b = self.env['sign.item.role'].create({'name': 'Rolle B'})
        signature_type = self.env.ref('sign.sign_item_type_signature')
        self.env['sign.item'].create([{
            'document_id': document.id, 'type_id': signature_type.id,
            'responsible_id': role.id, 'page': 1, 'posX': 0.1, 'posY': y,
            'width': 0.2, 'height': 0.05,
        } for role, y in ((role_a, 0.1), (role_b, 0.5))])
        self.assertFalse(self.Event._kjr_consent_template_ok(template))
        self.event.kjr_consent_sign_template_id = template
        # Der Modus wird bei jedem Zugriff berechnet: dort keine WARNING (sonst
        # flutet die ungültige Vorlage das Protokoll), nur auf Wunsch (log=True).
        with self.assertNoLogs(LOGGER_EVENT, level='WARNING'):
            self.assertEqual(self.event._kjr_consent_mode(), 'checkbox')
            self.assertEqual(self.event.kjr_consent_mode, 'checkbox')
        with self.assertLogs(LOGGER_EVENT, level='WARNING'):
            self.Event._kjr_consent_template_ok(template, log=True)

    # ── Anfrage anlegen ─────────────────────────────────────────────────────

    def test_request_start_creates_sign_request(self):
        """Anfrage verweist auf die Anmeldung, Absender ist der Ersteller,
        Gültigkeit endet vor Beginn, kein Kindsname in Referenz und Betreff."""
        reg, req = self._started()
        self.assertEqual(req.reference_doc, reg)
        self.assertEqual(req.create_uid, self.sender)
        self.assertEqual(req.state, 'sent')
        self.assertTrue(req.validity)
        self.assertLess(req.validity, reg.sudo()._kjr_sign_event_begin_date())
        self.assertGreater(req.validity, fields.Date.context_today(reg))
        self.assertNotIn('Mustername', req.reference)
        self.assertNotIn('Mustername', req.subject or '')
        self.assertIn(str(reg.id), req.reference)
        self.assertTrue(req.reminder_enabled)
        self.assertEqual(req.reminder, 3)
        self.assertEqual(reg.kjr_sign_state, 'sent')
        self.assertFalse(reg.kjr_sign_error)
        self.assertEqual(req.communication_company_id, self.event.company_id)

    def test_partner_reused_for_same_email_and_name(self):
        """Ein Kontakt mit derselben E-Mail UND demselben Namen (ohne Groß-/
        Kleinschreibung, Leerraum egal) wird wiederverwendet, nicht umbenannt."""
        existing = self.env['res.partner'].create({
            'name': 'Erika  Elternteil', 'email': 'Eltern.Test@Example.com'})
        reg, req = self._started(guardian_name=' erika ELTERNTEIL ')
        self.assertEqual(req.request_item_ids.partner_id, existing)
        self.assertEqual(existing.name, 'Erika  Elternteil')
        category = self.env.ref('kjr_event_sign.partner_category_guardian')
        self.assertNotIn(category, existing.category_id)

    def test_partner_same_email_other_name_gets_new_contact(self):
        """Gleiche E-Mail, anderer Name: neuer Kontakt mit dem Namen der/des
        Erziehungsberechtigten; der bestehende bleibt unverändert."""
        existing = self.env['res.partner'].create({
            'name': 'Bestehender Kontakt', 'email': 'Eltern.Test@Example.com'})
        reg, req = self._started(guardian_name='Anderer Name')
        partner = req.request_item_ids.partner_id
        self.assertNotEqual(partner, existing)
        self.assertEqual(partner.name, 'Anderer Name')
        self.assertEqual(partner.email_normalized, 'eltern.test@example.com')
        self.assertIn(self.env.ref('kjr_event_sign.partner_category_guardian'),
                      partner.category_id)
        self.assertEqual(existing.name, 'Bestehender Kontakt')

    def test_partner_is_never_the_child_contact(self):
        """Die Website legt den Kontakt der Anmeldung mit dem Namen des Kindes
        an. Er wird nicht Unterzeichner, auch wenn die E-Mail passt; die
        Sign-Mail spricht damit nicht das Kind an."""
        child_contact = self.env['res.partner'].create({
            'name': 'Kind Mustername', 'email': 'eltern.test@example.com'})
        reg, req = self._started(partner_id=child_contact.id)
        partner = req.request_item_ids.partner_id
        self.assertNotEqual(partner, child_contact)
        self.assertEqual(partner.name, GUARDIAN)
        self.assertEqual(child_contact.name, 'Kind Mustername')

    def test_partner_without_guardian_name_skips_child_contact(self):
        """Ohne Namen der Eltern (Vorlage ohne Vorbefüllung, z. B. v1): nie der
        Kind-Kontakt, sondern ein neuer Kontakt mit der E-Mail als Name."""
        self.event.kjr_consent_sign_template_id = self.template_v1
        child_contact = self.env['res.partner'].create({
            'name': 'Kind Mustername', 'email': 'eltern.test@example.com'})
        reg, req = self._started(partner_id=child_contact.id, guardian_name=False)
        partner = req.request_item_ids.partner_id
        self.assertNotEqual(partner, child_contact)
        self.assertEqual(partner.name, 'eltern.test@example.com')
        # Ein anders benannter Kontakt mit der Adresse wird dagegen wie bisher
        # wiederverwendet.
        other = self.env['res.partner'].create({
            'name': 'Eltern Kontakt', 'email': 'zweite.eltern@example.com'})
        reg2, req2 = self._started(email='zweite.eltern@example.com', guardian_name=False)
        self.assertEqual(req2.request_item_ids.partner_id, other)

    def test_new_partner_gets_category(self):
        """Ein neu angelegter Eltern-Kontakt trägt die Kategorie."""
        reg, req = self._started(
            email='kind.selbst@example.com',
            guardian_email='neue.eltern.kjr@example.com',
            guardian_name='Erika Elternteil')
        partner = req.request_item_ids.partner_id
        self.assertEqual(partner.email_normalized, 'neue.eltern.kjr@example.com')
        self.assertEqual(partner.name, 'Erika Elternteil')
        self.assertIn(self.env.ref('kjr_event_sign.partner_category_guardian'),
                      partner.category_id)

    def test_double_start_creates_no_second_request(self):
        """Ein zweiter Aufruf bei offener Anfrage legt keine weitere an."""
        reg, req = self._started()
        reg._kjr_consent_request_start()
        self.assertEqual(reg.sudo().kjr_sign_request_id, req)
        self.assertEqual(self.SignRequest.search_count(
            [('reference_doc', '=', 'event.registration,%d' % reg.id)]), 1)

    def test_sender_without_email_sets_error_without_raise(self):
        """Ohne Absender mit E-Mail: Fehlermerker, Aktivität, kein Abbruch."""
        no_mail = new_test_user(self.env, login='kjr_sign_nomail', groups='base.group_user')
        no_mail.partner_id.email = False
        self.ICP.set_param('kjr_event_sign.sender_user_id', str(no_mail.id))
        self.event.user_id = no_mail
        self.env.ref('base.user_admin').partner_id.email = False
        reg = self._held_registration()
        reg._kjr_consent_request_start()
        self.assertFalse(reg.sudo().kjr_sign_request_id)
        self.assertTrue(reg.kjr_sign_error)
        self.assertEqual(reg.kjr_sign_attempts, 1)
        self.assertTrue(reg.activity_ids, 'Die Geschäftsstelle muss eine Aktivität bekommen.')
        self.assertTrue(reg.kjr_consent_hold)

    # ── Unterschrift ────────────────────────────────────────────────────────

    def test_sign_releases_registration(self):
        """Unterschrift setzt die Einwilligung und gibt die Anmeldung frei."""
        reg, req = self._started()
        self._sign(req)
        self.assertEqual(req.state, 'signed')
        self.assertTrue(reg.parental_consent)
        self.assertEqual(reg.kjr_consent_source, 'sign')
        self.assertFalse(reg.kjr_consent_hold)
        self.assertEqual(reg.state, 'open')
        self.assertEqual(reg.kjr_sign_state, 'signed')

    def test_stale_request_has_no_effect(self):
        """Eine Anfrage, die nicht (mehr) die aktuelle ist, bewirkt nichts."""
        reg, req = self._started()
        reg.sudo().write({'kjr_sign_request_id': False})
        self._sign(req)
        self.assertEqual(req.state, 'signed')
        self.assertFalse(reg.parental_consent)
        self.assertTrue(reg.kjr_consent_hold)

    def test_release_error_does_not_break_sign(self):
        """Ein Fehler in der Freigabe bricht die Unterschrift nicht ab."""
        reg, req = self._started()
        with patch.object(type(self.Registration), '_kjr_consent_release_one',
                          autospec=True, side_effect=UserError('Testfehler')):
            self._sign(req)
        self.assertEqual(req.state, 'signed')
        self.assertTrue(reg.parental_consent,
                        'Die Einwilligung bleibt gespeichert, auch wenn die Freigabe scheitert.')
        self.assertTrue(reg.kjr_consent_hold)

    # ── Ablehnung und Storno ────────────────────────────────────────────────

    def test_refuse_marks_registration_once(self):
        """Ablehnung: Merker, genau EINE Notiz, Sperre bleibt, keine Begründung."""
        reg, req = self._started()
        item = req.request_item_ids[:1]
        item.sudo()._refuse('sent', 'Geheime Begründung der Eltern')
        self.assertEqual(req.state, 'canceled')
        self.assertTrue(reg.kjr_sign_refused)
        self.assertEqual(reg.kjr_sign_state, 'refused')
        self.assertTrue(reg.kjr_consent_hold)
        self.assertEqual(len(self._notes(reg, 'Unterschrift abgelehnt.')), 1)
        self.assertFalse(self._notes(reg, 'Unterschriftsanfrage storniert'),
                         'Der cancel-Hook darf bei der Ablehnung keine zweite Notiz schreiben.')
        self.assertFalse(self._notes(reg, 'Geheime Begründung'))

    def test_paper_consent_cancels_open_request(self):
        """Papier-Einwilligung storniert die offene Anfrage."""
        reg, req = self._started()
        reg.action_kjr_consent_paper()
        self.assertEqual(req.state, 'canceled')
        self.assertTrue(reg.parental_consent)
        self.assertEqual(reg.kjr_consent_source, 'paper')
        self.assertEqual(len(self._notes(reg, 'Einwilligung liegt auf Papier vor')), 1)

    def test_registration_cancel_cancels_request(self):
        """Absage der Anmeldung storniert die offene Anfrage."""
        reg, req = self._started()
        reg.action_cancel()
        self.assertEqual(reg.state, 'cancel')
        self.assertEqual(req.state, 'canceled')

    def test_cron_cancels_request_of_deleted_registration(self):
        """Cron c): Anfrage einer per Kaskade gelöschten Anmeldung wird storniert."""
        reg, req = self._started()
        self.env.flush_all()
        # Löschen ohne ORM (wie die Datenbank-Kaskade beim Löschen der
        # Veranstaltung): der unlink-Hook der Brücke greift dabei nicht.
        self.env.cr.execute('DELETE FROM event_registration WHERE id = %s', (reg.id,))
        self.env.invalidate_all()
        self.Registration._cron_kjr_event_sign()
        self.assertEqual(req.state, 'canceled')

    def test_cron_followup_activity_once(self):
        """Cron b): abgelaufene Anfrage bekommt einmalig eine Aktivität."""
        reg, req = self._started()
        req.sudo().state = 'expired'
        self.assertEqual(reg.kjr_sign_state, 'expired')
        self.Registration._cron_kjr_event_sign()
        self.assertTrue(reg.kjr_sign_followup_done)
        count = len(reg.activity_ids)
        self.assertTrue(count)
        self.Registration._cron_kjr_event_sign()
        self.assertEqual(len(reg.activity_ids), count)

    # ── Signierlink ─────────────────────────────────────────────────────────

    def test_action_url_only_when_sent(self):
        """Der Signierlink existiert nur, solange die Anfrage offen ist."""
        reg, req = self._started()
        reg.invalidate_recordset(['kjr_consent_action_url'])
        self.assertIn('/sign/document/mail/%d/' % req.id, reg.kjr_consent_action_url or '')
        reg.action_kjr_sign_request_cancel()
        reg.invalidate_recordset(['kjr_consent_action_url'])
        self.assertEqual(req.state, 'canceled')
        self.assertFalse(reg.kjr_consent_action_url)

    # ── Einstellungen ───────────────────────────────────────────────────────

    def test_settings_store_parameters(self):
        """Die Einstellungen schreiben die Systemparameter (0 bleibt 0)."""
        settings = self.env['res.config.settings'].create({
            'kjr_event_sign_enabled': True,
            'kjr_event_sign_template_id': self.template.id,
            'kjr_event_sign_sender_id': self.sender.id,
            'kjr_event_sign_validity_days': 10,
            'kjr_event_sign_reminder_days': 0,
        })
        settings.execute()
        self.assertTrue(self.ICP.get_param('kjr_event_sign.enabled'))
        self.assertEqual(self.ICP.get_param('kjr_event_sign.default_template_id'),
                         str(self.template.id))
        self.assertEqual(self.ICP.get_param('kjr_event_sign.sender_user_id'), str(self.sender.id))
        self.assertEqual(self.ICP.get_param('kjr_event_sign.validity_days'), '10')
        self.assertEqual(self.ICP.get_param('kjr_event_sign.reminder_days'), '0')
        self.assertFalse(settings.kjr_event_sign_template_warning)
        reg, req = self._started()
        self.assertFalse(req.reminder_enabled)

    # ── Nachbesserungen (Review) ────────────────────────────────────────────

    def test_refused_request_not_restarted_automatically(self):
        """Nach der Ablehnung startet der automatische Aufruf (z. B. Auftrag
        'sent' -> 'sale') keine neue Anfrage; nur die Schaltfläche tut das."""
        reg, req = self._started()
        req.request_item_ids[:1].sudo()._refuse('sent', 'Nein')
        reg._kjr_consent_request_start()
        self.assertEqual(reg.sudo().kjr_sign_request_id, req)
        self.assertTrue(reg.kjr_sign_refused, 'Die Ablehnung bleibt im Stand sichtbar.')
        self.assertEqual(reg.kjr_sign_state, 'refused')
        reg.action_kjr_sign_request_send()
        new_req = reg.sudo().kjr_sign_request_id
        self.assertNotEqual(new_req, req)
        self.assertEqual(new_req.state, 'sent')
        self.assertEqual(reg.kjr_sign_state, 'sent')

    def test_canceled_request_not_restarted_automatically(self):
        """Nach bewusstem Storno durch die Geschäftsstelle kein Neuversand von selbst."""
        reg, req = self._started()
        reg.action_kjr_sign_request_cancel()
        reg._kjr_consent_request_start()
        self.assertEqual(reg.sudo().kjr_sign_request_id, req)
        self.assertEqual(reg.kjr_sign_state, 'canceled')

    def test_cron_orphans_found_beyond_batch_limit(self):
        """Cron c): Waisen werden auch gefunden, wenn mehr offene Anfragen zu
        lebenden Anmeldungen (mit kleinerer ID) existieren als das Limit."""
        reg_alive, req_alive = self._started()
        reg_orphan, req_orphan = self._started(email='andere.eltern@example.com')
        self.assertLess(req_alive.id, req_orphan.id)
        self.env.flush_all()
        self.env.cr.execute('UPDATE event_registration SET state = %s WHERE id = %s',
                            ('cancel', reg_orphan.id))
        self.env.invalidate_all()
        with patch.object(bridge_registration, 'CRON_BATCH_LIMIT', 1):
            self.Registration._cron_kjr_event_sign()
        self.assertEqual(req_orphan.state, 'canceled')
        self.assertEqual(req_alive.state, 'sent')

    def test_cron_no_followup_when_consent_present(self):
        """Cron b): Liegt die Einwilligung auf Papier vor und bleibt die Anmeldung
        nur gesperrt (kein Platz bzw. Freigabe gescheitert), keine Aktivität
        "Unterschrift abgelaufen oder abgelehnt"."""
        reg, req = self._started()
        with patch.object(type(self.Registration), '_kjr_consent_release_one',
                          autospec=True, side_effect=UserError('Kein Platz')):
            reg.action_kjr_consent_paper()
        self.assertTrue(reg.parental_consent)
        self.assertTrue(reg.kjr_consent_hold)
        self.assertEqual(req.state, 'canceled')
        self.Registration._cron_kjr_event_sign()
        self.assertFalse(reg.activity_ids.filtered(
            lambda a: a.summary == 'Unterschrift abgelaufen oder abgelehnt'))

    def test_email_change_cancels_and_resends(self):
        """Korrigierte Eltern-Adresse: alte Anfrage storniert, neue an die neue Adresse."""
        reg, req = self._started()
        reg.write({'guardian_email': 'korrigiert.eltern@example.com'})
        self.assertEqual(req.state, 'canceled')
        new_req = reg.sudo().kjr_sign_request_id
        self.assertTrue(new_req)
        self.assertNotEqual(new_req, req)
        self.assertEqual(new_req.request_item_ids.signer_email, 'korrigiert.eltern@example.com')
        self.assertEqual(len(self._notes(reg, 'E-Mail-Adresse geändert')), 1)

    def test_action_url_empty_for_other_recipient(self):
        """Kein Signierlink, wenn der Unterzeichner nicht der aktuelle Empfänger ist."""
        reg, req = self._started()
        # Ohne Hook (direkt in der Datenbank), damit die Anfrage offen bleibt.
        self.env.flush_all()
        self.env.cr.execute('UPDATE event_registration SET guardian_email = %s WHERE id = %s',
                            ('jemand.anders@example.com', reg.id))
        self.env.invalidate_all()
        self.assertEqual(req.state, 'sent')
        self.assertFalse(reg.kjr_consent_action_url)

    def test_cancel_note_ignores_context_free_text(self):
        """Der cancel-Hook übernimmt keinen Freitext aus dem Kontext."""
        reg, req = self._started()
        req.with_context(kjr_sign_cancel_note='Fremdtext',
                         kjr_sign_cancel_reason='<b>unbekannt</b>').cancel()
        self.assertFalse(self._notes(reg, 'Fremdtext'))
        self.assertFalse(self._notes(reg, 'unbekannt'))
        self.assertEqual(len(self._notes(reg, 'Unterschriftsanfrage storniert.')), 1)

    def test_sign_does_not_reactivate_cancelled_registration(self):
        """Unterschrift zu einer (per Compute) abgesagten Anmeldung: bleibt abgesagt."""
        reg, req = self._started()
        self.env.flush_all()
        self.env.cr.execute('UPDATE event_registration SET state = %s WHERE id = %s',
                            ('cancel', reg.id))
        self.env.invalidate_all()
        self._sign(req)
        self.assertEqual(req.state, 'signed')
        self.assertEqual(reg.state, 'cancel')
        self.assertFalse(reg.parental_consent)
        self.assertTrue(reg.activity_ids.filtered(
            lambda a: a.summary == 'Einwilligung zu abgesagter Anmeldung unterschrieben'))

    def test_partner_prefers_contact_with_user(self):
        """Mehrere Kontakte mit derselben Adresse: der mit Benutzerkonto gewinnt."""
        email = 'konto.eltern@example.com'
        self.env['res.partner'].create({'name': GUARDIAN, 'email': email,
                                        'is_company': True})
        self.env['res.partner'].create({'name': GUARDIAN, 'email': email})
        portal = new_test_user(self.env, login='kjr_sign_portal_eltern', email=email,
                               name=GUARDIAN, groups='base.group_portal')
        reg, req = self._started(email=email)
        self.assertEqual(req.request_item_ids.partner_id, portal.partner_id)

    # ── Abgesagte Anmeldungen ───────────────────────────────────────────────

    def test_cancelled_registration_gets_no_request(self):
        """Abgesagte Anmeldung: weder Schaltfläche noch direkter Aufruf fragen an."""
        reg = self._held_registration()
        reg.action_cancel()
        self.assertEqual(reg.state, 'cancel')
        result = reg.action_kjr_sign_request_send()
        self.assertEqual(result['params']['type'], 'warning')
        result = reg.action_kjr_sign_request_resend()
        self.assertEqual(result['params']['type'], 'warning')
        reg.with_context(kjr_sign_force=True)._kjr_consent_request_start()
        self.assertFalse(reg.sudo().kjr_sign_request_id)
        self.assertFalse(self.SignRequest.search_count(
            [('reference_doc', '=', 'event.registration,%d' % reg.id)]))
        self.assertFalse(reg.kjr_sign_error)

    # ── Rückfall ohne aktive Brücke ─────────────────────────────────────────

    def test_request_start_falls_back_when_bridge_disabled(self):
        """Brücke ausgeschaltet: Aktivität aus kjr_event, kein Fehlermerker."""
        reg = self._held_registration()
        self.ICP.set_param('kjr_event_sign.enabled', False)
        reg._kjr_consent_request_start()
        self.assertFalse(reg.sudo().kjr_sign_request_id)
        self.assertFalse(reg.kjr_sign_error)
        self.assertEqual(reg.kjr_sign_attempts, 0)
        summaries = reg.activity_ids.mapped('summary')
        self.assertIn('Einwilligung einholen', summaries)
        self.assertNotIn('Unterschriftsanfrage konnte nicht versendet werden', summaries)
        self.assertTrue(reg.kjr_consent_hold)

    def test_cron_retry_only_in_sign_mode(self):
        """Cron a) wiederholt nur bei Veranstaltungen im Modus 'sign'."""
        reg = self._held_registration()
        reg.sudo().write({'kjr_sign_error': True, 'kjr_sign_attempts': 1})
        self.ICP.set_param('kjr_event_sign.enabled', False)
        self.Registration._cron_kjr_event_sign()
        self.assertFalse(reg.sudo().kjr_sign_request_id)
        self.assertEqual(reg.kjr_sign_attempts, 1)
        self.ICP.set_param('kjr_event_sign.enabled', 'True')
        self.Registration._cron_kjr_event_sign()
        self.assertTrue(reg.sudo().kjr_sign_request_id)

    # ── Fehlerzähler ────────────────────────────────────────────────────────

    def test_success_resets_attempts(self):
        """Erfolgreicher Versand setzt den Fehlerzähler zurück."""
        reg = self._held_registration()
        reg.sudo().write({'kjr_sign_error': True, 'kjr_sign_attempts': 3})
        reg.with_context(kjr_sign_force=True)._kjr_consent_request_start()
        self.assertTrue(reg.sudo().kjr_sign_request_id)
        self.assertFalse(reg.kjr_sign_error)
        self.assertEqual(reg.kjr_sign_attempts, 0)

    # ── Rechte der Schaltflächen ────────────────────────────────────────────

    def test_buttons_require_event_user(self):
        """Registrierungstheke und Portal-Kooperationspartner: AccessError."""
        reg, req = self._started()
        desk = new_test_user(
            self.env, login='kjr_sign_desk',
            groups='base.group_user,event.group_event_registration_desk')
        coop = new_test_user(
            self.env, login='kjr_sign_coop',
            groups='base.group_portal,kjr_event.group_kjr_cooperation_partner')
        self.event.write({'cooperation_user_ids': [Command.link(coop.id)]})
        for user in (desk, coop):
            for method in ('action_kjr_sign_request_send',
                           'action_kjr_sign_request_resend',
                           'action_kjr_sign_request_cancel'):
                with self.assertRaises(AccessError, msg='%s als %s' % (method, user.login)):
                    getattr(reg.with_user(user), method)()
        self.assertEqual(req.state, 'sent')
        self.assertEqual(self.SignRequest.search_count(
            [('reference_doc', '=', 'event.registration,%d' % reg.id)]), 1)

    # ── Datenschutz: unterschriebenes PDF ───────────────────────────────────

    def test_signed_pdf_not_attached_to_registration(self):
        """Nach der Unterschrift hängt kein PDF an der Anmeldung; die Anfrage
        behält das fertige Dokument als Nachweis."""
        reg, req = self._started()
        document = req.template_id.document_ids[:1]

        def fake_send(sign_request):
            # Nachbildung von Odoo Sign: fertiges Dokument an der Anfrage und
            # Nachricht "fully signed" mit Anhang an der Anmeldung.
            sreq = sign_request.sudo()
            self.env['sign.completed.document'].sudo().create({
                'sign_request_id': sreq.id,
                'document_id': document.id,
                'file': document.datas,
            })
            attachment = self.env['ir.attachment'].sudo().create({
                'name': document.name,
                'datas': document.datas,
                'res_model': 'sign.request',
                'res_id': sreq.id,
            })
            sreq.completed_document_attachment_ids = [Command.link(attachment.id)]
            sreq.reference_doc.message_post(
                body='The document has been fully signed.', attachment_ids=attachment.ids)

        item = req.request_item_ids[:1]
        with patch.object(type(self.SignRequest), '_send_completed_documents',
                          autospec=True, side_effect=fake_send):
            item.sudo().sign(self._sign_values(req))
        self.assertEqual(req.state, 'signed')
        self.assertTrue(reg.parental_consent)
        # Nur das unterschriebene Dokument prüfen: die Freigabe kann andere
        # Anhänge erzeugen (z. B. Ticket der Anmeldebestätigung).
        signed_pdfs = req.sudo().completed_document_attachment_ids
        self.assertTrue(signed_pdfs)
        self.assertFalse(self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'event.registration'), ('res_id', '=', reg.id),
            ('name', '=', document.name)]),
            'Die Kopie des unterschriebenen PDF darf nicht an der Anmeldung hängen.')
        self.assertFalse(reg.sudo().message_ids.attachment_ids & signed_pdfs,
                         'Keine Nachricht der Anmeldung darf das PDF tragen.')
        self.assertTrue(self._notes(reg, 'fully signed'),
                        'Die Nachricht selbst bleibt, nur ohne Anhang.')
        self.assertTrue(req.sudo().completed_document_ids)

    # ── Archivierte Anmeldungen wie abgesagte ───────────────────────────────

    def test_archive_cancels_open_request(self):
        """Archivieren der Anmeldung storniert die offene Anfrage."""
        reg, req = self._started()
        reg.action_archive()
        self.assertFalse(reg.active)
        self.assertEqual(req.state, 'canceled')

    def test_cron_cancels_request_of_archived_registration(self):
        """Cron c): Anfrage einer (ohne Hook) archivierten Anmeldung wird storniert."""
        reg, req = self._started()
        self.env.flush_all()
        self.env.cr.execute('UPDATE event_registration SET active = FALSE WHERE id = %s',
                            (reg.id,))
        self.env.invalidate_all()
        self.Registration._cron_kjr_event_sign()
        self.assertEqual(req.state, 'canceled')

    def test_sign_does_not_release_archived_registration(self):
        """Unterschrift zu einer archivierten Anmeldung: keine Freigabe, Aktivität."""
        reg, req = self._started()
        self.env.flush_all()
        self.env.cr.execute('UPDATE event_registration SET active = FALSE WHERE id = %s',
                            (reg.id,))
        self.env.invalidate_all()
        self._sign(req)
        self.assertEqual(req.state, 'signed')
        self.assertFalse(reg.active)
        self.assertFalse(reg.parental_consent)
        self.assertTrue(reg.kjr_consent_hold)
        self.assertNotEqual(reg.state, 'open')
        self.assertTrue(reg.activity_ids.filtered(
            lambda a: a.summary == 'Einwilligung zu archivierter Anmeldung unterschrieben'))

    def test_archived_registration_gets_no_request(self):
        """Archivierte Anmeldungen bekommen auch über die Schaltfläche keine Anfrage."""
        reg = self._held_registration()
        reg.action_archive()
        reg.with_context(kjr_sign_force=True)._kjr_consent_request_start()
        self.assertFalse(reg.sudo().kjr_sign_request_id)
        self.assertEqual(self.SignRequest.search_count(
            [('reference_doc', '=', 'event.registration,%d' % reg.id)]), 0)

    # ── Rechte: Empfängerwechsel und Herkunft 'sign' ────────────────────────

    def test_desk_email_change_does_not_resend(self):
        """Registrierungstheke ändert die Anmelde-E-Mail (ohne Eltern-Adresse):
        die offene Anfrage wird nur storniert, KEINE neue Anfrage an die neue
        Adresse; stattdessen Aktivität für die Geschäftsstelle."""
        reg, req = self._started()
        self.assertFalse(reg.sudo().guardian_email,
                         'Voraussetzung: Empfänger ist die Anmelde-E-Mail.')
        desk = new_test_user(
            self.env, login='kjr_sign_desk_email',
            groups='base.group_user,event.group_event_registration_desk')
        reg.with_user(desk).write({'email': 'theke.eigene@example.com'})
        self.assertEqual(req.state, 'canceled')
        self.assertEqual(reg.sudo().kjr_sign_request_id, req,
                         'Es darf keine neue Anfrage entstanden sein.')
        self.assertEqual(self.SignRequest.search_count(
            [('reference_doc', '=', 'event.registration,%d' % reg.id)]), 1)
        self.assertFalse(self.env['sign.request.item'].sudo().search_count(
            [('partner_id.email_normalized', '=', 'theke.eigene@example.com')]))
        self.assertTrue(reg.kjr_consent_hold)
        self.assertTrue(reg.activity_ids.filtered(
            lambda a: a.summary == 'Unterschriftsanfrage neu senden'))

    def test_rpc_sign_context_counts_as_paper(self):
        """Kontext kjr_consent_source='sign' ohne sudo: kjr_event bucht Papier,
        die Brücke storniert die offene Anfrage."""
        reg, req = self._started()
        reg.with_user(self.sender).with_context(kjr_consent_source='sign').write(
            {'parental_consent': True})
        self.assertTrue(reg.parental_consent)
        self.assertNotEqual(reg.kjr_consent_source, 'sign')
        self.assertEqual(req.state, 'canceled')
        self.assertEqual(len(self._notes(reg, 'Einwilligung liegt auf Papier vor')), 1)

    # ── Vorbefüllung aus der Anmeldung (19.0.1.1.0, Vorlage v2) ─────────────

    def _item_values(self, req):
        return {value.sign_item_id: value.value
                for value in req.request_item_ids.sudo().sign_item_value_ids}

    def test_v2_is_default_template(self):
        """Ohne Vorlage an der Veranstaltung und ohne Parameter gilt v2."""
        self.ICP.set_param(PARAM_DEFAULT_TEMPLATE, False)
        self.assertEqual(self.event._kjr_consent_sign_template(), self.template)
        self.assertTrue(self.Event._kjr_consent_template_ok(self.template))
        self.assertEqual(self.template.model_id.model, 'event.registration')
        constant = self.template.sign_item_ids.filtered('constant')
        self.assertEqual(len(constant), 3)
        self.assertFalse(any(constant.mapped('required')))

    def test_v2_prefills_child_event_and_guardian(self):
        """Nach dem Anlegen der Anfrage stehen Name des Kindes, Veranstaltung
        mit Zeitraum und Name der/des Erziehungsberechtigten in den
        schreibgeschützten Feldern, auch wenn der Absender die Gruppe für die
        geschützten Eltern-Daten nicht hat (Odoo Sign liest mit sudo)."""
        self.assertFalse(self.sender.has_group('kjr_event.group_kjr_event_care'))
        reg, req = self._started()
        self.assertEqual(req.template_id, self.template)
        values = self._item_values(req)
        child_item = self.env.ref('kjr_event_sign.item_v2_child_name')
        event_item = self.env.ref('kjr_event_sign.item_v2_event')
        guardian_item = self.env.ref('kjr_event_sign.item_v2_guardian_name')
        self.assertEqual(values.get(child_item), 'Kind Mustername')
        self.assertEqual(values.get(guardian_item), GUARDIAN)
        label = reg.kjr_sign_event_label
        self.assertEqual(values.get(event_item), label)
        begin = reg._kjr_sign_event_begin_date()
        end = reg._kjr_sign_event_end_date()
        self.assertEqual(label, 'Sommerfreizeit Test, %s bis %s' % (
            begin.strftime('%d.%m.%Y'), end.strftime('%d.%m.%Y')))
        # Nur die drei schreibgeschützten Felder sind vorab gefüllt.
        self.assertEqual(set(values), {child_item, event_item, guardian_item})
        # Unterschreiben ohne diese Felder klappt (sie sind kein Pflichtfeld).
        self._sign(req)
        self.assertEqual(req.state, 'signed')
        self.assertTrue(reg.parental_consent)
        self.assertEqual(self._item_values(req).get(child_item), 'Kind Mustername')

    def test_v2_constant_value_cannot_be_changed(self):
        """Odoo Sign lehnt einen anderen Wert für ein schreibgeschütztes Feld ab."""
        reg, req = self._started()
        values = self._sign_values(req)
        child_item = self.env.ref('kjr_event_sign.item_v2_child_name')
        values[str(child_item.id)] = 'Anderes Kind'
        with self.assertRaises(UserError), \
                patch.object(type(self.SignRequest), '_send_completed_documents',
                             autospec=True):
            req.request_item_ids[:1].sudo().sign(values)

    def test_event_label_single_day(self):
        """Eintägig nur ein Datum; der Name steht vorn. Uhrzeit fest auf 08:00
        UTC, damit Beginn und Ende auch in Europe/Berlin am selben Tag liegen."""
        begin = (fields.Datetime.now() + timedelta(days=20)).replace(
            hour=8, minute=0, second=0, microsecond=0)
        event = self.Event.create({
            'name': 'Tagesausflug', 'date_begin': begin,
            'date_end': begin + timedelta(hours=2), 'date_tz': 'Europe/Berlin',
        })
        reg = self.Registration.create({'event_id': event.id, 'name': 'Kind'})
        day = reg._kjr_sign_event_begin_date().strftime('%d.%m.%Y')
        self.assertEqual(reg.kjr_sign_event_label, 'Tagesausflug, %s' % day)

    def test_v2_without_guardian_name_sets_error(self):
        """Vorlage v2 und kein Name der Eltern an der Anmeldung (Backend,
        ältere Anmeldung): keine Anfrage mit leerem Namensfeld, sondern
        Fehlermerker und Aktivität für die Geschäftsstelle."""
        reg = self._held_registration(guardian_name=False)
        reg._kjr_consent_request_start()
        self.assertFalse(reg.sudo().kjr_sign_request_id)
        self.assertTrue(reg.kjr_sign_error)
        self.assertTrue(reg.activity_ids.filtered(
            lambda a: a.summary == 'Unterschriftsanfrage konnte nicht versendet werden'))
        # Nachgetragen: der nächste Versuch klappt.
        reg.sudo().guardian_name = GUARDIAN
        reg.with_context(kjr_sign_force=True)._kjr_consent_request_start()
        self.assertTrue(reg.sudo().kjr_sign_request_id)
        self.assertFalse(reg.kjr_sign_error)

    def test_message_without_child_name(self):
        """Begleittext: v2 bittet um Prüfung der übernommenen Angaben, v1 wie
        bisher um das Eintragen; der Name des Kindes steht in keinem."""
        reg, req = self._started()
        self.assertIn('übernommenen Angaben', req.message)
        self.assertNotIn('Mustername', req.message)
        self.event.kjr_consent_sign_template_id = self.template_v1
        reg_v1, req_v1 = self._started(email='v1.eltern@example.com')
        self.assertEqual(req_v1.template_id, self.template_v1)
        self.assertIn('Namen Ihres Kindes', req_v1.message)
        self.assertNotIn('Mustername', req_v1.message)
        self.assertFalse(self._item_values(req_v1))

    def test_switch_default_template_v2(self):
        """Migration 19.0.1.1.0: Parameter und Veranstaltungen von v1 auf v2;
        eigene Vorlagen und versendete Anfragen bleiben."""
        Event = self.Event
        # Versendete Anfrage mit v1 vor der Umstellung
        self.event.kjr_consent_sign_template_id = self.template_v1
        reg, req_v1 = self._started()
        self.assertEqual(req_v1.template_id, self.template_v1)
        archived = Event.create({
            'name': 'Archiviert', 'date_begin': self.event.date_begin,
            'date_end': self.event.date_end, 'active': False,
            'kjr_consent_sign_template_id': self.template_v1.id,
        })
        self.ICP.set_param(PARAM_DEFAULT_TEMPLATE, str(self.template_v1.id))
        # Stand der Produktion vor dem Update: v1 mit ausgeliefertem Namen
        self.template_v1.sudo().name = TEMPLATE_V1_SHIPPED_NAME

        result = Event._kjr_sign_switch_default_template_v2()
        self.assertEqual(result, {'param': 'set', 'events': 2, 'v1_renamed': True})
        self.assertEqual(self.template_v1.name, TEMPLATE_V1_LEGACY_NAME)
        self.assertNotIn('Standard', self.template_v1.name)
        self.assertNotIn('Standard', self.template.name)
        self.assertEqual(self.ICP.get_param(PARAM_DEFAULT_TEMPLATE), str(self.template.id))
        self.assertEqual(self.event.kjr_consent_sign_template_id, self.template)
        self.assertEqual(archived.kjr_consent_sign_template_id, self.template)
        self.assertEqual(req_v1.template_id, self.template_v1)
        self.assertEqual(req_v1.state, 'sent')

        # Idempotent
        self.assertEqual(Event._kjr_sign_switch_default_template_v2(),
                         {'param': 'kept', 'events': 0, 'v1_renamed': False})

        # Eigene Vorlage der Geschäftsstelle bleibt
        own = self.env['sign.template'].create({'name': 'Eigene Einwilligung'})
        self.ICP.set_param(PARAM_DEFAULT_TEMPLATE, str(own.id))
        self.assertEqual(Event._kjr_sign_switch_default_template_v2()['param'], 'kept')
        self.assertEqual(self.ICP.get_param(PARAM_DEFAULT_TEMPLATE), str(own.id))

        # Leerer Parameter -> v2
        self.ICP.set_param(PARAM_DEFAULT_TEMPLATE, False)
        self.assertEqual(Event._kjr_sign_switch_default_template_v2()['param'], 'set')
        self.assertEqual(self.ICP.get_param(PARAM_DEFAULT_TEMPLATE), str(self.template.id))

    def test_rename_template_v1_only_shipped_name(self):
        """v1 heißt nach der Umstellung "… (alt, ohne Vorbefüllung)"; ein
        eigener Name der Geschäftsstelle bleibt. Nur der Name ändert sich."""
        Event = self.Event
        items = self.template_v1.sign_item_ids
        self.template_v1.sudo().name = TEMPLATE_V1_SHIPPED_NAME
        self.assertTrue(Event._kjr_sign_rename_template_v1())
        self.assertEqual(self.template_v1.name, TEMPLATE_V1_LEGACY_NAME)
        # Idempotent
        self.assertFalse(Event._kjr_sign_rename_template_v1())
        self.assertEqual(self.template_v1.sign_item_ids, items)
        self.assertTrue(self.template_v1.active)
        self.template_v1.sudo().name = 'Einwilligung Ferienlager (eigene)'
        self.assertFalse(Event._kjr_sign_rename_template_v1())
        self.assertEqual(self.template_v1.name, 'Einwilligung Ferienlager (eigene)')

    # ── Name des Kindes im Feld der Eltern (gemeldeter Fall) ────────────────

    def test_v2_guardian_name_is_child_sets_error(self):
        """Steht im Feld der Eltern der Name des Kindes (andere Schreibweise,
        Mehrfach-Leerraum egal), geht mit v2 keine Anfrage hinaus: sonst
        stünde der Kindername schreibgeschützt als unterschreibende Person im
        Dokument. Fehlermerker und Aktivität wie bei fehlendem Namen; nach der
        Korrektur ist Unterzeichner nie der Kind-Kontakt."""
        child_contact = self.env['res.partner'].create({
            'name': 'Kind Mustername', 'email': 'eltern.test@example.com'})
        reg = self._held_registration(
            partner_id=child_contact.id, guardian_name='  kind  MUSTERNAME ')
        reg._kjr_consent_request_start()
        self.assertFalse(reg.sudo().kjr_sign_request_id)
        self.assertTrue(reg.kjr_sign_error)
        self.assertTrue(reg.activity_ids.filtered(
            lambda a: a.summary == 'Unterschriftsanfrage konnte nicht versendet werden'))
        self.assertFalse(self.SignRequest.search(
            [('reference_doc', '=', 'event.registration,%d' % reg.id)]))
        with self.assertRaises(UserError):
            reg._kjr_sign_check_prefill(self.template)

        reg.sudo().guardian_name = GUARDIAN
        reg.with_context(kjr_sign_force=True)._kjr_consent_request_start()
        req = reg.sudo().kjr_sign_request_id
        self.assertTrue(req)
        partner = req.request_item_ids.partner_id
        self.assertNotEqual(partner, child_contact)
        self.assertEqual(partner.name, GUARDIAN)
        guardian_item = self.env.ref('kjr_event_sign.item_v2_guardian_name')
        self.assertEqual(self._item_values(req).get(guardian_item), GUARDIAN)

    def test_partner_guardian_name_is_child_treated_as_missing(self):
        """Ohne Vorbefüllung (v1): Name des Kindes im Feld der Eltern gilt als
        fehlender Name. Weder der Kind-Kontakt noch ein neuer Kontakt mit dem
        Kindernamen wird Unterzeichner, sondern ein Kontakt mit der Adresse
        als Name."""
        self.event.kjr_consent_sign_template_id = self.template_v1
        child_contact = self.env['res.partner'].create({
            'name': 'Kind Mustername', 'email': 'eltern.test@example.com'})
        reg, req = self._started(partner_id=child_contact.id,
                                 guardian_name='Kind Mustername')
        partner = req.request_item_ids.partner_id
        self.assertNotEqual(partner, child_contact)
        self.assertEqual(partner.name, 'eltern.test@example.com')

    def test_partner_child_named_contact_excluded_with_guardian_name(self):
        """Auch mit Namen der Eltern kommt ein Kontakt mit dem Namen des Kindes
        über die E-Mail-Suche nie in Frage."""
        self.env['res.partner'].create({
            'name': 'Kind Mustername', 'email': 'eltern.test@example.com'})
        reg = self._held_registration()
        partner = reg._kjr_sign_guardian_partner()
        self.assertEqual(partner.name, GUARDIAN)

    # ── Vorbefüllung nur für die eigene Anfrage ─────────────────────────────

    def test_foreign_request_gets_no_prefill(self):
        """Eine fremde Anfrage mit reference_doc = Anmeldung (z. B. von einer
        Sign-Benutzerin ohne Betreuungsgruppe angelegt) bekommt weder beim
        Anlegen noch auf der Signierseite Werte aus der Anmeldung, auch nicht
        den Namen der/des Erziehungsberechtigten. Die eigene Anfrage der
        Anmeldung bekommt sie weiter."""
        reg, req = self._started()
        guardian_type = self.env.ref('kjr_event_sign.sign_item_type_kjr_guardian_name')
        child_type = self.env.ref('kjr_event_sign.sign_item_type_kjr_child_name')
        intruder = new_test_user(
            self.env, login='kjr_sign_intruder', name='Fremde Person',
            email='fremd.kjr@example.com', groups='base.group_user,sign.group_sign_user')
        self.assertFalse(intruder.has_group('kjr_event.group_kjr_event_care'))
        role = self.template.sign_item_ids.responsible_id
        foreign = self.SignRequest.sudo().with_context(no_sign_mail=True).create({
            'template_id': self.template.id,
            # Pflichtfeld von sign.request; bewusst ohne Kindsnamen.
            'reference': 'Fremde Anfrage',
            'reference_doc': 'event.registration,%d' % reg.id,
            'request_item_ids': [Command.create({
                'partner_id': intruder.partner_id.id, 'role_id': role.id})],
        })
        values = self._item_values(foreign)
        self.assertFalse(values.get(self.env.ref('kjr_event_sign.item_v2_guardian_name')))
        self.assertFalse(values.get(self.env.ref('kjr_event_sign.item_v2_child_name')))
        # Weg der Signierseite (sign/controllers/main.py: auto_value je Feldtyp)
        foreign_item = foreign.request_item_ids.sudo()
        for item_type in (guardian_type, child_type):
            self.assertEqual(foreign_item._get_auto_field_value(
                {'id': item_type.id, 'auto_field': item_type.auto_field}), '')
        own_item = req.request_item_ids.sudo()
        self.assertEqual(own_item._get_auto_field_value(
            {'id': guardian_type.id, 'auto_field': 'guardian_name'}), GUARDIAN)
        # Der Freigabe-Merker gilt nur während des Anlegens.
        self.assertFalse(self.env.cr.cache.get(bridge_registration.PREFILL_CACHE_KEY))

    def test_request_link_not_settable_without_sudo(self):
        """Wer Sign-Rechte und Schreibrecht an der Anmeldung hat (hier die
        Registrierungstheke), aber nicht zur Betreuungsgruppe gehört, kann
        seine eigene Anfrage nicht per RPC zur aktuellen der Anmeldung machen
        (write, create, Kontext-Vorgabe). Die Vorbefüllung bleibt für die
        fremde Anfrage gesperrt, die eigene Anfrage der Anmeldung bleibt."""
        reg, req = self._started()
        intruder = new_test_user(
            self.env, login='kjr_sign_desk_intruder', name='Theke Fremd',
            email='theke.fremd@example.com',
            groups='base.group_user,sign.group_sign_user,'
                   'event.group_event_registration_desk')
        self.assertFalse(intruder.has_group('kjr_event.group_kjr_event_care'))
        role = self.template.sign_item_ids.responsible_id
        foreign = self.SignRequest.sudo().with_context(no_sign_mail=True).create({
            'template_id': self.template.id,
            'reference': 'Fremde Anfrage',
            'reference_doc': 'event.registration,%d' % reg.id,
            'request_item_ids': [Command.create({
                'partner_id': intruder.partner_id.id, 'role_id': role.id})],
        })
        with self.assertRaisesRegex(AccessError, 'von Hand'):
            reg.with_user(intruder).write({'kjr_sign_request_id': foreign.id})
        with self.assertRaisesRegex(AccessError, 'von Hand'):
            self.Registration.with_user(intruder).create({
                'event_id': self.event.id, 'name': 'Zweite Anmeldung',
                'kjr_sign_request_id': foreign.id})
        with self.assertRaisesRegex(AccessError, 'von Hand'):
            self.Registration.with_user(intruder).with_context(
                default_kjr_sign_request_id=foreign.id).create({
                    'event_id': self.event.id, 'name': 'Dritte Anmeldung'})
        self.assertEqual(reg.sudo().kjr_sign_request_id, req)
        guardian_type = self.env.ref('kjr_event_sign.sign_item_type_kjr_guardian_name')
        self.assertEqual(foreign.request_item_ids.sudo()._get_auto_field_value(
            {'id': guardian_type.id, 'auto_field': guardian_type.auto_field}), '')
        # Die Brücke selbst (sudo) darf das Feld weiter setzen und leeren.
        reg.sudo().write({'kjr_sign_request_id': False})
        self.assertFalse(reg.sudo().kjr_sign_request_id)

    # ── Geänderte Angaben bei offener Anfrage (Vorlage v2) ──────────────────

    def test_v2_guardian_name_change_resends(self):
        """Name der/des Erziehungsberechtigten berichtigt: die offene Anfrage
        mit dem alten, schreibgeschützten Namen wird storniert und mit dem
        neuen Namen neu versendet."""
        reg, req = self._started()
        reg.write({'guardian_name': 'Erika Berichtigt'})
        self.assertEqual(req.state, 'canceled')
        new_req = reg.sudo().kjr_sign_request_id
        self.assertTrue(new_req)
        self.assertNotEqual(new_req, req)
        guardian_item = self.env.ref('kjr_event_sign.item_v2_guardian_name')
        self.assertEqual(self._item_values(new_req).get(guardian_item), 'Erika Berichtigt')
        self.assertEqual(len(self._notes(reg, 'Angaben der Anmeldung geändert')), 1)

    def test_v2_child_name_change_resends(self):
        """Name des Kindes berichtigt: ebenso Storno und Neuversand."""
        reg, req = self._started()
        reg.write({'name': 'Kind Berichtigt'})
        self.assertEqual(req.state, 'canceled')
        new_req = reg.sudo().kjr_sign_request_id
        self.assertNotEqual(new_req, req)
        child_item = self.env.ref('kjr_event_sign.item_v2_child_name')
        self.assertEqual(self._item_values(new_req).get(child_item), 'Kind Berichtigt')

    def test_v2_unchanged_values_keep_request(self):
        """Schreiben derselben Werte (Formular speichert alles) lässt die
        offene Anfrage stehen."""
        reg, req = self._started()
        reg.write({'name': 'Kind Mustername', 'guardian_name': GUARDIAN})
        self.assertEqual(req.state, 'sent')
        self.assertEqual(reg.sudo().kjr_sign_request_id, req)

    def test_v2_event_dates_change_resends(self):
        """Termine der Veranstaltung verschoben: das vorbefüllte Feld
        "Veranstaltung" wäre veraltet, also Storno und Neuversand mit dem
        neuen Zeitraum."""
        reg, req = self._started()
        event_item = self.env.ref('kjr_event_sign.item_v2_event')
        old_label = self._item_values(req).get(event_item)
        self.event.write({
            'date_begin': self.event.date_begin + timedelta(days=7),
            'date_end': self.event.date_end + timedelta(days=7),
        })
        self.assertEqual(req.state, 'canceled')
        new_req = reg.sudo().kjr_sign_request_id
        self.assertNotEqual(new_req, req)
        new_label = self._item_values(new_req).get(event_item)
        self.assertEqual(new_label, reg.kjr_sign_event_label)
        self.assertNotEqual(new_label, old_label)

    def test_v1_name_change_keeps_request(self):
        """Vorlage ohne vorbefüllte Felder (v1): eine Namensänderung lässt die
        offene Anfrage unberührt."""
        self.event.kjr_consent_sign_template_id = self.template_v1
        reg, req = self._started()
        reg.write({'name': 'Kind Berichtigt', 'guardian_name': 'Erika Berichtigt'})
        self.assertEqual(req.state, 'sent')
        self.assertEqual(reg.sudo().kjr_sign_request_id, req)

    def test_desk_child_name_change_does_not_resend(self):
        """Registrierungstheke berichtigt den Namen des Kindes: Storno, aber
        kein automatischer Neuversand (gleiche Grenze wie beim Adresswechsel),
        sondern die Aktivität für die Geschäftsstelle."""
        reg, req = self._started()
        desk = new_test_user(
            self.env, login='kjr_sign_desk_name',
            groups='base.group_user,event.group_event_registration_desk')
        reg.with_user(desk).write({'name': 'Kind Berichtigt'})
        self.assertEqual(req.state, 'canceled')
        self.assertEqual(reg.sudo().kjr_sign_request_id, req,
                         'Es darf keine neue Anfrage entstanden sein.')
        self.assertTrue(reg.activity_ids.filtered(
            lambda a: a.summary == 'Unterschriftsanfrage neu senden'))

    # ── Anonymisierung (Befund K6) ──────────────────────────────────────────

    def test_purge_deletes_unsigned_requests_keeps_signed(self):
        """Nie unterschriebene Anfragen tragen mit v2 die Namen von Kind und
        Eltern; die Anonymisierung löscht sie, auch frühere aus "Erneut
        senden". Unterschriebene bleiben archiviert als Nachweis."""
        reg, first = self._started()
        reg._kjr_sign_cancel_open_requests(reason='resend')
        reg.with_context(kjr_sign_force=True)._kjr_consent_request_start()
        second = reg.sudo().kjr_sign_request_id
        self.assertTrue(second)
        self.assertNotEqual(first, second)
        self.assertEqual(first.state, 'canceled')

        signed_reg, signed_req = self._started(email='unterschrieben.kjr@example.com')
        self._sign(signed_req)
        self.assertEqual(signed_req.state, 'signed')

        self.Event._kjr_purge_registration_copies(reg | signed_reg)
        self.assertFalse(first.exists())
        self.assertFalse(second.exists())
        self.assertFalse(reg.sudo().kjr_sign_request_id)
        self.assertTrue(signed_req.exists())
        self.assertFalse(signed_req.active)
        self.assertEqual(signed_req.state, 'signed')
        self.assertFalse(signed_reg.sudo().kjr_sign_request_id)
