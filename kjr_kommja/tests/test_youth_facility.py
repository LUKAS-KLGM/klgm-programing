# -*- coding: utf-8 -*-
"""Tests des KommJA-Einrichtungsverzeichnisses."""
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import ValidationError


@tagged('post_install', '-at_install')
class TestKjrYouthFacility(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Facility = cls.env['kjr.youth.facility']

    def test_create_and_age_range(self):
        """Anlegen + berechnete Altersgruppe."""
        f = self.Facility.create({
            'name': 'Jugendzentrum Oberstdorf', 'facility_type': 'jz',
            'municipality': 'Oberstdorf', 'age_min': 12, 'age_max': 18,
        })
        self.assertEqual(f.age_range, '12–18 Jahre')

    def test_age_range_open_ended(self):
        """Altersgruppe mit nur Unter-/Obergrenze."""
        f = self.Facility.create({'name': 'Treff', 'facility_type': 'jt', 'age_min': 14})
        self.assertEqual(f.age_range, 'ab 14 Jahre')
        f2 = self.Facility.create({'name': 'Treff2', 'facility_type': 'jt', 'age_max': 21})
        self.assertEqual(f2.age_range, 'bis 21 Jahre')

    def test_age_validation(self):
        """Höchstalter < Mindestalter ist unzulässig."""
        with self.assertRaises(ValidationError):
            self.Facility.create({
                'name': 'Falsch', 'facility_type': 'jz', 'age_min': 18, 'age_max': 12,
            })

    def test_negative_age_rejected(self):
        """Negative Altersangaben sind unzulässig."""
        with self.assertRaises(ValidationError):
            self.Facility.create({'name': 'Neg', 'facility_type': 'jz', 'age_min': -1})
