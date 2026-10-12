# -*- coding: utf-8 -*-
"""Einwilligungs-Sperre (19.0.5.9.0): erst sperren, dann freigeben.

Fachliche Leitplanken, die hier als ausführbare Zusicherung festgeschrieben
werden:

* Gesperrt wird NUR mit dem Kontext ``kjr_consent_hold_event_id`` (den setzt der
  Website-Controller im Verfahren 'sign') und nur für genau diese Veranstaltung.
* Eine gesperrte Anmeldung ist unbestätigt, erzeugt keine Rechnung und lässt
  sich nicht von Hand bestätigen (hörbarer Fehler statt stillem Verwerfen).
* Die Einwilligung gibt frei: über ``write(parental_consent=True)``, mit
  Platzprüfung, Rechnung genau einmal, ohne Überbuchung und ohne Exception.
* Nachrücken von der Warteliste verschickt bei gesperrter Anmeldung KEINE Mail.

Die Brücke zu Odoo Sign (kjr_event_sign) wird hier nicht vorausgesetzt: das
Verfahren wird bei Bedarf per ``patch.object`` auf 'sign' gestellt, der Start
der Einwilligungsanfrage ebenso durch einen Platzhalter ersetzt.
"""
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user

from odoo.addons.kjr_event.models import kjr_event_document

PARAM_ACTIVE_FROM = 'kjr_event.automation_active_from'
PARAM_PACKING_LEAD = 'kjr_event.packing_list_lead_days'

SUMMARY_NO_BIRTHDATE = 'Angaben nicht zuordenbar: Einwilligung prüfen'
SUMMARY_NO_SEAT = 'Einwilligung liegt vor, aber kein Platz frei'
SUMMARY_WAITLIST = 'Einwilligung liegt vor, Veranstaltung voll: Warteliste'


