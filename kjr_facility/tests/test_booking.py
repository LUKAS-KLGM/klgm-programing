# -*- coding: utf-8 -*-
"""Tests der Einrichtungsbuchung: Doppelbelegung, Kapazität, Beträge, Betreuung."""
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import ValidationError


@tagged('post_install', '-at_install')
class TestKjrFacilityBooking(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Gruppe Test'})
        cls.facility = cls.env['kjr.facility'].create({
            'name': 'Jugendhaus Diepolz', 'facility_type': 'house',
            'capacity': 42, 'supervision_ratio': 5,
        })
        cls.room = cls.env['kjr.facility.room'].create({
            'name': 'Schlafsaal 1', 'facility_id': cls.facility.id, 'capacity': 20,
        })
        cls.tariff = cls.env['kjr.facility.tariff'].create({
            'name': 'Mitglied', 'facility_id': cls.facility.id,
            'price_per_person_night': 20.0,
        })

    def _booking(self, **kw):
        vals = {
            'facility_id': self.facility.id, 'partner_id': self.partner.id,
            'check_in': '2026-08-01', 'check_out': '2026-08-05',
            'participant_count': 10,
        }
        vals.update(kw)
        return self.env['kjr.facility.booking'].create(vals)

    def test_nights_computation(self):
        """Nächte = Abreise − Anreise."""
        self.assertEqual(self._booking().nights, 4)

    def test_date_validation(self):
        """Abreise muss nach Anreise liegen."""
        with self.assertRaises(ValidationError):
            self._booking(check_in='2026-08-05', check_out='2026-08-01')

    def test_capacity_constraint(self):
        """Teilnehmerzahl über Einrichtungskapazität wird abgelehnt."""
        with self.assertRaises(ValidationError):
            self._booking(participant_count=50)

    def test_supervision_ratio(self):
        """Betreuungsschlüssel: 2 Betreuer × 5 = 10 ≥ 10 TN → ausreichend;
        1 Betreuer × 5 = 5 < 10 → nicht ausreichend."""
        b = self._booking(participant_count=10, leader_count=2)
        self.assertTrue(b.supervision_ok)
        b.leader_count = 1
        self.assertFalse(b.supervision_ok)

    def test_amount_accommodation(self):
        """Unterkunft = Nächte × TN × Preis/Person/Nacht (4 × 10 × 20 = 800)."""
        b = self._booking(tariff_id=self.tariff.id, participant_count=10)
        self.assertEqual(b.amount_accommodation, 800.0)
        self.assertEqual(b.amount_total, 800.0)

    def test_find_overlapping_detects_conflict(self):
        """Überlappende Buchungen derselben Einrichtung werden erkannt."""
        self._booking(check_in='2026-08-01', check_out='2026-08-05', state='confirmed')
        overlap = self.env['kjr.facility.booking']._find_overlapping(
            self.facility.id, '2026-08-04', '2026-08-08')
        self.assertTrue(overlap, 'Überlappung muss erkannt werden.')
        # Kein Konflikt bei anschließendem, nicht überlappendem Zeitraum
        no_overlap = self.env['kjr.facility.booking']._find_overlapping(
            self.facility.id, '2026-08-05', '2026-08-09')
        self.assertFalse(no_overlap)

    def test_double_booking_same_room_blocked(self):
        """Zwei Buchungen mit demselben Raum und überlappendem Zeitraum → Sperre."""
        self._booking(check_in='2026-08-01', check_out='2026-08-05',
                      state='confirmed', room_ids=[(6, 0, [self.room.id])])
        with self.assertRaises(ValidationError):
            self._booking(check_in='2026-08-03', check_out='2026-08-07',
                          state='confirmed', room_ids=[(6, 0, [self.room.id])])

    # ── Schutz gegen Massenversand beim ersten Cron-Lauf ─────────────────────
    # Die Merker-Felder stehen bei übernommenen Buchungen auf False. Ohne den
    # Aktivierungszeitpunkt würde der erste Lauf nach Go-live den kompletten
    # Bestand anschreiben. Dieser Test darf nicht "weggetestet" werden.
    def test_automation_skips_legacy_bookings(self):
        """Der erste Lauf schreibt den Aktivierungszeitpunkt fest; vorher
        angelegte Buchungen bleiben von der Automatik unberührt."""
        Booking = self.env['kjr.facility.booking']
        Param = self.env['ir.config_parameter'].sudo()
        Param.search([('key', '=', Booking._AUTOMATION_ACTIVE_FROM)]).unlink()
        legacy = self._booking()
        self.assertTrue(Booking._automation_active_from(),
                        'Der erste Lauf muss den Aktivierungszeitpunkt setzen.')
        self.assertNotIn(legacy, Booking._automation_search([('id', '=', legacy.id)]))
        # Bewusstes Zurücksetzen durch die Administration bezieht Altbestände ein.
        Param.set_param(Booking._AUTOMATION_ACTIVE_FROM, '2000-01-01 00:00:00')
        self.assertIn(legacy, Booking._automation_search([('id', '=', legacy.id)]))

    def test_automation_batch_limit_caps_each_run(self):
        """Die Mengenbegrenzung je Lauf greift (Default 50, hier auf 1 gesetzt)."""
        Booking = self.env['kjr.facility.booking']
        Param = self.env['ir.config_parameter'].sudo()
        Param.set_param(Booking._AUTOMATION_ACTIVE_FROM, '2000-01-01 00:00:00')
        Param.set_param(Booking._AUTOMATION_BATCH_LIMIT, '1')
        first = self._booking()
        second = self._booking()
        found = Booking._automation_search([('id', 'in', (first + second).ids)])
        self.assertEqual(len(found), 1)
