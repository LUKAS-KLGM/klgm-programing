# -*- coding: utf-8 -*-
"""E7 – Sicherung der Veranstaltungs-Automatik gegen Massenversand.

Die Merker-Felder (``kjr_consent_reminder_sent`` / ``kjr_packing_list_sent``)
stehen bei übernommenen Bestandsdaten auf False. Ohne zusätzliche Bremse würde
der erste Cron-Lauf nach Go-live den kompletten Bestand anschreiben — Mails, die
sich nicht zurückholen lassen. Dieselbe Sicherung wie in kjr_facility
(``test_booking.test_automation_skips_legacy_bookings``):

* ``kjr_event.automation_active_from`` wird beim ERSTEN Lauf festgeschrieben;
  danach zählen nur Veranstaltungen, die NACH diesem Zeitpunkt angelegt wurden.
* ``kjr_event.automation_batch_limit`` begrenzt jeden Lauf der Menge nach.
* Ohne gepflegten Vorlauf (Default 0) sendet der Cron gar nichts.

Diese Tests dürfen nicht "weggetestet" werden.
"""
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.tests import tagged

PARAM_ACTIVE_FROM = 'kjr_event.automation_active_from'
PARAM_BATCH_LIMIT = 'kjr_event.automation_batch_limit'
PARAM_CONSENT_LEAD = 'kjr_event.consent_reminder_lead_days'
PARAM_PACKING_LEAD = 'kjr_event.packing_list_lead_days'


