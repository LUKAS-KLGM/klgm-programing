# -*- coding: utf-8 -*-
"""E2: Statistik-Export (Meldung an das Landesamt).

Die Datei geht an eine Behörde. Die Zusicherungen hier schützen die beiden
Fehlerarten, die in einer CSV lautlos passieren:

* Eine Spalte verrutscht, weil Kopf und Zeile unterschiedlich lang sind. Dafür
  gibt es eigene Längentests, für die Standard- UND für eine abweichende
  Altersklassen-Konfiguration.
* Ein Wert ist erfunden. Deshalb: ohne gepflegte PLZ bleibt die Spalte leer
  (kein "unbekannt"), und eine unbrauchbare Altersklassen-Konfiguration fällt
  auf den Standard zurück, statt still nur einen Teil auszuwerten.
"""
import base64
import json

from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from odoo.addons.kjr_event.wizard.kjr_event_statistics import (
    DEFAULT_AGE_BUCKETS, GENDER_BASIS, INCOME_HEADER, PARAM_AGE_BUCKETS,
)


@tagged('post_install', '-at_install')
class TestKjrEventStatistics(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Event = cls.env['event.event']
        cls.Registration = cls.env['event.registration']
        cls.Wizard = cls.env['kjr.event.statistics.wizard']
        cls.Param = cls.env['ir.config_parameter'].sudo()
        cls.product = cls.env['product.product'].create({
            'name': 'Schulung 50 Euro (Statistik-Test)',
            'list_price': 50.0,
            'type': 'service',
        })

    def setUp(self):
        super().setUp()
        # Jeder Test startet mit den ausgelieferten Standardklassen.
        self.Param.set_param(PARAM_AGE_BUCKETS, '')

    # ------------------------------------------------------------------
    # Hilfsmittel
    # ------------------------------------------------------------------
    def _event(self, name='Maßnahme', **kw):
        vals = {
            'name': name,
            'is_kjr': True,
            'date_begin': '2026-07-06 09:00:00',
            'date_end': '2026-07-10 17:00:00',
            'kjr_event_type': 'ferienprogramm',
        }
        vals.update(kw)
        if 'auto_confirm' in self.Event._fields:
            vals.setdefault('auto_confirm', False)
        return self.Event.create(vals)

    def _reg(self, event, state='open', **kw):
        vals = {'event_id': event.id, 'name': 'Teilnehmer', 'state': state}
        vals.update(kw)
        reg = self.Registration.create(vals)
        if reg.state != state:
            reg.write({'state': state})
        return reg

    def _wizard(self, group_by='event', events=None):
        wiz = self.Wizard.create({
            'date_from': '2026-01-01',
            'date_to': '2026-12-31',
            'group_by': group_by,
        })
        if events is not None:
            wiz.event_ids = [(6, 0, events.ids)]
        return wiz

    def _rows(self, wiz, events):
        """Kopf-, Detail- und Summenzeilen wie beim echten Export."""
        buckets = wiz._age_buckets()
        genders = wiz._gender_levels()
        data = wiz._collect_data(events, buckets, genders)
        return wiz._build_rows(events, data, buckets, genders), buckets, genders

    def _cell(self, header, row, label):
        """Wert einer Spalte über ihre Beschriftung (nie über einen festen Index)."""
        self.assertIn(label, header, 'Spalte "%s" fehlt im Kopf.' % label)
        return row[header.index(label)]

    # ------------------------------------------------------------------
    # E2a – PLZ des Veranstaltungsorts
    # ------------------------------------------------------------------
    def test_zip_column_shows_partner_zip(self):
        """Die PLZ des Veranstaltungsort-Kontakts steht in einer eigenen Spalte."""
        if 'address_id' not in self.Event._fields:
            self.skipTest('Diese Odoo-Edition kennt kein address_id an event.event.')
        address = self.env['res.partner'].create({'name': 'Jugendhaus', 'zip': '87000'})
        event = self._event(name='Mit PLZ', address_id=address.id)
        wiz = self._wizard(events=event)
        rows, _buckets, _genders = self._rows(wiz, event)
        self.assertEqual(self._cell(rows[0], rows[1], 'PLZ'), '87000')

    def test_zip_column_stays_empty_without_zip(self):
        """Ohne gepflegte PLZ bleibt die Spalte LEER, kein Platzhalter."""
        if 'address_id' not in self.Event._fields:
            self.skipTest('Diese Odoo-Edition kennt kein address_id an event.event.')
        address = self.env['res.partner'].create({'name': 'Ort ohne PLZ'})
        event = self._event(name='Ohne PLZ', address_id=address.id)
        wiz = self._wizard(events=event)
        rows, _b, _g = self._rows(wiz, event)
        self.assertEqual(self._cell(rows[0], rows[1], 'PLZ'), '',
                         'Die Datei geht an eine Behörde, ein erfundener Wert wäre falsch.')

    def test_zip_column_stays_empty_without_address(self):
        """Ganz ohne Veranstaltungsort bleibt die Spalte leer."""
        event = self._event(name='Ohne Ort')
        wiz = self._wizard(events=event)
        rows, _b, _g = self._rows(wiz, event)
        self.assertEqual(self._cell(rows[0], rows[1], 'PLZ'), '')

    # ------------------------------------------------------------------
    # E2b – Einnahmen
    # ------------------------------------------------------------------
    def test_income_counts_only_confirmed(self):
        """Einnahmen = Beitrag mal BESTÄTIGTE Anmeldungen (ohne Entwurf/Storno)."""
        event = self._event(name='Kostenpflichtig', payment_required=True,
                            training_product_id=self.product.id)
        self._reg(event, state='open')
        self._reg(event, state='draft')
        self._reg(event, state='cancel')
        wiz = self._wizard(events=event)
        rows, _b, _g = self._rows(wiz, event)
        self.assertEqual(self._cell(rows[0], rows[1], INCOME_HEADER), '50,00',
                         'Nur die bestätigte Anmeldung zählt in die Einnahmen.')

    def test_income_is_zero_without_payment_required(self):
        """Hinterlegtes Produkt ohne Zahlungspflicht: Einnahmen 0,00."""
        event = self._event(name='Kostenfrei mit Produkt', payment_required=False,
                            training_product_id=self.product.id)
        self._reg(event, state='open')
        wiz = self._wizard(events=event)
        rows, _b, _g = self._rows(wiz, event)
        self.assertEqual(self._cell(rows[0], rows[1], INCOME_HEADER), '0,00')

    def test_income_header_names_its_basis(self):
        """Zählmenge UND Rechenweg stehen in der Spaltenbeschriftung selbst."""
        self.assertIn('bestätigt', INCOME_HEADER)
        self.assertIn('teilgenommen', INCOME_HEADER)
        self.assertIn('Listenpreis', INCOME_HEADER)
        self.assertIn('Soll', INCOME_HEADER)
        self.assertNotIn('Einnahmen', INCOME_HEADER)

    def test_fee_and_income_never_contradict_each_other(self):
        """Beitrag und Beitragssumme derselben Zeile widersprechen sich nicht.

        Ohne Zahlungspflicht wird für die Maßnahme nichts fakturiert. Stünde
        dort weiterhin der Produktpreis, meldete dieselbe Zeile an die Behörde
        einen Beitrag von 50,00 und eine Summe von 0,00.
        """
        event = self._event(name='Kostenfrei mit Produkt', payment_required=False,
                            training_product_id=self.product.id)
        self._reg(event, state='open')
        wiz = self._wizard(events=event)
        rows, _b, _g = self._rows(wiz, event)
        header, row = rows[0], rows[1]
        self.assertEqual(self._cell(header, row, 'Teilnahmebeitrag (€)'), '0,00',
                         'Ohne Zahlungspflicht gibt es keinen Teilnahmebeitrag.')
        self.assertEqual(self._cell(header, row, INCOME_HEADER), '0,00')

    def test_fee_is_shown_when_payment_is_required(self):
        """Mit Zahlungspflicht steht der Listenpreis des Produkts im Beitrag."""
        event = self._event(name='Kostenpflichtig mit Produkt', payment_required=True,
                            training_product_id=self.product.id)
        wiz = self._wizard(events=event)
        rows, _b, _g = self._rows(wiz, event)
        self.assertEqual(self._cell(rows[0], rows[1], 'Teilnahmebeitrag (€)'), '50,00')

    def test_income_is_summed_over_events(self):
        """Die Summenzeile addiert die Einnahmen der einzelnen Maßnahmen."""
        first = self._event(name='Schulung A', payment_required=True,
                            training_product_id=self.product.id)
        second = self._event(name='Schulung B', payment_required=True,
                             training_product_id=self.product.id)
        self._reg(first, state='open')
        self._reg(second, state='open')
        self._reg(second, state='open')
        events = first | second
        wiz = self._wizard(events=events)
        rows, _b, _g = self._rows(wiz, events)
        self.assertEqual(self._cell(rows[0], rows[-1], INCOME_HEADER), '150,00')

    # ------------------------------------------------------------------
    # E2c – Merkmal Geschlecht
    # ------------------------------------------------------------------
    def test_gender_is_optional(self):
        """Eine Anmeldung ohne Angabe zum Geschlecht bleibt anlegbar."""
        event = self._event(name='Ohne Geschlecht')
        reg = self._reg(event)
        self.assertFalse(reg.kjr_gender, 'Das Feld hat bewusst keinen Vorbelegungswert.')

    def test_gender_columns_count_each_level(self):
        """Je Stufe eine Spalte plus "ohne Angabe"; Stornos zählen nirgends."""
        event = self._event(name='Geschlechtsverteilung')
        levels = self.Wizard._gender_levels()
        self.assertTrue(levels, 'Das Feld kjr_gender muss Stufen haben.')
        for key, _label in levels:
            self._reg(event, kjr_gender=key)
        self._reg(event)                      # ohne Angabe (Feld leer)
        self._reg(event, state='cancel', kjr_gender=levels[0][0])

        wiz = self._wizard(events=event)
        rows, _b, genders = self._rows(wiz, event)
        header, row = rows[0], rows[1]
        for _key, label in genders:
            self.assertEqual(
                self._cell(header, row, ('Geschlecht %s' % label) + GENDER_BASIS), 1,
                'Jede Stufe muss genau einmal gezählt werden.')
        self.assertEqual(
            self._cell(header, row, 'Geschlecht nicht erfasst' + GENDER_BASIS), 1)
        self.assertEqual(self._cell(header, row, 'Anmeldungen gesamt'), len(levels) + 2)
        self.assertEqual(self._cell(header, row, 'davon storniert'), 1)

    def test_gender_columns_name_their_counting_basis(self):
        """Jede Geschlechtsspalte nennt ihre Zählmenge in der Beschriftung.

        Die Nachbarspalte "Anmeldungen gesamt" zählt alle Status einschließlich
        Storno, die Geschlechtsspalten nur die nicht stornierten. Ohne den
        Zusatz summieren sich die Spalten in der Behördenmeldung sichtbar auf
        eine andere Zahl, und die Empfängerin muss die Differenz erraten.
        """
        levels = self.Wizard._gender_levels()
        for header in self.Wizard._gender_headers(levels):
            self.assertTrue(header.endswith(GENDER_BASIS),
                            'Spalte "%s" nennt ihre Zählmenge nicht.' % header)

    def test_empty_field_column_is_distinguishable(self):
        """Leeres Feld und bewusste Nicht-Angabe sind an der Beschriftung zu trennen.

        Die Stufe des Feldes heißt "keine Angabe" (bewusst nicht angegeben). Die
        Spalte für das leere Feld darf nicht "ohne Angabe" heißen: zwei
        Nachbarspalten, deren Bedeutung an einem einzigen Wort hängt, sind beim
        Übertragen in den Erhebungsbogen nicht auseinanderzuhalten.
        """
        headers = self.Wizard._gender_headers(self.Wizard._gender_levels())
        self.assertEqual(headers[-1], 'Geschlecht nicht erfasst' + GENDER_BASIS)
        self.assertNotIn('Geschlecht ohne Angabe' + GENDER_BASIS, headers)

    def test_gender_group_disappears_without_levels(self):
        """Ohne Stufenliste entfällt die GANZE Spaltengruppe, auch "nicht erfasst".

        Eine 0 in "nicht erfasst" wäre dort die Aussage "bei niemandem fehlt die
        Angabe", obwohl das Merkmal überhaupt nicht erhoben wird.
        """
        self.assertEqual(self.Wizard._gender_headers([]), [])
        self.assertEqual(
            self.Wizard._gender_values({'genders': {}, 'gender_none': 0}, []), [])

    def test_gender_columns_match_field_levels(self):
        """Spaltenzahl und Stufenzahl des Feldes dürfen nicht auseinanderlaufen."""
        levels = self.Wizard._gender_levels()
        headers = self.Wizard._gender_headers(levels)
        self.assertEqual(len(headers), len(levels) + 1,
                         'Je Stufe eine Spalte, dazu genau eine für "ohne Angabe".')
        field_levels = self.Registration._fields['kjr_gender'].selection
        self.assertEqual(len(levels), len(field_levels))

    def test_gender_survives_anonymization(self):
        """Das Aggregatmerkmal bleibt nach der DSGVO-Anonymisierung erhalten.

        Begründung siehe models/event_event.py: nach dem Leeren von Name,
        Geburtsdatum und Kontakt trägt die Stufe keinen Personenbezug mehr, wird
        aber für die Statistik vergangener Jahre weiter gebraucht.
        """
        event = self._event(name='Anonymisierung')
        reg = self._reg(event, kjr_gender='female', birthdate='2010-05-01')
        self.Event._kjr_anonymize_expired_registrations(reg)
        reg.invalidate_recordset()
        self.assertTrue(reg.kjr_data_anonymized)
        self.assertEqual(reg.kjr_gender, 'female',
                         'kjr_gender ist ein Aggregatmerkmal und wird nicht geleert.')

    # ------------------------------------------------------------------
    # E2d – Konfigurierbare Altersklassen
    # ------------------------------------------------------------------
    def test_default_buckets_without_parameter(self):
        """Ohne gepflegten Parameter gelten die sechs Standardklassen."""
        self.assertEqual(self.Wizard._age_buckets(), list(DEFAULT_AGE_BUCKETS))

    def test_shipped_parameter_equals_default(self):
        """Der ausgelieferte Parameterwert ergibt genau die Standardklassen.

        Sonst bekäme eine frische Installation stillschweigend eine andere
        Einteilung als eine, bei der der Parameter gelöscht wurde.
        """
        param = self.env.ref('kjr_event.param_statistics_age_buckets',
                             raise_if_not_found=False)
        if not param:
            self.skipTest('Systemparameter-Datensatz nicht geladen.')
        self.Param.set_param(PARAM_AGE_BUCKETS, param.value)
        self.assertEqual(self.Wizard._age_buckets(), list(DEFAULT_AGE_BUCKETS))

    def test_four_buckets_are_applied(self):
        """Eine gültige Vier-Klassen-Konfiguration wird übernommen."""
        self.Param.set_param(PARAM_AGE_BUCKETS, json.dumps([
            {'label': 'Alter unter 6', 'bis': 5},
            {'label': 'Alter 6 bis 13', 'von': 6, 'bis': 13},
            {'label': 'Alter 14 bis 17', 'von': 14, 'bis': 17},
            {'label': 'Alter 18 und älter', 'von': 18},
        ]))
        buckets = self.Wizard._age_buckets()
        self.assertEqual(len(buckets), 4)
        self.assertEqual([label for label, _lo, _hi in buckets],
                         ['Alter unter 6', 'Alter 6 bis 13',
                          'Alter 14 bis 17', 'Alter 18 und älter'])

    def test_four_buckets_classify_boundaries(self):
        """Die Einordnung trifft genau die neuen Grenzen (Grenzfälle)."""
        self.Param.set_param(PARAM_AGE_BUCKETS, json.dumps([
            {'bis': 5}, {'von': 6, 'bis': 13}, {'von': 14, 'bis': 17}, {'von': 18},
        ]))
        event = self._event(name='Grenzfälle')
        # Beginn 06.07.2026: Geburtstag am 06.07. liefert exakt das Zielalter.
        for year in (2021, 2020, 2013, 2012, 2009, 2008):
            self._reg(event, birthdate='%d-07-06' % year)
        wiz = self._wizard(events=event)
        rows, buckets, _g = self._rows(wiz, event)
        header, row = rows[0], rows[1]
        counts = [self._cell(header, row, label) for label, _lo, _hi in buckets]
        # Alter 5 und 6 | 6 und 13 | 14 und 17 | 18
        self.assertEqual(counts, [1, 2, 2, 1],
                         'Grenzjahrgänge müssen in der jeweils richtigen Klasse landen.')

    def test_unusable_configurations_fall_back(self):
        """Jede unbrauchbare Konfiguration fällt auf die sechs Standardklassen."""
        broken = {
            'kein JSON': '{kaputt',
            'leere Liste': '[]',
            'Lücke': json.dumps([{'bis': 5}, {'von': 7}]),
            'Überschneidung': json.dumps([{'bis': 10}, {'von': 10}]),
            'absteigend': json.dumps([{'von': 14, 'bis': 17}, {'von': 6, 'bis': 9}]),
            '"bis" fehlt in der Mitte': json.dumps([{'bis': 5}, {'von': 6}, {'von': 10}]),
            'unten nicht abgedeckt': json.dumps([{'von': 6, 'bis': 9}, {'von': 10}]),
            'oben nicht abgedeckt': json.dumps([{'bis': 5}, {'von': 6, 'bis': 26}]),
        }
        for label, value in broken.items():
            with self.subTest(konfiguration=label):
                self.Param.set_param(PARAM_AGE_BUCKETS, value)
                with self.assertLogs(
                        'odoo.addons.kjr_event.wizard.kjr_event_statistics',
                        level='WARNING') as logs:
                    buckets = self.Wizard._age_buckets()
                self.assertEqual(buckets, list(DEFAULT_AGE_BUCKETS))
                self.assertTrue(any('unbrauchbar' in line for line in logs.output),
                                'Der Rückfall muss im Protokoll sichtbar sein.')

    # ------------------------------------------------------------------
    # Spaltenzahlen (sonst verrutscht die CSV lautlos)
    # ------------------------------------------------------------------
    def _assert_column_counts(self):
        event = self._event(name='Spaltenprobe', payment_required=True,
                            training_product_id=self.product.id)
        self._reg(event, kjr_gender='male', birthdate='2012-03-01')
        self._reg(event)
        events = event

        wiz = self._wizard(group_by='event', events=events)
        rows, buckets, genders = self._rows(wiz, events)
        header = wiz._detail_header(buckets, genders)
        self.assertEqual(rows[0], header)
        for index, row in enumerate(rows[1:], start=1):
            self.assertEqual(
                len(row), len(header),
                'Detailzeile %d hat %d statt %d Spalten.' % (index, len(row), len(header)))

        for group_by in ('type', 'total'):
            wiz = self._wizard(group_by=group_by, events=events)
            rows, buckets, genders = self._rows(wiz, events)
            agg_header = rows[0]
            self.assertEqual(
                len(agg_header),
                len(wiz._aggregate_header(agg_header[0], buckets, genders)))
            for index, row in enumerate(rows[1:], start=1):
                self.assertEqual(
                    len(row), len(agg_header),
                    'Aggregatzeile %d (%s) hat %d statt %d Spalten.'
                    % (index, group_by, len(row), len(agg_header)))

    def test_column_counts_with_default_buckets(self):
        """Standardklassen: Kopf, Datenzeilen und Summenzeile sind gleich lang."""
        self._assert_column_counts()

    def test_column_counts_with_four_buckets(self):
        """Vier Klassen: Kopf, Datenzeilen und Summenzeile sind gleich lang."""
        self.Param.set_param(PARAM_AGE_BUCKETS, json.dumps([
            {'bis': 5}, {'von': 6, 'bis': 13}, {'von': 14, 'bis': 17}, {'von': 18},
        ]))
        self._assert_column_counts()

    # ------------------------------------------------------------------
    # Gesamtlauf
    # ------------------------------------------------------------------
    def test_action_generate_produces_a_file(self):
        """Der Assistent erzeugt eine CSV mit BOM und Semikolon."""
        event = self._event(name='Gesamtlauf', payment_required=True,
                            training_product_id=self.product.id)
        self._reg(event, kjr_gender='diverse')
        wiz = self._wizard(events=event)
        wiz.action_generate()
        self.assertTrue(wiz.export_file)
        content = base64.b64decode(wiz.export_file)
        self.assertTrue(content.startswith(b'\xef\xbb\xbf'),
                        'UTF-8-BOM fehlt, Excel würde die Umlaute zerlegen.')
        text = content.decode('utf-8-sig')
        lines = [line for line in text.split('\r\n') if line]
        self.assertEqual(len({line.count(';') for line in lines}), 1,
                         'Alle Zeilen müssen dieselbe Spaltenzahl haben.')
        self.assertIn('PLZ', lines[0])
        self.assertIn('Geschlecht', lines[0])
