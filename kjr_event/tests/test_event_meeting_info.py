# -*- coding: utf-8 -*-
"""Tests für E12: Treffpunkt, Wichtig, Webseite."""
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestKjrEventMeetingInfo(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.event = cls.env['event.event'].create({
            'name': 'Tagesfahrt zur Comic Con Dornbirn',
            'date_begin': '2026-02-14 08:45:00',
            'date_end': '2026-02-14 18:00:00',
        })

    def test_fields_empty_by_default(self):
        """Neue Felder sind standardmäßig leer – kein Pflichtinhalt erzwungen."""
        self.assertFalse(self.event.kjr_meeting_point)
        self.assertFalse(self.event.kjr_important_note)
        self.assertFalse(self.event.kjr_website_url)

    def test_fields_storable_and_readable(self):
        """Alle drei Felder lassen sich setzen und wieder auslesen."""
        self.event.write({
            'kjr_meeting_point': 'Vordereingang des Landratsamtes Oberallgäu.',
            'kjr_important_note': '<p>Bitte Schüler*innen-Ausweis mitbringen.</p>',
            'kjr_website_url': 'https://www.europapark.de/de/park',
        })
        self.assertIn('Vordereingang', self.event.kjr_meeting_point)
        self.assertIn('Schüler', self.event.kjr_important_note)
        self.assertEqual(self.event.kjr_website_url, 'https://www.europapark.de/de/park')
