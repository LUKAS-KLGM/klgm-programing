# -*- coding: utf-8 -*-
"""Tests der Datenschutzangaben in den Einstellungen.

Die sechs Angaben des Datenschutzblocks (Art. 13 DSGVO) werden auf allen
öffentlichen Formularen dieser Modulfamilie aus Systemparametern gelesen. Seit
19.0.15.7.0 gibt es dafür eine Eingabemaske in den Einstellungen. Geprüft wird,
dass sie auf genau die Schlüssel schreibt, die die Vorlagen lesen, und dass ein
geleertes Feld den Parameter wieder entfernt (dann steht auf den Formularen
wieder der sichtbare Warnhinweis statt einer stillen Leerstelle).
"""
from odoo.tests.common import TransactionCase
from odoo.tests import tagged

# Die Schlüssel sind der Vertrag zwischen Einstellungen und Vorlagen. Sie werden
# ausserhalb von kjr_grant auch von kjr_event, kjr_facility und kjr_rental
# gelesen und dürfen sich deshalb nicht unbemerkt ändern.
PRIVACY_PARAMS = {
    'kjr_privacy_operator': 'kjr.privacy.operator',
    'kjr_privacy_controller': 'kjr.privacy.controller',
    'kjr_privacy_dpo': 'kjr.privacy.dpo',
    'kjr_privacy_legal_basis': 'kjr.privacy.legal_basis',
    'kjr_privacy_retention': 'kjr.privacy.retention',
    'kjr_privacy_authority': 'kjr.privacy.authority',
}


@tagged('post_install', '-at_install')
class TestKjrPrivacySettings(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Settings = cls.env['res.config.settings']
        cls.Param = cls.env['ir.config_parameter'].sudo()

    def test_alle_sechs_felder_schreiben_ihren_systemparameter(self):
        """Jedes Feld schreibt beim Speichern genau den Schlüssel, den die
        Vorlagen mit get_param lesen. Ein Tippfehler im Schlüssel bliebe sonst
        unbemerkt: die Formulare zeigten weiter den Warnhinweis."""
        werte = {name: 'Testwert %s' % name for name in PRIVACY_PARAMS}
        self.Settings.create(werte).execute()
        for name, schluessel in PRIVACY_PARAMS.items():
            self.assertEqual(self.Param.get_param(schluessel), werte[name])

    def test_gespeicherte_werte_werden_wieder_angezeigt(self):
        """Was in den Parametern steht, muss beim nächsten Öffnen der
        Einstellungen wieder im Feld stehen."""
        self.Param.set_param('kjr.privacy.controller', 'Verantwortliche Stelle')
        self.assertEqual(
            self.Settings.create({}).kjr_privacy_controller,
            'Verantwortliche Stelle',
        )

    def test_geleertes_feld_entfernt_den_parameter(self):
        """Ein geleertes Feld löscht den Parameter. Dann greift auf den
        Formularen wieder der sichtbare Warnhinweis."""
        self.Param.set_param('kjr.privacy.dpo', 'Alte Angabe')
        self.Settings.create({'kjr_privacy_dpo': False}).execute()
        self.assertFalse(self.Param.get_param('kjr.privacy.dpo'))
