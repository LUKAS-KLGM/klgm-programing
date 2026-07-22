# -*- coding: utf-8 -*-
"""Tests für E13: Mindestanzahl Teilnehmer (kjr_seats_min)."""
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestKjrEventSeatsMin(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.event = cls.env['event.event'].create({
            'name': 'Winterfreizeit 2026',
            'date_begin': '2026-12-27 09:00:00',
            'date_end': '2026-12-30 17:00:00',
            'kjr_seats_min': 3,
        })

    def _reg(self, **kw):
        vals = {'event_id': self.event.id, 'name': 'Teilnehmer'}
        vals.update(kw)
        return self.env['event.registration'].create(vals)

    def test_min_not_reached_by_default(self):
        """Ohne Anmeldungen ist die Mindestanzahl (3) nicht erreicht."""
        self.assertEqual(self.event.seats_taken, 0)
        self.assertFalse(self.event.kjr_seats_min_reached)

    def test_min_reached_once_enough_registrations(self):
        """Mit genügend offenen Anmeldungen gilt die Mindestanzahl als erreicht."""
        for _ in range(3):
            self._reg()
        self.assertEqual(self.event.seats_taken, 3)
        self.assertTrue(self.event.kjr_seats_min_reached)

    def test_no_minimum_means_always_reached(self):
        """kjr_seats_min = 0 (Standard) => immer als erreicht markiert."""
        event = self.env['event.event'].create({
            'name': 'Spontanausflug',
            'date_begin': '2026-09-01 09:00:00',
            'date_end': '2026-09-01 17:00:00',
        })
        self.assertEqual(event.kjr_seats_min, 0)
        self.assertTrue(event.kjr_seats_min_reached)
