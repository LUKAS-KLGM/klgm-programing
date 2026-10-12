# -*- coding: utf-8 -*-
"""Tests der Brücke Veranstaltungen ↔ E-Signatur (kjr_event_sign).

Grundlage ist die mitgelieferte Vorlage (XML-ID
``kjr_event_sign.sign_template_consent``). Gesperrte Anmeldungen entstehen wie
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

LOGGER_EVENT = 'odoo.addons.kjr_event_sign.models.event_event'

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
        cls.template = cls.env.ref('kjr_event_sign.sign_template_consent')
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
        """Gesperrte Anmeldung eines minderjährigen Kindes (wie Website)."""
        vals = {
            'event_id': self.event.id,
            'name': 'Kind Mustername',
            'email': 'eltern.test@example.com',
            'birthdate': self.child_birthdate,
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

    def test_partner_reused_for_same_email(self):
        """Ein Kontakt mit derselben E-Mail wird wiederverwendet, nicht umbenannt."""
        existing = self.env['res.partner'].create({
            'name': 'Bestehender Kontakt', 'email': 'Eltern.Test@Example.com'})
        reg, req = self._started(guardian_name='Anderer Name')
        self.assertEqual(req.request_item_ids.partner_id, existing)
        self.assertEqual(existing.name, 'Bestehender Kontakt')
        category = self.env.ref('kjr_event_sign.partner_category_guardian')
        self.assertNotIn(category, existing.category_id)

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
        self.env['res.partner'].create({'name': 'Firma Eltern', 'email': email,
                                        'is_company': True})
        self.env['res.partner'].create({'name': 'Dublette Eltern', 'email': email})
        portal = new_test_user(self.env, login='kjr_sign_portal_eltern', email=email,
                               groups='base.group_portal')
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