@tagged('post_install', '-at_install')
class TestKjrEventAutomation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Registration = cls.env['event.registration']
        cls.Param = cls.env['ir.config_parameter'].sudo()
        # Veranstaltung, die in die Vorlauffenster der Tests fällt.
        cls.event = cls.env['event.event'].create({
            'name': 'Zeltlager (Automatik-Test)',
            'is_kjr': True,
            'date_begin': fields.Datetime.now() + timedelta(days=5),
            'date_end': fields.Datetime.now() + timedelta(days=8),
            'kjr_event_type': 'ferienprogramm',
            'requires_parental_consent': True,
        })

    def _reg(self, **kw):
        vals = {
            'event_id': self.event.id,
            'name': 'Teilnehmer',
            'email': 'teilnehmer@example.com',
        }
        vals.update(kw)
        return self.Registration.create(vals)

    def _activate_after_now(self):
        """Automatik so aktivieren, als wäre sie NACH dem Bestand eingeschaltet worden.

        Der Zeitstempel liegt bewusst eine Sekunde in der Zukunft: ``create_date``
        entspricht dem Transaktionsbeginn und ``fields.Datetime.now()`` schneidet
        die Mikrosekunden ab — ohne diesen Abstand wäre die Grenze innerhalb
        derselben Sekunde nicht eindeutig und der Test flatterhaft.
        """
        stamp = fields.Datetime.now() + timedelta(seconds=1)
        self.Param.set_param(PARAM_ACTIVE_FROM, fields.Datetime.to_string(stamp))
        return stamp

    # ── Aktivierungszeitpunkt ────────────────────────────────────────────────

    def test_first_call_writes_the_activation_timestamp(self):
        """Der erste Lauf schreibt den Aktivierungszeitpunkt selbst fest."""
        self.Param.search([('key', '=', PARAM_ACTIVE_FROM)]).unlink()
        stamp = self.Registration._kjr_automation_active_from()
        self.assertTrue(stamp, 'Der erste Lauf muss den Aktivierungszeitpunkt setzen.')
        self.assertEqual(self.Param.get_param(PARAM_ACTIVE_FROM),
                         fields.Datetime.to_string(stamp))

    def test_invalid_timestamp_pauses_the_automation(self):
        """Ein unlesbarer Parameter pausiert die Automatik, statt alles anzuschreiben."""
        self.Param.set_param(PARAM_ACTIVE_FROM, 'kein Datum')
        self.assertFalse(self.Registration._kjr_automation_active_from())
        self.assertFalse(
            self.Registration._kjr_due_registrations(30, 'kjr_packing_list_sent'))

    def test_legacy_registrations_are_not_mailed(self):
        """Vor dem Aktivierungszeitpunkt angelegte Bestandsdaten bleiben unberührt."""
        legacy = self._reg(name='Bestandsanmeldung')
        self._activate_after_now()
        due = self.Registration._kjr_due_registrations(30, 'kjr_packing_list_sent')
        self.assertNotIn(legacy, due,
                         'Bestandsdaten vor dem Aktivierungszeitpunkt dürfen vom '
                         'Cron nicht angeschrieben werden.')
        # Bewusstes Zurücksetzen durch die Administration bezieht Altbestände ein.
        self.Param.set_param(PARAM_ACTIVE_FROM, '2000-01-01 00:00:00')
        due = self.Registration._kjr_due_registrations(30, 'kjr_packing_list_sent')
        self.assertIn(legacy, due)

    # ── Mengenbegrenzung ─────────────────────────────────────────────────────

    def test_batch_limit_caps_each_run(self):
        """Die Obergrenze je Lauf greift (Default 50, hier auf 1 gesetzt)."""
        self.Param.set_param(PARAM_ACTIVE_FROM, '2000-01-01 00:00:00')
        self.Param.set_param(PARAM_BATCH_LIMIT, '1')
        first = self._reg(name='Erste')
        second = self._reg(name='Zweite')
        due = self.Registration._kjr_due_registrations(30, 'kjr_packing_list_sent')
        self.assertEqual(len(due), 1)
        self.assertTrue(due <= (first + second))

    def test_invalid_batch_limit_falls_back_to_default(self):
        """Ein unbrauchbarer Grenzwert darf die Begrenzung nicht aushebeln."""
        self.assertEqual(self.Registration._kjr_param_int(PARAM_BATCH_LIMIT, 50), 50)
        self.Param.set_param(PARAM_BATCH_LIMIT, 'viele')
        self.assertEqual(self.Registration._kjr_param_int(PARAM_BATCH_LIMIT, 50), 50)

    # ── Weitere Filter der Auswahl ───────────────────────────────────────────

    def test_registration_without_recipient_is_skipped(self):
        """Ohne E-Mail-Adresse kein Versand — sonst blockiert der Datensatz jeden Lauf."""
        self.Param.set_param(PARAM_ACTIVE_FROM, '2000-01-01 00:00:00')
        no_mail = self._reg(name='Ohne Adresse', email=False)
        due = self.Registration._kjr_due_registrations(30, 'kjr_packing_list_sent')
        self.assertNotIn(no_mail, due)

    def test_already_sent_registration_is_not_selected_again(self):
        """Der Merker verhindert den doppelten Versand durch den Cron."""
        self.Param.set_param(PARAM_ACTIVE_FROM, '2000-01-01 00:00:00')
        reg = self._reg(name='Schon angeschrieben')
        self.assertIn(reg, self.Registration._kjr_due_registrations(
            30, 'kjr_packing_list_sent'))
        reg._kjr_mark_sent('kjr_packing_list_sent', 'kjr_packing_list_date')
        self.assertTrue(reg.kjr_packing_list_sent)
        self.assertNotIn(reg, self.Registration._kjr_due_registrations(
            30, 'kjr_packing_list_sent'))

    def test_event_outside_the_lead_window_is_not_selected(self):
        """Nur Veranstaltungen innerhalb des Vorlauffensters werden angeschrieben."""
        self.Param.set_param(PARAM_ACTIVE_FROM, '2000-01-01 00:00:00')
        reg = self._reg(name='Noch lange hin')
        # Beginn in 5 Tagen: bei 2 Tagen Vorlauf noch nicht fällig, bei 30 schon.
        self.assertNotIn(reg, self.Registration._kjr_due_registrations(
            2, 'kjr_packing_list_sent'))
        self.assertIn(reg, self.Registration._kjr_due_registrations(
            30, 'kjr_packing_list_sent'))

    # ── Crons ohne gepflegten Vorlauf ────────────────────────────────────────

    def test_crons_send_nothing_without_a_configured_lead(self):
        """Vorlauf 0 = Automatik AUS: beide Crons senden nichts und setzen nichts."""
        self.Param.set_param(PARAM_ACTIVE_FROM, '2000-01-01 00:00:00')
        self.Param.set_param(PARAM_CONSENT_LEAD, '0')
        self.Param.set_param(PARAM_PACKING_LEAD, '0')
        reg = self._reg(name='Unangetastet', birthdate='2015-01-01')
        self.assertEqual(self.Registration._cron_kjr_consent_reminder(), 0)
        self.assertEqual(self.Registration._cron_kjr_packing_list(), 0)
        self.assertFalse(reg.kjr_consent_reminder_sent)
        self.assertFalse(reg.kjr_packing_list_sent)

    def test_consent_cron_only_targets_missing_consents(self):
        """Die Erinnerung geht nur an Anmeldungen mit fehlender Einwilligung."""
        self.Param.set_param(PARAM_ACTIVE_FROM, '2000-01-01 00:00:00')
        minor = self._reg(name='Minderjährig', birthdate='2015-01-01')
        adult = self._reg(name='Volljährig', birthdate='1990-01-01')
        self.assertTrue(minor.consent_missing)
        self.assertFalse(adult.consent_missing)
        due = self.Registration._kjr_due_registrations(
            30, 'kjr_consent_reminder_sent',
            extra_domain=[('consent_missing', '=', True)])
        self.assertIn(minor, due)
        self.assertNotIn(adult, due)
