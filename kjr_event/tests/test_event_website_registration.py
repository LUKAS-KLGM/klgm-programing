# -*- coding: utf-8 -*-
"""E1: Auswertung der Formularwerte der öffentlichen Online-Anmeldung.

Geprüft wird der Teil, der bisher keinen Test hatte und in dem deshalb ein
stiller Datenverlust möglich war: die Prüfung der Auswahlwerte in
``_kjr_valid_selection_value`` / ``_kjr_extract_attendee_values``.

Die fachliche Leitplanke: eine Ernährungsangabe aus dem öffentlichen Formular
MUSS in der Geschäftsstelle ankommen. ``dietary_requirements`` ist
feldgeschützt (``groups=KJR_SENSITIVE_DATA_GROUP``), der Website-Besucher ist
in dieser Gruppe nicht. Ohne ``sudo()`` liefert ``fields_get`` für dieses Feld
NICHTS, der Wertevorrat wäre leer und jede Angabe würde als "unbekannt"
verworfen - die Küchenplanung der Freizeiten arbeitete dann mit leeren Feldern.

Getestet wird ohne laufenden Webserver: ``request`` ist im Controller-Modul ein
Modulattribut und wird hier durch ein Objekt mit genau dem ersetzt, was die
geprüften Methoden brauchen (``env``). Das ist bewusst so klein gehalten - der
Test soll die Wertprüfung belegen und nicht den Website-Stack nachbauen.
"""
from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from odoo.addons.kjr_event.controllers import website_event as kjr_website_event


@tagged('post_install', '-at_install')
class TestKjrWebsiteRegistrationValues(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.controller = kjr_website_event.KjrWebsiteEventController()

    def _public_env(self):
        """Umgebung des öffentlichen Website-Benutzers.

        Er ist in keiner Gruppe und damit auch nicht in
        ``kjr_event.group_kjr_event_care`` - genau die Lage einer anonymen
        Online-Anmeldung.
        """
        public_user = self.env.ref('base.public_user', raise_if_not_found=False)
        if not public_user:
            self.skipTest('Diese Instanz kennt keinen base.public_user.')
        self.assertFalse(
            public_user.has_group('kjr_event.group_kjr_event_care'),
            'Der öffentliche Benutzer darf die sensiblen Felder nicht lesen dürfen, '
            'sonst prüft dieser Test den gefährlichen Fall nicht.')
        return self.env(user=public_user)

    def _extract(self, env, post):
        """``_kjr_extract_attendee_values`` mit ersetztem ``request`` aufrufen."""
        with patch.object(kjr_website_event, 'request', SimpleNamespace(env=env)):
            return self.controller._kjr_extract_attendee_values(post)

    # ------------------------------------------------------------------
    # Feldgeschütztes Auswahlfeld (Befund: stiller Datenverlust)
    # ------------------------------------------------------------------
    def test_dietary_value_survives_public_submission(self):
        """Die Ernährungsangabe einer anonymen Anmeldung wird übernommen."""
        values = self._extract(self._public_env(), {
            '1-name': 'Kind',
            '1-dietary_requirements': 'vegetarian',
        })
        self.assertEqual(
            values, [(1, {'dietary_requirements': 'vegetarian'})],
            'Die Ernährungsangabe darf auf der öffentlichen Website nicht '
            'verworfen werden - sie braucht die Küchenplanung.')

    def test_allergy_value_survives_public_submission(self):
        """Auch der fachlich wichtigste Wert "Allergie" kommt durch."""
        values = self._extract(self._public_env(), {
            '1-name': 'Kind',
            '1-dietary_requirements': 'allergy',
        })
        self.assertEqual(values[0][1].get('dietary_requirements'), 'allergy')

    def test_selection_values_are_known_to_the_public_user(self):
        """Der Wertevorrat des geschützten Feldes ist für die Prüfung lesbar."""
        env = self._public_env()
        with patch.object(kjr_website_event, 'request', SimpleNamespace(env=env)):
            self.assertTrue(self.controller._kjr_valid_selection_value(
                'dietary_requirements', 'vegan'))
            self.assertFalse(self.controller._kjr_valid_selection_value(
                'dietary_requirements', 'kein_solcher_wert'))

    # ------------------------------------------------------------------
    # Nicht geschütztes Auswahlfeld und Ausreißer
    # ------------------------------------------------------------------
    def test_gender_value_survives_public_submission(self):
        """Das Merkmal Geschlecht trägt keinen Feldschutz und kommt ebenfalls durch."""
        values = self._extract(self._public_env(), {
            '1-name': 'Kind',
            '1-kjr_gender': 'no_answer',
        })
        self.assertEqual(values[0][1].get('kjr_gender'), 'no_answer')

    def test_unknown_selection_value_is_dropped(self):
        """Ein präparierter Wert wird verworfen, statt die Anmeldung abzubrechen."""
        values = self._extract(self._public_env(), {
            '1-name': 'Kind',
            '1-dietary_requirements': '<script>',
            '1-kjr_gender': 'kein_geschlecht',
            '1-dietary_note': 'ohne Schweinefleisch',
        })
        self.assertEqual(
            values, [(1, {'dietary_note': 'ohne Schweinefleisch'})],
            'Unbekannte Auswahlwerte fallen heraus, der Rest der Zeile bleibt.')

    def test_several_attendees_keep_their_own_values(self):
        """Je Teilnehmer/in bleibt der eigene Wert am eigenen Zähler."""
        values = self._extract(self._public_env(), {
            '1-name': 'Kind eins',
            '1-dietary_requirements': 'vegan',
            '2-name': 'Kind zwei',
            '2-dietary_requirements': 'halal',
        })
        self.assertEqual(values, [
            (1, {'dietary_requirements': 'vegan'}),
            (2, {'dietary_requirements': 'halal'}),
        ])
