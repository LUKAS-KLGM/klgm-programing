# -*- coding: utf-8 -*-
"""Tests der Brücke Einrichtungsbuchung ↔ Zuschussantrag."""
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestKjrFacilityGrantBridge(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'Jugendverband Test',
            'is_company': True, 'is_kjr_member': True, 'kjr_vr_right': True,
        })
        cls.facility = cls.env['kjr.facility'].create({
            'name': 'Jugendhaus Testberg', 'facility_type': 'house',
        })

    def _booking(self, **kw):
        vals = {
            'facility_id': self.facility.id,
            'partner_id': self.partner.id,
            'group_name': 'Sommerfreizeit',
            'check_in': '2026-08-01',
            'check_out': '2026-08-05',
            'participant_count': 24,
            'leader_count': 4,
        }
        vals.update(kw)
        return self.env['kjr.facility.booking'].create(vals)

    def test_create_grant_from_overnight_booking(self):
        """Mehrtägige Buchung → vorbefüllter, verknüpfter Antrag der Förderart § 4.1b."""
        booking = self._booking()
        action = booking.action_create_grant_application()
        app = booking.grant_application_id
        self.assertTrue(app, 'Antrag muss verknüpft sein.')
        self.assertEqual(action['res_id'], app.id)
        self.assertEqual(app.grant_type_id.code, '4_1b')
        self.assertEqual(app.partner_id, self.partner)
        self.assertEqual(str(app.measure_start), '2026-08-01')
        self.assertEqual(str(app.measure_end), '2026-08-05')
        self.assertEqual(app.tn_count, 24)
        self.assertEqual(app.tn_leader_count, 4)
        self.assertEqual(app.measure_name, 'Sommerfreizeit')
        self.assertEqual(app.cost_accommodation, booking.amount_total)
        # Entkoppelte Förderfelder werden gespiegelt
        self.assertTrue(booking.is_grant_funded)
        self.assertEqual(booking.grant_reference, app.name)

    def test_same_day_booking_is_rejected(self):
        """Eine Einrichtungsbuchung ist immer eine Übernachtung: An-/Abreise am
        selben Tag wird vom Facility-Modul abgelehnt (Grundlage für 4_1b-Default)."""
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self._booking(check_in='2026-08-01', check_out='2026-08-01')

    def test_duplicate_creation_blocked(self):
        """Ein zweiter Antrag aus derselben Buchung wird verhindert."""
        booking = self._booking()
        booking.action_create_grant_application()
        with self.assertRaises(UserError):
            booking.action_create_grant_application()

    def test_reverse_link_and_count(self):
        """Der Antrag kennt die verknüpften Buchungen (Gegenrichtung)."""
        booking = self._booking()
        booking.action_create_grant_application()
        app = booking.grant_application_id
        self.assertIn(booking, app.facility_booking_ids)
        self.assertEqual(app.facility_booking_count, 1)

    def test_onchange_mirrors_reference(self):
        """Manuelles Verknüpfen setzt is_grant_funded und das Aktenzeichen."""
        app = self.env['kjr.grant.application'].create({
            'partner_id': self.partner.id,
            'grant_type_id': self.env.ref('kjr_grant.grant_type_4_1b').id,
            'measure_name': 'Direkt', 'measure_start': '2026-08-01',
            'measure_end': '2026-08-03',
        })
        booking = self._booking()
        booking.grant_application_id = app.id
        booking._onchange_grant_application_id()
        self.assertTrue(booking.is_grant_funded)
        self.assertEqual(booking.grant_reference, app.name)
