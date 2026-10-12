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
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from odoo.exceptions import UserError
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


@tagged('post_install', '-at_install')
class TestKjrWebsiteConsentPrecheck(TransactionCase):
    """Einwilligung (19.0.5.9.0): Vorprüfung und Aufbereitung des Formulars.

    Die Vorprüfung entscheidet VOR dem Anlegen, ob eine Anmeldung überhaupt
    entstehen darf. Geprüft wird ohne Webserver; das Verfahren 'sign' wird per
    ``patch.object`` auf dem Erweiterungspunkt ``_kjr_consent_mode`` gesetzt,
    damit die Tests nicht von der Brücke kjr_event_sign abhängen.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.controller = kjr_website_event.KjrWebsiteEventController()
        Event = cls.env['event.event']
        base = {
            'date_begin': '2027-07-10 09:00:00',
            'date_end': '2027-07-15 17:00:00',
            'is_kjr': True,
        }
        cls.event = Event.create(dict(base, name='Mit Einwilligung',
                                      requires_parental_consent=True))
        cls.event_none = Event.create(dict(base, name='Ohne Einwilligung',
                                           requires_parental_consent=False))

    def _precheck(self, event, post):
        with patch.object(kjr_website_event, 'request', SimpleNamespace(env=self.env)):
            return self.controller._kjr_consent_precheck(event, post)

    def _sign_mode(self):
        return patch.object(type(self.env['event.event']), '_kjr_consent_mode',
                            autospec=True, return_value='sign')

    # ------------------------------------------------------------------
    # Verfahren 'none' und 'checkbox'
    # ------------------------------------------------------------------
    def test_mode_none_checks_nothing(self):
        """Ohne Einwilligungspflicht wird nichts geprüft, auch kein Geburtsdatum."""
        self.assertIsNone(self._precheck(self.event_none, {'1-name-1': 'Kind'}))

    def test_birthdate_missing(self):
        """Fehlendes oder ungültiges Geburtsdatum."""
        self.assertEqual(self._precheck(self.event, {'1-name-1': 'Kind'}),
                         'kjr_birthdate_missing')
        self.assertEqual(self._precheck(self.event, {
            '1-name-1': 'Kind', '1-birthdate': 'kein-datum'}), 'kjr_birthdate_missing')

    def test_checkbox_minor_without_consent(self):
        """Minderjährig ohne Häkchen."""
        self.assertEqual(self._precheck(self.event, {
            '1-name-1': 'Kind', '1-birthdate': '2015-01-01'}), 'kjr_consent_missing')

    def test_checkbox_minor_with_consent(self):
        self.assertIsNone(self._precheck(self.event, {
            '1-name-1': 'Kind', '1-birthdate': '2015-01-01', '1-parental_consent': '1'}))

    def test_adult_is_ok(self):
        """Volljährig am Beginntag: keine Einwilligung nötig."""
        self.assertIsNone(self._precheck(self.event, {
            '1-name-1': 'Erwachsen', '1-birthdate': '2009-07-10'}))

    def test_order_wide_answers_are_no_person(self):
        """Zähler 0 (einmal je Bestellung gefragt) ist keine Teilnehmerin."""
        self.assertIsNone(self._precheck(self.event, {
            '0-email-3': 'familie@example.com',
            '1-name-1': 'Erwachsen', '1-birthdate': '1990-01-01'}))

    # ------------------------------------------------------------------
    # Verfahren 'sign'
    # ------------------------------------------------------------------
    def test_sign_minor_without_any_email(self):
        with self._sign_mode():
            self.event.invalidate_recordset(['kjr_consent_mode'])
            self.assertEqual(self._precheck(self.event, {
                '1-name-1': 'Kind', '1-birthdate': '2015-01-01',
                '1-guardian_email': 'keine-adresse'}), 'kjr_guardian_email_missing')
        self.event.invalidate_recordset(['kjr_consent_mode'])

    def test_sign_minor_with_guardian_email(self):
        with self._sign_mode():
            self.event.invalidate_recordset(['kjr_consent_mode'])
            self.assertIsNone(self._precheck(self.event, {
                '1-name-1': 'Kind', '1-birthdate': '2015-01-01',
                '1-guardian_name': 'Erika Muster',
                '1-guardian_email': 'mutter@beispiel.de'}))
        self.event.invalidate_recordset(['kjr_consent_mode'])

    def test_sign_minor_falls_back_to_registration_email(self):
        """Ohne eigene Adresse der Erziehungsberechtigten genügt die Anmelde-E-Mail."""
        with self._sign_mode():
            self.event.invalidate_recordset(['kjr_consent_mode'])
            self.assertIsNone(self._precheck(self.event, {
                '1-name-1': 'Kind', '1-birthdate': '2015-01-01',
                '1-guardian_name': 'Erika Muster',
                '1-email-2': 'eltern@example.com'}))
        self.event.invalidate_recordset(['kjr_consent_mode'])

    def test_sign_minor_without_guardian_name(self):
        """19.0.5.10.0: Verfahren 'sign', minderjährig, Name der/des
        Erziehungsberechtigten fehlt (oder nur Leerraum): eigener Fehlercode.
        Er wird in das Einwilligungsformular übernommen und ist dort
        schreibgeschützt."""
        with self._sign_mode():
            self.event.invalidate_recordset(['kjr_consent_mode'])
            for guardian_name in (None, '', '   '):
                post = {'1-name-1': 'Kind', '1-birthdate': '2015-01-01',
                        '1-guardian_email': 'mutter@beispiel.de'}
                if guardian_name is not None:
                    post['1-guardian_name'] = guardian_name
                self.assertEqual(self._precheck(self.event, post),
                                 'kjr_guardian_name_missing', repr(guardian_name))
            # Die fehlende E-Mail bleibt der vorrangige Fehler.
            self.assertEqual(self._precheck(self.event, {
                '1-name-1': 'Kind', '1-birthdate': '2015-01-01'}),
                'kjr_guardian_email_missing')
            # Zweite Teilnehmerin ohne Namen der Eltern: auch dann Fehler.
            self.assertEqual(self._precheck(self.event, {
                '1-name-1': 'Kind A', '1-birthdate': '2015-01-01',
                '1-guardian_name': 'Erika Muster',
                '1-guardian_email': 'mutter@beispiel.de',
                '2-name-1': 'Kind B', '2-birthdate': '2016-01-01',
                '2-guardian_email': 'mutter@beispiel.de'}),
                'kjr_guardian_name_missing')
            # Volljährig: kein Name der Eltern nötig.
            self.assertIsNone(self._precheck(self.event, {
                '1-name-1': 'Erwachsen', '1-birthdate': '1990-01-01',
                '1-email-2': 'selbst@example.com'}))
        self.event.invalidate_recordset(['kjr_consent_mode'])

    def test_sign_minor_guardian_name_is_child_name(self):
        """19.0.5.10.0 (gemeldeter Fall): Im Feld der Erziehungsberechtigten
        steht der Name des Kindes (auch in anderer Schreibweise oder mit
        Mehrfach-Leerraum). Die Einwilligung trüge sonst den Kindernamen als
        unterschreibende Person: eigener Fehlercode."""
        with self._sign_mode():
            self.event.invalidate_recordset(['kjr_consent_mode'])
            for guardian_name in ('Lina Muster', '  lina   MUSTER '):
                self.assertEqual(self._precheck(self.event, {
                    '1-name-1': 'Lina Muster', '1-birthdate': '2015-01-01',
                    '1-guardian_name': guardian_name,
                    '1-guardian_email': 'mutter@beispiel.de'}),
                    'kjr_guardian_name_is_child', repr(guardian_name))
            # Zweite Teilnehmerin: Vergleich je Person (Name aus "2-name-<id>").
            self.assertEqual(self._precheck(self.event, {
                '1-name-1': 'Lina Muster', '1-birthdate': '2015-01-01',
                '1-guardian_name': 'Erika Muster',
                '1-guardian_email': 'mutter@beispiel.de',
                '2-name-1': 'Paul Muster', '2-birthdate': '2016-01-01',
                '2-guardian_name': 'Paul Muster',
                '2-guardian_email': 'mutter@beispiel.de'}),
                'kjr_guardian_name_is_child')
            # Name eines Geschwisterkindes ist kein Fehler dieser Prüfung.
            self.assertIsNone(self._precheck(self.event, {
                '1-name-1': 'Lina Muster', '1-birthdate': '2015-01-01',
                '1-guardian_name': 'Erika Muster',
                '1-guardian_email': 'mutter@beispiel.de',
                '2-name-1': 'Paul Muster', '2-birthdate': '2016-01-01',
                '2-guardian_name': 'Erika Muster',
                '2-guardian_email': 'mutter@beispiel.de'}))
            # Volljährig: keine Prüfung.
            self.assertIsNone(self._precheck(self.event, {
                '1-name-1': 'Erwachsen', '1-birthdate': '1990-01-01',
                '1-guardian_name': 'Erwachsen',
                '1-email-2': 'selbst@example.com'}))
        self.event.invalidate_recordset(['kjr_consent_mode'])
        # Verfahren 'checkbox': unverändert (Name der Eltern freiwillig).
        self.assertIsNone(self._precheck(self.event, {
            '1-name-1': 'Kind', '1-birthdate': '2015-01-01',
            '1-guardian_name': 'Kind', '1-parental_consent': '1'}))

    def test_error_message_guardian_name_is_child(self):
        """Der Fehlercode erzeugt auf der Anmeldeseite einen Hinweis."""
        arch = self.env.ref('kjr_event.registration_template_kjr_consent_errors').arch
        self.assertIn("registration_error_code == 'kjr_guardian_name_is_child'", arch)
        # Die Meldung nennt beide Felder (nicht feststellbar, welches falsch ist).
        self.assertIn('Bitte prüfen Sie beide Angaben', arch)
        self.assertIn('Name des Kindes / Teilnehmer/in', arch)
        self.assertNotIn('nicht den Namen des Kindes', arch)

    def test_name_question_label_names_the_child(self):
        """19.0.5.10.0: Das Kernfeld "Name" heißt je Teilnehmer/in "Name des
        Kindes / Teilnehmer/in"; der Fragetitel in der Datenbank bleibt, und
        Fragen je Bestellung (Index 0) sowie andere Fragetypen behalten ihn."""
        name_question = self.env['event.question'].create({
            'title': 'Name', 'question_type': 'name'})
        email_question = self.env['event.question'].create({
            'title': 'E-Mail', 'question_type': 'email'})
        base = {
            'event': self.event, 'counter': 1, 'default_first_attendee': {},
            'input_type_by_question_type': {
                'name': 'text', 'email': 'email', 'phone': 'tel', 'company_name': 'text'},
        }

        def render(question, index):
            return str(self.env['ir.qweb']._render(
                'website_event.registration_event_question',
                dict(base, question=question, registration_index=index)))

        self.assertIn('Name des Kindes / Teilnehmer/in', render(name_question, 1))
        self.assertNotIn('Name des Kindes', render(name_question, 0))
        self.assertNotIn('Name des Kindes', render(email_question, 1))
        self.assertIn('E-Mail', render(email_question, 1))
        self.assertEqual(name_question.title, 'Name')

    def test_name_question_not_prefilled_with_account_name(self):
        """19.0.5.10.0: Der Kern befuellt das erste Ticket mit
        default_first_attendee (Name des Benutzerkontos bzw. Website-Besuchers,
        meist ein Elternteil). Das Namensfeld des Kindes bleibt leer, E-Mail
        und Fragen je Bestellung behalten die Kern-Vorbefuellung."""
        name_question = self.env['event.question'].create({
            'title': 'Name', 'question_type': 'name'})
        email_question = self.env['event.question'].create({
            'title': 'E-Mail', 'question_type': 'email'})
        base = {
            'event': self.event, 'counter': 1,
            'default_first_attendee': {
                'name': 'Elternteil Konto', 'email': 'eltern@example.com'},
            'input_type_by_question_type': {
                'name': 'text', 'email': 'email', 'phone': 'tel', 'company_name': 'text'},
        }

        def render(question, index):
            return str(self.env['ir.qweb']._render(
                'website_event.registration_event_question',
                dict(base, question=question, registration_index=index)))

        child = render(name_question, 1)
        self.assertNotIn('Elternteil Konto', child)
        self.assertIn('name="1-name-%s"' % name_question.id, child)
        self.assertIn('eltern@example.com', render(email_question, 1))
        # Frage je Bestellung (Index 0): Kernverhalten unveraendert.
        self.assertIn('Elternteil Konto', render(name_question, 0))

    def test_checkbox_minor_needs_no_guardian_name(self):
        """Im Verfahren 'checkbox' bleibt der Name der Eltern freiwillig."""
        self.assertIsNone(self._precheck(self.event, {
            '1-name-1': 'Kind', '1-birthdate': '2015-01-01', '1-parental_consent': '1'}))

    def test_sign_drops_parental_consent(self):
        """Im Verfahren 'sign' ersetzt kein Häkchen die Unterschrift."""
        values = [(1, {'parental_consent': True, 'birthdate': '2015-01-01'})]
        self.controller._kjr_apply_consent_mode(values, 'sign')
        self.assertEqual(values, [(1, {'birthdate': '2015-01-01'})])

    def test_checkbox_marks_source_website(self):
        values = [(1, {'parental_consent': True})]
        self.controller._kjr_apply_consent_mode(values, 'checkbox')
        self.assertEqual(values[0][1].get('kjr_consent_source'), 'website')

    # ------------------------------------------------------------------
    # Formularwerte
    # ------------------------------------------------------------------
    def test_guardian_email_is_normalized(self):
        with patch.object(kjr_website_event, 'request', SimpleNamespace(env=self.env)):
            values = self.controller._kjr_extract_attendee_values({
                '1-name': 'Kind', '1-guardian_email': ' Mutter@Beispiel.DE '})
        self.assertEqual(values, [(1, {'guardian_email': 'mutter@beispiel.de'})])

    def test_invalid_guardian_email_is_dropped(self):
        with patch.object(kjr_website_event, 'request', SimpleNamespace(env=self.env)):
            values = self.controller._kjr_extract_attendee_values({
                '1-name': 'Kind', '1-guardian_email': 'keine adresse'})
        self.assertEqual(values, [(1, {})])

    def test_match_values_understand_question_keys(self):
        """Odoo 19 sendet Name/E-Mail/Telefon als ``<n>-<typ>-<frage-id>``."""
        match = self.controller._kjr_extract_attendee_match_values({
            '1-name-5': 'Kind', '1-email-6': 'kind@example.com',
            '0-phone-7': '0831 12345', '1-event_ticket_id': '4',
        })
        self.assertEqual(match, {1: {
            'name': 'Kind', 'email': 'kind@example.com',
            'phone': '0831 12345', 'event_ticket_id': '4'}})

    def test_form_counters(self):
        with patch.object(kjr_website_event, 'request', SimpleNamespace(env=self.env)):
            self.assertEqual(self.controller._kjr_form_counters({
                '0-email-3': 'x', '1-name-1': 'a', '2-event_ticket_id': '0',
                '2-birthdate': '2015-01-01', 'csrf_token': 'x'}), [1, 2])
            # Jeder Index, zu dem der Kern eine Anmeldung anlegt, zählt mit,
            # auch ohne Name oder Ticket (nur eine E-Mail-Antwort).
            self.assertEqual(self.controller._kjr_form_counters({
                '1-name-1': 'a', '3-email-5': 'b@example.com'}), [1, 3])

    def test_precheck_covers_every_core_registration(self):
        """Ein präparierter POST mit zusätzlichem Index umgeht die Vorprüfung nicht."""
        # Index 2 nur mit einer E-Mail-Antwort: der Kern legt dafür eine
        # Anmeldung an, also muss auch ihr Geburtsdatum vorliegen.
        self.assertEqual(self._precheck(self.event, {
            '1-name-1': 'Erwachsen', '1-birthdate': '1990-01-01',
            '2-email-5': 'kind@example.com'}), 'kjr_birthdate_missing')
        # Indizes, die das Formular nie erzeugt, werden fail-closed abgewiesen.
        for key in ('0-email', '01-name-1', 'x-name'):
            self.assertEqual(self._precheck(self.event, {
                '1-name-1': 'Erwachsen', '1-birthdate': '1990-01-01',
                key: 'Wert'}), 'kjr_birthdate_missing', key)
        # Leere Werte legen im Kern keine Anmeldung an.
        self.assertIsNone(self._precheck(self.event, {
            '1-name-1': 'Erwachsen', '1-birthdate': '1990-01-01', '2-email-5': ''}))

    def test_write_attendee_values_returns_recordset(self):
        """Die Methode liefert immer ein Recordset, auch ohne Treffer."""
        reg = self.env['event.registration'].create({
            'event_id': self.event.id, 'name': 'Kind'})
        tx_start = self.env.cr.now() - timedelta(seconds=1)
        with patch.object(kjr_website_event, 'request', SimpleNamespace(env=self.env)):
            found = self.controller._kjr_write_attendee_values(
                self.event, [(1, {'kjr_gender': 'no_answer'})], {1: {'name': 'Kind'}},
                tx_start)
            empty = self.controller._kjr_write_attendee_values(
                self.event_none, [(1, {'kjr_gender': 'no_answer'})], {1: {'name': 'Kind'}},
                tx_start)
        self.assertIn(reg, found)
        self.assertEqual(reg.kjr_gender, 'no_answer')
        self.assertEqual(empty._name, 'event.registration')
        self.assertFalse(empty)

    # ------------------------------------------------------------------
    # Spam-Schutz vorab (kjr_website_antispam, optional)
    # ------------------------------------------------------------------
    def _antispam_rejects(self, reason):
        """``_kjr_antispam_rejects`` mit ersetzten Methoden des Spam-Schutzes.

        ``create=True``: kjr_event hängt nicht von kjr_website_antispam ab, die
        Methoden existieren also nicht zwingend.
        """
        IrHttp = type(self.env['ir.http'])
        calls = []

        def precheck(_self, action):
            return reason

        def check(_self, action):
            calls.append(action)
            raise UserError('abgewiesen')

        with patch.object(IrHttp, '_kjr_antispam_precheck', precheck, create=True), \
                patch.object(IrHttp, '_kjr_antispam_check', check, create=True), \
                patch.object(kjr_website_event, 'request', SimpleNamespace(env=self.env)):
            return self.controller._kjr_antispam_rejects(), calls

    def test_antispam_precheck_rejects_before_super(self):
        """Ein Abweisungsgrund führt VOR super() zur Abweisung (Log über _kjr_antispam_check)."""
        rejected, calls = self._antispam_rejects('honeypot')
        self.assertTrue(rejected)
        self.assertEqual(calls, ['website_event_registration'])

    def test_antispam_precheck_passes(self):
        """Ohne Grund (Modus log/off oder gültiges Token) geht die Anmeldung weiter."""
        rejected, calls = self._antispam_rejects(None)
        self.assertFalse(rejected)
        self.assertEqual(calls, [])