@tagged('post_install', '-at_install')
class TestKjrConsentHold(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Event = cls.env['event.event']
        cls.Registration = cls.env['event.registration']
        cls.event = cls._make_event()

    # ------------------------------------------------------------------
    # Hilfsmittel
    # ------------------------------------------------------------------
    @classmethod
    def _make_event(cls, seats_max=0, waitlist=False, name='Zeltlager (Einwilligungs-Test)',
                    **extra):
        """Veranstaltung mit Einwilligungspflicht, Beginn 10.07.2027.

        ``seats_limited`` nur, wenn die Odoo-Edition das Feld führt (gleiches
        Vorgehen wie in den Wartelistentests).
        """
        vals = {
            'name': name,
            'is_kjr': True,
            'date_begin': '2027-07-10 09:00:00',
            'date_end': '2027-07-15 17:00:00',
            'kjr_event_type': 'ferienprogramm',
            'requires_parental_consent': True,
            'kjr_waitlist_enabled': waitlist,
        }
        if seats_max:
            vals['seats_max'] = seats_max
            if 'seats_limited' in cls.Event._fields:
                vals['seats_limited'] = True
        vals.update(extra)
        return cls.Event.create(vals)

    def _held(self, event=None, **kw):
        """Anmeldung so anlegen, wie es der Controller im Verfahren 'sign' tut."""
        event = event or self.event
        vals = {'event_id': event.id, 'name': 'Kind', 'email': 'eltern@example.com'}
        vals.update(kw)
        reg = self.Registration.with_context(kjr_consent_hold_event_id=event.id).create(vals)
        # Ohne den Kontext weiterarbeiten, wie nach dem Ende der Anfrage.
        return self.Registration.browse(reg.id)

    def _reg(self, event=None, **kw):
        vals = {'event_id': (event or self.event).id, 'name': 'Teilnehmer/in'}
        vals.update(kw)
        return self.Registration.create(vals)

    def _has_activity(self, reg, summary):
        return bool(reg.activity_ids.filtered(lambda a: a.summary == summary))

    # ------------------------------------------------------------------
    # Sperren beim Anlegen
    # ------------------------------------------------------------------
    def test_hold_only_with_context(self):
        """Mit dem Kontext wird gesperrt und unbestätigt angelegt."""
        reg = self._held(birthdate='2015-01-01')
        self.assertTrue(reg.kjr_consent_hold)
        self.assertEqual(reg.state, 'draft')

    def test_hold_only_for_the_named_event(self):
        """Der Kontext sperrt nur Anmeldungen genau dieser Veranstaltung."""
        other = self._make_event(name='Andere Veranstaltung')
        reg = self.Registration.with_context(kjr_consent_hold_event_id=self.event.id).create({
            'event_id': other.id, 'name': 'Kind'})
        self.assertFalse(reg.kjr_consent_hold)

    def test_no_context_no_hold(self):
        """Ohne Kontext (Backend, Import, Shop-Bestätigung) keine Sperre."""
        reg = self._reg(birthdate='2015-01-01')
        self.assertFalse(reg.kjr_consent_hold)

    def test_no_invoice_while_held(self):
        """Eine gesperrte Anmeldung erzeugt keine Rechnung."""
        product = self.env['product.product'].create({
            'name': 'Freizeitbeitrag (Test)', 'list_price': 50.0, 'type': 'service'})
        event = self._make_event(
            name='Kostenpflichtig (Einwilligungs-Test)', payment_required=True,
            kjr_auto_invoice=True, training_product_id=product.id)
        partner = self.env['res.partner'].create({'name': 'Zahlende Person'})
        with patch.object(type(self.Registration), '_kjr_create_training_invoices',
                          autospec=True) as create_invoices:
            reg = self._held(event, partner_id=partner.id, birthdate='2015-01-01')
        create_invoices.assert_not_called()
        self.assertFalse(reg.kjr_training_invoice_id)

    # ------------------------------------------------------------------
    # Schutz in write()
    # ------------------------------------------------------------------
    def test_write_open_on_held_raises(self):
        """Direktes Bestätigen einer gesperrten Anmeldung ist ein Fehler."""
        reg = self._held(birthdate='2015-01-01')
        with self.assertRaises(UserError):
            reg.write({'state': 'open'})
        self.assertTrue(reg.kjr_consent_hold)

    def test_action_confirm_on_held_raises(self):
        """Auch der Kernknopf "Registriert" scheitert hörbar."""
        reg = self._held(birthdate='2015-01-01')
        with self.assertRaises(UserError):
            reg.action_confirm()

    # ------------------------------------------------------------------
    # Freigabe
    # ------------------------------------------------------------------
    def test_parental_consent_releases(self):
        """Einwilligung eintragen: registriert, entsperrt, Quelle Papier, Rechnung einmal."""
        reg = self._held(birthdate='2015-01-01')
        with patch.object(type(self.Registration), '_kjr_auto_invoice',
                          autospec=True) as auto_invoice:
            reg.write({'parental_consent': True})
        self.assertEqual(reg.state, 'open')
        self.assertFalse(reg.kjr_consent_hold)
        self.assertEqual(reg.kjr_consent_source, 'paper')
        self.assertEqual(auto_invoice.call_count, 1,
                         'Die Rechnungsautomatik muss genau einmal angestoßen werden.')
        self.assertIn(reg, auto_invoice.call_args[0][0])

    def test_paper_action_releases(self):
        """Der Papier-Knopf gibt frei und meldet Erfolg."""
        reg = self._held(birthdate='2015-01-01')
        result = reg.action_kjr_consent_paper()
        self.assertEqual(reg.state, 'open')
        self.assertTrue(reg.parental_consent)
        self.assertEqual(result['params']['type'], 'success')

    def test_release_on_full_event_with_waitlist(self):
        """Volle Veranstaltung mit Warteliste: Warteliste statt Überbuchung, keine Exception."""
        event = self._make_event(seats_max=1, waitlist=True, name='Voll mit Warteliste')
        held = self._held(event, birthdate='2015-01-01')
        self._reg(event)  # belegt den einzigen Platz (die Sperre zählt nicht)
        self.assertEqual(event._kjr_free_seats(), 0)
        held.write({'parental_consent': True})
        self.assertFalse(held.kjr_consent_hold)
        self.assertTrue(held.kjr_is_waitlist)
        self.assertEqual(held.state, 'draft')
        self.assertTrue(self._has_activity(held, SUMMARY_WAITLIST))

    def test_release_on_full_event_without_waitlist(self):
        """Volle Veranstaltung ohne Warteliste: Sperre bleibt, Einwilligung bleibt gespeichert."""
        event = self._make_event(seats_max=1, waitlist=False, name='Voll ohne Warteliste')
        held = self._held(event, birthdate='2015-01-01')
        self._reg(event)
        held.write({'parental_consent': True})
        self.assertTrue(held.kjr_consent_hold)
        self.assertTrue(held.parental_consent)
        self.assertEqual(held.state, 'draft')
        self.assertTrue(self._has_activity(held, SUMMARY_NO_SEAT))

    def test_release_failure_never_raises(self):
        """Ein Fehler in der Freigabe kippt das Schreiben der Einwilligung nicht."""
        reg = self._held(birthdate='2015-01-01')
        with patch.object(type(self.Registration), '_kjr_consent_release_one',
                          autospec=True, side_effect=RuntimeError('Testfehler')):
            reg.write({'parental_consent': True})
        self.assertTrue(reg.parental_consent)
        self.assertTrue(reg.kjr_consent_hold)
        self.assertTrue(self._has_activity(reg, 'Freigabe nach Einwilligung fehlgeschlagen'))

    def test_activity_is_not_duplicated(self):
        """Gleiche Aktivität zweimal anlegen ergibt nur eine."""
        reg = self._held()
        reg._kjr_consent_activity('Einwilligung einholen')
        reg._kjr_consent_activity('Einwilligung einholen')
        self.assertEqual(
            len(reg.activity_ids.filtered(lambda a: a.summary == 'Einwilligung einholen')), 1)

    # ------------------------------------------------------------------
    # Auflösung nach der Online-Anmeldung
    # ------------------------------------------------------------------
    def test_resolve_releases_adult(self):
        """Volljährige werden sofort freigegeben."""
        reg = self._held(birthdate='1990-01-01')
        reg._kjr_consent_resolve_holds()
        self.assertFalse(reg.kjr_consent_hold)
        self.assertEqual(reg.state, 'open')

    def test_resolve_without_birthdate_keeps_hold(self):
        """Ohne Geburtsdatum bleibt die Sperre (fail-closed) und es gibt eine Aktivität."""
        reg = self._held()
        reg._kjr_consent_resolve_holds()
        self.assertTrue(reg.kjr_consent_hold)
        self.assertTrue(self._has_activity(reg, SUMMARY_NO_BIRTHDATE))

    def test_resolve_starts_request_for_minor(self):
        """Für Minderjährige startet die Einwilligungsanfrage."""
        reg = self._held(birthdate='2015-01-01')
        with patch.object(type(self.Registration), '_kjr_consent_request_start',
                          autospec=True) as request_start:
            reg._kjr_consent_resolve_holds()
        self.assertEqual(request_start.call_count, 1)
        self.assertIn(reg, request_start.call_args[0][0])
        self.assertTrue(reg.kjr_consent_hold)

    # ------------------------------------------------------------------
    # Warteliste und Versand
    # ------------------------------------------------------------------
    def test_promote_held_waitlist_without_mail(self):
        """Nachrücken bei Sperre: Warteliste verlassen, unbestätigt, keine Mail."""
        event = self._make_event(seats_max=2, waitlist=True, name='Nachrücken mit Sperre')
        reg = self._held(event, birthdate='2015-01-01', kjr_is_waitlist=True)
        self.assertTrue(reg.kjr_is_waitlist)
        with patch.object(type(self.env['mail.template']), 'send_mail',
                          autospec=True) as send_mail:
            reg.action_kjr_promote_waitlist()
        send_mail.assert_not_called()
        self.assertFalse(reg.kjr_is_waitlist)
        self.assertTrue(reg.kjr_consent_hold)
        self.assertEqual(reg.state, 'draft')

    def test_packing_list_skips_held(self):
        """Die Packliste geht nicht an gesperrte Anmeldungen."""
        params = self.env['ir.config_parameter'].sudo()
        params.set_param(PARAM_ACTIVE_FROM, '2000-01-01 00:00:00')
        params.set_param(PARAM_PACKING_LEAD, '30')
        event = self._make_event(
            name='Packliste (Einwilligungs-Test)',
            date_begin=fields.Datetime.now() + timedelta(days=5),
            date_end=fields.Datetime.now() + timedelta(days=8))
        held = self._held(event, birthdate='2015-01-01')
        normal = self._reg(event, email='teilnehmer@example.com')
        with patch.object(kjr_event_document, '_kjr_send_template', return_value=True):
            self.Registration._cron_kjr_packing_list()
        self.assertTrue(normal.kjr_packing_list_sent)
        self.assertFalse(held.kjr_packing_list_sent)

    # ------------------------------------------------------------------
    # Hilfsfunktionen und Felder
    # ------------------------------------------------------------------
    def test_age_at_begin_matches_kjr_age(self):
        """Der 18. Geburtstag am Beginntag zählt als volljährig, einen Tag später nicht."""
        self.assertEqual(self.event._kjr_age_at_begin('2009-07-10'), 18)
        self.assertEqual(self.event._kjr_age_at_begin('2009-07-11'), 17)
        self.assertIsNone(self.event._kjr_age_at_begin(False))
        adult = self._reg(birthdate='2009-07-10')
        minor = self._reg(birthdate='2009-07-11')
        self.assertEqual(adult.kjr_age, 18)
        self.assertFalse(adult.is_minor)
        self.assertEqual(minor.kjr_age, 17)
        self.assertTrue(minor.is_minor)

    def test_mask_email(self):
        """Maskierung für die Bestätigungsseite."""
        mask = self.Registration._kjr_mask_email
        self.assertEqual(mask('max@beispiel.de'), 'm***@b***.de')
        self.assertEqual(mask(''), '')
        self.assertEqual(mask(False), '')

    def test_recipient_prefers_guardian_email(self):
        """Empfänger: zuerst die Erziehungsberechtigten, sonst die Anmeldung."""
        reg = self._held(guardian_email=' Mutter@Beispiel.DE ')
        self.assertEqual(reg._kjr_consent_recipient_email(), 'mutter@beispiel.de')
        reg.guardian_email = False
        self.assertEqual(reg._kjr_consent_recipient_email(), 'eltern@example.com')
        self.assertEqual(reg.kjr_consent_recipient_masked, 'e***@e***.com')

    def test_action_url_is_false_without_bridge(self):
        """Ohne Brücke gibt es keinen Signierlink."""
        reg = self._held(birthdate='2015-01-01')
        self.assertFalse(reg.kjr_consent_action_url)

    def test_consent_mode_hook(self):
        """Das Verfahren kommt aus dem Erweiterungspunkt _kjr_consent_mode()."""
        self.assertEqual(self.event.kjr_consent_mode, 'checkbox')
        none_event = self._make_event(name='Ohne Einwilligung', requires_parental_consent=False)
        self.assertEqual(none_event.kjr_consent_mode, 'none')
        with patch.object(type(self.Event), '_kjr_consent_mode', autospec=True,
                          return_value='sign'):
            self.event.invalidate_recordset(['kjr_consent_mode'])
            self.assertEqual(self.event.kjr_consent_mode, 'sign')
        self.event.invalidate_recordset(['kjr_consent_mode'])

    def test_anonymization_clears_guardian_email(self):
        """Die Anonymisierung leert auch die E-Mail der Erziehungsberechtigten."""
        reg = self._reg(guardian_email='mutter@beispiel.de')
        self.Event._kjr_anonymize_expired_registrations(reg)
        self.assertFalse(reg.guardian_email)

    # ------------------------------------------------------------------
    # Absage: nie wieder freigeben (Befund Review 2026-10-12)
    # ------------------------------------------------------------------
    def test_cancelled_held_registration_is_never_released(self):
        """Absage, danach Einwilligung: bleibt abgesagt, keine Rechnung, Knöpfe scheitern."""
        reg = self._held(birthdate='2015-01-01')
        reg.action_cancel()
        self.assertEqual(reg.state, 'cancel')
        with patch.object(type(self.Registration), '_kjr_auto_invoice',
                          autospec=True) as auto_invoice:
            reg.write({'parental_consent': True})
        auto_invoice.assert_not_called()
        self.assertEqual(reg.state, 'cancel')
        self.assertTrue(reg.parental_consent)
        with self.assertRaises(UserError):
            reg.action_kjr_consent_paper()
        with self.assertRaises(UserError):
            reg.action_kjr_consent_release_manual()
        reg._kjr_consent_release('paper')
        self.assertEqual(reg.state, 'cancel')

    # ------------------------------------------------------------------
    # Erneute Freigabe ohne die Herkunft zu überschreiben
    # ------------------------------------------------------------------
    def test_retry_release_keeps_sign_source(self):
        """Unterschrift bei voller Veranstaltung, später Platz frei: Herkunft bleibt 'sign'."""
        event = self._make_event(seats_max=1, waitlist=False, name='Voll, später Platz frei')
        held = self._held(event, birthdate='2015-01-01')
        other = self._reg(event)
        held.write({'parental_consent': True, 'kjr_consent_source': 'sign'})
        self.assertTrue(held.kjr_consent_hold)
        self.assertEqual(held.kjr_consent_source, 'sign')
        other.action_cancel()
        held.action_kjr_consent_paper()
        self.assertFalse(held.kjr_consent_hold)
        self.assertEqual(held.state, 'open')
        self.assertEqual(held.kjr_consent_source, 'sign',
                         'Der Papier-Knopf darf die Herkunft der Einwilligung nicht '
                         'überschreiben.')
        self.assertFalse(
            held.message_ids.filtered(lambda m: 'auf Papier bestätigt' in (m.body or '')),
            'Es darf keine Papier-Notiz entstehen, wenn die Unterschrift vorliegt.')

    def test_retry_release_action(self):
        """Der Knopf "Freigabe erneut prüfen" gibt mit der vorhandenen Herkunft frei."""
        event = self._make_event(seats_max=1, waitlist=False, name='Erneut prüfen')
        held = self._held(event, birthdate='2015-01-01')
        other = self._reg(event)
        held.write({'parental_consent': True, 'kjr_consent_source': 'sign'})
        result = held.action_kjr_consent_retry_release()
        self.assertEqual(result['params']['type'], 'warning')
        self.assertTrue(held.kjr_consent_hold)
        other.action_cancel()
        result = held.action_kjr_consent_retry_release()
        self.assertEqual(result['params']['type'], 'success')
        self.assertEqual(held.state, 'open')
        self.assertEqual(held.kjr_consent_source, 'sign')

    # ------------------------------------------------------------------
    # Serverseitiger Schutz gegen RPC (Befund Review 2026-10-12)
    # ------------------------------------------------------------------
    def test_desk_cannot_clear_hold_or_enter_consent(self):
        """Registration Desk: Sperre löschen oder Einwilligung eintragen ist verboten."""
        desk = new_test_user(self.env, login='kjr_consent_desk',
                             groups='base.group_user,event.group_event_registration_desk')
        reg = self._held(birthdate='2015-01-01')
        with self.assertRaises(AccessError):
            reg.with_user(desk).write({'kjr_consent_hold': False})
        with self.assertRaises(AccessError):
            reg.with_user(desk).write({'parental_consent': True})
        with self.assertRaises(UserError):
            reg.with_user(desk).with_context(kjr_consent_release=True).write(
                {'state': 'open'})
        self.assertTrue(reg.kjr_consent_hold)
        self.assertEqual(reg.state, 'draft')

    def test_event_user_cannot_forge_sign_source(self):
        """Event-User: 'sign' als Herkunft weder direkt noch per Kontext."""
        user = new_test_user(self.env, login='kjr_consent_user',
                             groups='base.group_user,event.group_event_user')
        reg = self._held(birthdate='2015-01-01')
        with self.assertRaises(AccessError):
            reg.with_user(user).write({'parental_consent': True, 'kjr_consent_source': 'sign'})
        with self.assertRaises(AccessError):
            reg.with_user(user).write({'kjr_consent_hold': False})
        reg.with_user(user).with_context(kjr_consent_source='sign').write(
            {'parental_consent': True})
        self.assertFalse(reg.kjr_consent_hold)
        self.assertEqual(reg.state, 'open')
        self.assertEqual(reg.kjr_consent_source, 'paper',
                         'Ein Kontext aus einem RPC-Aufruf darf keine digitale '
                         'Unterschrift vortäuschen.')

    def test_event_user_paper_action_works(self):
        """Der Papier-Knopf funktioniert für Veranstaltungs-Benutzer/innen."""
        user = new_test_user(self.env, login='kjr_consent_paper_user',
                             groups='base.group_user,event.group_event_user')
        reg = self._held(birthdate='2015-01-01')
        reg.with_user(user).action_kjr_consent_paper()
        self.assertEqual(reg.state, 'open')
        self.assertEqual(reg.kjr_consent_source, 'paper')

    # ------------------------------------------------------------------
    # Erinnerung mit Signierlink ohne Bezug zur Anmeldung
    # ------------------------------------------------------------------
    def test_consent_reminder_is_detached(self):
        """Die Erinnerung mit Bearer-Link hängt nicht an der Anmeldung."""
        reg = self._held(birthdate='2015-01-01')
        with patch.object(type(self.env['mail.template']), 'send_mail',
                          autospec=True, return_value=1) as send_mail:
            reg.action_kjr_send_consent_reminder()
        self.assertEqual(send_mail.call_count, 1)
        email_values = send_mail.call_args.kwargs.get('email_values') or {}
        self.assertIs(email_values.get('model'), False)
        self.assertIs(email_values.get('res_id'), False)
        self.assertEqual(email_values.get('email_to'), 'eltern@example.com')
        self.assertEqual(email_values.get('kjr_detached_registration_id'), reg.id,
                         'Die abgekoppelte Mail braucht eine Kennung für die '
                         'Anonymisierung.')

    def test_consent_reminder_goes_only_to_guardian(self):
        """Echter Versand ohne Patch: der Signierlink geht nur an die Erziehungsberechtigten.

        Kontakt und Anmeldung tragen dieselbe Adresse (Normalfall im
        Shop-Checkout und bei angemeldeten Website-Benutzern). Mit dem
        Odoo-Standard ``use_default_to=True`` würde send_mail sonst den Kontakt
        als Empfänger (recipient_ids) eintragen. Geprüft für beide
        Vorlagen-Einstellungen, damit auch ein Bestand ohne Migration sicher ist.
        """
        template = self.env.ref('kjr_event.mail_template_consent_reminder')
        partner = self.env['res.partner'].create({
            'name': 'Jugendliche Person', 'email': 'jugend@example.com'})
        Mail = self.env['mail.mail'].sudo()
        for use_default_to in (True, False):
            with self.subTest(use_default_to=use_default_to):
                template.use_default_to = use_default_to
                reg = self._held(birthdate='2010-01-01', email='jugend@example.com',
                                 partner_id=partner.id,
                                 guardian_email='eltern-sorge@example.com')
                reg.action_kjr_send_consent_reminder()
                mail = Mail.search([('kjr_detached_registration_id', '=', reg.id)])
                self.assertEqual(len(mail), 1)
                self.assertFalse(mail.recipient_ids,
                                 'Der Kontakt der Anmeldung darf den Signierlink nicht '
                                 'bekommen.')
                self.assertFalse(mail.partner_ids)
                self.assertFalse(mail.email_cc)
                self.assertEqual(mail.email_to, 'eltern-sorge@example.com')
                self.assertFalse(mail.model)
                self.assertFalse(mail.res_id)

    def test_detached_send_requires_explicit_recipient(self):
        """Ohne ausdrücklichen Empfänger kein abgekoppelter Versand (kein Rückfall)."""
        reg = self._held(birthdate='2015-01-01')
        with patch.object(type(self.env['mail.template']), 'send_mail',
                          autospec=True, return_value=1) as send_mail:
            ok = kjr_event_document._kjr_send_template(
                reg, 'kjr_event.mail_template_consent_reminder', None,
                sudo=True, detach=True)
        self.assertFalse(ok)
        send_mail.assert_not_called()

    # ------------------------------------------------------------------
    # Schulungsrechnung: nicht für gesperrte Anmeldungen
    # ------------------------------------------------------------------
    def _invoice_event(self):
        product = self.env['product.product'].create({
            'name': 'Schulungsbeitrag (Test)', 'list_price': 40.0, 'type': 'service'})
        return self._make_event(
            name='Schulung (Einwilligungs-Test)', payment_required=True,
            kjr_auto_invoice=False, training_product_id=product.id)

    def test_invoice_bulk_action_skips_held(self):
        """Sammelaktion: gesperrte Anmeldung bekommt weder Rechnung noch Bestätigung."""
        event = self._invoice_event()
        partner = self.env['res.partner'].create({
            'name': 'Zahlende Person', 'email': 'zahlt@example.com'})
        held = self._held(event, partner_id=partner.id, birthdate='2015-01-01')
        normal = self._reg(event, partner_id=partner.id, email='zahlt@example.com')
        with patch.object(type(self.env['mail.template']), 'send_mail',
                          autospec=True, return_value=1) as send_mail:
            result = (held | normal).action_kjr_create_training_invoices()
        self.assertFalse(held.kjr_training_invoice_id)
        self.assertTrue(normal.kjr_training_invoice_id)
        mailed = [call.args[1] for call in send_mail.call_args_list]
        self.assertNotIn(held.id, mailed, 'Keine Anmeldebestätigung für gesperrte Anmeldungen.')
        self.assertEqual(result.get('tag'), 'display_notification')
        self.assertEqual(result['params']['next']['res_model'], 'account.move')
        _moves, stats = held._kjr_create_training_invoices()
        self.assertEqual(stats['skipped_hold'], 1)
        self.assertEqual(stats['created'], 0)

    def test_invoice_button_refuses_held(self):
        """Einzelknopf: gesperrte Anmeldung ergibt einen hörbaren Fehler."""
        event = self._invoice_event()
        partner = self.env['res.partner'].create({'name': 'Zahlende Person'})
        held = self._held(event, partner_id=partner.id, birthdate='2015-01-01')
        with patch.object(type(self.env['mail.template']), 'send_mail',
                          autospec=True, return_value=1) as send_mail:
            with self.assertRaises(UserError):
                held.action_create_training_invoice()
        send_mail.assert_not_called()
        self.assertFalse(held.kjr_training_invoice_id)

    def test_purge_removes_detached_reminder_mail(self):
        """Die Anonymisierung löscht nicht versendete, abgekoppelte Erinnerungen."""
        reg = self._held(birthdate='2015-01-01')
        mail = self.env['mail.mail'].sudo().create({
            'subject': 'Erinnerung',
            'body_html': '<p>Erinnerung</p>',
            'email_to': 'eltern@example.com',
            'model': False,
            'res_id': False,
            'kjr_detached_registration_id': reg.id,
        })
        message = mail.mail_message_id
        other = self.env['mail.mail'].sudo().create({
            'subject': 'Andere Mail',
            'body_html': '<p>Andere</p>',
            'email_to': 'andere@example.com',
            'kjr_detached_registration_id': reg.id + 100000,
        })
        self.Event._kjr_purge_registration_copies(reg)
        self.assertFalse(mail.exists())
        self.assertFalse(message.exists())
        self.assertTrue(other.exists())

    def test_reminder_renders_without_sudo(self):
        """Composer-Weg (Benutzerkontext ohne Betreuungsgruppe): kein Zugriffsfehler.

        Die Vorlage liest den feldgeschützten Signierlink nur unter sudo; im
        Benutzerkontext erscheint der Text ohne Link.
        """
        user = new_test_user(self.env, login='kjr_reminder_render_user',
                             groups='base.group_user,event.group_event_user')
        reg = self._held(birthdate='2015-01-01')
        template = self.env.ref('kjr_event.mail_template_consent_reminder')
        body = template.with_user(user)._render_field('body_html', reg.ids)[reg.id]
        self.assertIn('rechtzeitig vor Beginn', body)
        self.assertNotIn('Einwilligung jetzt unterschreiben', body)
        body_sudo = template.sudo()._render_field('body_html', reg.ids)[reg.id]
        self.assertIn('rechtzeitig vor Beginn', body_sudo,
                      'Ohne Brücke gibt es keinen Link, auch nicht unter sudo.')

    def test_manual_release_without_birthdate_is_not_adult(self):
        """"Sperre aufheben" ohne Geburtsdatum: die Notiz behauptet keine Volljährigkeit."""
        reg = self._held()
        reg._kjr_consent_resolve_holds()
        self.assertTrue(reg.kjr_consent_hold)
        reg.action_kjr_consent_release_manual()
        self.assertFalse(reg.kjr_consent_hold)
        bodies = ' '.join(str(body) for body in reg.message_ids.mapped('body'))
        self.assertNotIn('volljährig', bodies)
        self.assertIn('ohne Einwilligungsnachweis', bodies)
