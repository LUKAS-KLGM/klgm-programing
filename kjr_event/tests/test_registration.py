# -*- coding: utf-8 -*-
"""Tests der KJR-Ferienprogramm-/Schulungsanmeldung: Alter, Einwilligung, Juleica."""
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestKjrEventRegistration(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.event = cls.env['event.event'].create({
            'name': 'Sommerferienprogramm 2026',
            'date_begin': '2026-08-01 09:00:00',
            'date_end': '2026-08-05 17:00:00',
            'kjr_event_type': 'ferienprogramm',
            'kjr_min_age': 12, 'kjr_max_age': 18,
            'requires_parental_consent': True,
        })

    def _reg(self, **kw):
        vals = {'event_id': self.event.id, 'name': 'Teilnehmer'}
        vals.update(kw)
        return self.env['event.registration'].create(vals)

    def test_age_and_minor_flag(self):
        """Alter wird zum Veranstaltungsbeginn berechnet; <18 = minderjährig."""
        reg = self._reg(birthdate='2010-01-01')  # bei Beginn 2026-08-01: 16 Jahre
        self.assertEqual(reg.kjr_age, 16)
        self.assertTrue(reg.is_minor)

    def test_age_in_range(self):
        """16-Jährige/r liegt im Altersfenster 12–18 → nicht außerhalb."""
        reg = self._reg(birthdate='2010-01-01')
        self.assertFalse(reg.age_out_of_range)

    def test_age_below_range(self):
        """8-Jährige/r liegt unter dem Mindestalter 12 → außerhalb."""
        reg = self._reg(birthdate='2018-01-01')
        self.assertEqual(reg.kjr_age, 8)
        self.assertTrue(reg.age_out_of_range)

    def test_consent_missing_for_minor(self):
        """Minderjährige/r ohne Einwilligung → Einwilligung fehlt; mit Einwilligung nicht."""
        reg = self._reg(birthdate='2010-01-01')
        self.assertTrue(reg.consent_missing)
        reg.parental_consent = True
        self.assertFalse(reg.consent_missing)

    def test_consent_not_required_for_adult(self):
        """Volljährige/r braucht keine Einwilligung der Erziehungsberechtigten."""
        reg = self._reg(birthdate='1990-01-01')
        self.assertFalse(reg.is_minor)
        self.assertFalse(reg.consent_missing)

    def test_juleica_valid_three_years(self):
        """Juleica-Schulung: ausgestellte Juleica gilt ab Veranstaltungsbeginn 3 Jahre."""
        course = self.env['event.event'].create({
            'name': 'Juleica-Grundkurs',
            'date_begin': '2026-08-01 09:00:00',
            'date_end': '2026-08-03 17:00:00',
            'kjr_event_type': 'juleica_course',
        })
        self.assertTrue(course.is_juleica_course)
        reg = self.env['event.registration'].create({
            'event_id': course.id, 'name': 'Leiter', 'juleica_issued': True,
        })
        self.assertEqual(str(reg.juleica_valid_until), '2029-08-01')
