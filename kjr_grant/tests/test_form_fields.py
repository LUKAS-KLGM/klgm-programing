# -*- coding: utf-8 -*-
"""
Tests für die am 30.07.2026 mit der KJR-Kassenleitung abgestimmten Formularfelder.

Abgesichert wird der Daten-/API-Vertrag hinter der überarbeiteten Teilnahmeliste
und der digitalen Belegliste:

* Teilnahmeliste: das Alter wird direkt erfasst (Geburtsdatum entfällt im
  Website-Formular) und darf durch die Neuberechnung nicht verloren gehen;
  die Kennziffer (EA/HA/HO/PR/SO) steuert das förderrelevante Kennzeichen
  „Gruppenleitung".
* Belegliste: Beträge werden immer positiv erfasst (Vorzeichen steckt in der
  Art), Position und Art müssen zusammenpassen, die Summen am Antrag stimmen.
* Altersfenster-Prüfung: greift jetzt auch bei Teilnehmenden ohne Geburtsdatum,
  solange ein Alter erfasst ist (Jugendleitung bleibt ausgenommen).

Erwartungswerte sind in den Docstrings hergeleitet.
"""
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import ValidationError


@tagged('post_install', '-at_install')
class TestKjrGrantFormFields(TransactionCase):

    # Textbaustein der Altersfenster-Warnung aus _post_compliance_warnings().
    AGE_WARNING = 'außerhalb des förderfähigen'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Application = cls.env['kjr.grant.application']
        cls.Participant = cls.env['kjr.grant.participant']
        cls.Receipt = cls.env['kjr.grant.receipt']
        # Antragsberechtigter Mitgliedsverband (§ 3.1: Vertretungsrecht in der VV).
        cls.assoc = cls.env['res.partner'].create({
            'name': 'Testverband e. V.',
            'is_company': True,
            'is_kjr_member': True,
            'kjr_vr_right': True,
        })

    # ── Hilfsmethoden ────────────────────────────────────────────────────────
    def _app(self, type_xmlid='kjr_grant.grant_type_4_1a', **kw):
        vals = {
            'partner_id': self.assoc.id,
            'grant_type_id': self.env.ref(type_xmlid).id,
            'measure_name': 'Sommerausflug Skylinepark',
            'measure_start': '2026-07-01',
            'measure_end': '2026-07-01',
            'measure_zip': '86871',
            'measure_location': 'Skylinepark, Rammingen',
        }
        vals.update(kw)
        return self.Application.create(vals)

    def _participant(self, app, **kw):
        vals = {'application_id': app.id, 'name': 'Testkind, Tanja'}
        vals.update(kw)
        return self.Participant.create(vals)

    def _receipt(self, app, **kw):
        vals = {
            'application_id': app.id,
            'date': '2026-07-01',
            'receipt_no': 'R-001',
            'partner_name': 'Skylinepark GmbH',
            'description': 'Eintritt Freizeitpark',
            'direction': 'expense',
            'category': 'accommodation',
            'amount': 120.0,
        }
        vals.update(kw)
        return self.Receipt.create(vals)

    def _compliance_note(self, app):
        """Die Förderfähigkeits-Hinweise werden als Chatter-Notiz gepostet statt
        zurückgegeben – für die Prüfung den Text der neu erzeugten Nachricht lesen."""
        known = set(app.message_ids.ids)
        app._post_compliance_warnings()
        new_messages = app.message_ids.filtered(lambda m: m.id not in known)
        return '\n'.join(str(m.body) for m in new_messages)

    # ══ Teilnahmeliste: Alter wird direkt erfasst ════════════════════════════
    def test_age_manual_entry_is_kept(self):
        """Ohne Geburtsdatum bleibt das im Formular eingegebene Alter stehen –
        die Berechnung darf es nicht auf 0 zurücksetzen."""
        app = self._app()
        p = self._participant(app, name='Lena Beispiel', age=14)
        self.assertEqual(p.age, 14)
        self.assertFalse(p.birthdate)

    def test_age_survives_recompute_without_birthdate(self):
        """Auslöser der Neuberechnung (Maßnahmenbeginn ändert sich) darf das
        manuell erfasste Alter nicht überschreiben, solange kein Geburtsdatum
        hinterlegt ist."""
        app = self._app()
        p = self._participant(app, name='Lena Beispiel', age=14)
        app.write({'measure_start': '2026-08-01', 'measure_end': '2026-08-01'})
        p.invalidate_recordset(['age'])
        self.assertEqual(p.age, 14)

    def test_age_computed_from_birthdate(self):
        """Mit Geburtsdatum zählt das Alter zum Maßnahmenbeginn (01.07.2026):
        geboren am 15.08.2010 → Geburtstag noch nicht gehabt → 15 Jahre."""
        app = self._app()
        p = self._participant(app, name='Tim Testkind', birthdate='2010-08-15')
        self.assertEqual(p.age, 15)

    def test_age_computed_from_birthdate_after_birthday(self):
        """Geboren am 15.06.2010, Maßnahmenbeginn 01.07.2026 → Geburtstag lag
        bereits vor Maßnahmenbeginn → 16 Jahre."""
        app = self._app()
        p = self._participant(app, name='Tim Testkind', birthdate='2010-06-15')
        self.assertEqual(p.age, 16)

    def test_birthdate_recomputes_previously_entered_age(self):
        """Wird nachträglich ein Geburtsdatum erfasst (Backend, abgetippter
        Papierantrag), gewinnt die Berechnung gegenüber dem Eingabewert:
        99 → 16 Jahre."""
        app = self._app()
        p = self._participant(app, name='Tim Testkind', age=99)
        p.birthdate = '2010-06-15'
        self.assertEqual(p.age, 16)

    # ══ Teilnahmeliste: Kennziffer steuert die Gruppenleitung ════════════════
    def test_role_code_sets_is_leader(self):
        """Kennziffer gesetzt ⇒ Gruppenleitung; Kennziffer geleert ⇒ Teilnehmer/in.
        is_leader trägt die Förderlogik (Betreuungsschlüssel 1:5, Altersfenster-
        Ausnahme) und wird per Onchange mitgeführt."""
        app = self._app()
        p = self._participant(app, name='Maxi Musterleiter')
        self.assertFalse(p.is_leader)
        p.role_code = 'EA'
        p._onchange_role_code()
        self.assertTrue(p.is_leader)
        p.role_code = False
        p._onchange_role_code()
        self.assertFalse(p.is_leader)

    def test_role_code_onchange_on_unsaved_record(self):
        """Onchange greift auch im noch nicht gespeicherten Formular (Webclient)."""
        p = self.Participant.new({'name': 'Neue Zeile', 'role_code': 'HA'})
        p._onchange_role_code()
        self.assertTrue(p.is_leader)

    def test_is_leader_stays_manually_editable(self):
        """is_leader ist bewusst KEIN berechnetes Feld: die Geschäftsstelle kann
        eine Gruppenleitung ohne Kennziffer erfassen (Papieranträge), ohne dass
        ein Compute den Wert wieder entfernt."""
        app = self._app()
        p = self._participant(app, name='Ohne Kennziffer', is_leader=True)
        self.assertFalse(p.role_code)
        p.write({'note': 'Betreuung Bus'})
        self.assertTrue(p.is_leader)

    def test_role_code_selection_options(self):
        """Kennziffern laut Teilnahmeliste des KJR Oberallgäu – Werte und
        Reihenfolge sind Vertragsbestandteil (Legende im Website-Formular)."""
        selection = self.Participant.fields_get(['role_code'])['role_code']['selection']
        self.assertEqual([value for value, _label in selection],
                         ['EA', 'HA', 'HO', 'PR', 'SO'])
        self.assertEqual([label for _value, label in selection], [
            'EA – ehrenamtliche/r Mitarbeiter/in',
            'HA – haupt-/nebenberufliche/r Mitarbeiter/in',
            'HO – Honorarkraft',
            'PR – Praktikant/in',
            'SO – sonstige',
        ])

    # ══ Teilnahmeliste: Geschlecht ═══════════════════════════════════════════
    def test_gender_selection_options(self):
        """Genau drei Ausprägungen (Statistik der Geschäftsstelle)."""
        selection = self.Participant.fields_get(['gender'])['gender']['selection']
        self.assertEqual([(value, label) for value, label in selection], [
            ('male', 'männlich'),
            ('female', 'weiblich'),
            ('diverse', 'divers'),
        ])

    def test_gender_accepts_all_valid_values(self):
        app = self._app()
        for code in ('male', 'female', 'diverse'):
            p = self._participant(app, name='TN %s' % code, gender=code)
            self.assertEqual(p.gender, code)

    def test_gender_rejects_unknown_value(self):
        """Freitext/Tippfehler aus dem Formular dürfen nicht durchrutschen."""
        app = self._app()
        with self.assertRaises(ValueError):
            self._participant(app, name='Falsch', gender='unbekannt')

    # ══ Belegliste: Betrag und Position/Art ══════════════════════════════════
    def test_receipt_valid_expense_row(self):
        """Regulärer Ausgabenbeleg mit passender Position."""
        app = self._app()
        r = self._receipt(app)
        self.assertEqual(r.amount, 120.0)
        self.assertEqual(r.direction, 'expense')

    def test_receipt_valid_income_row(self):
        """Regulärer Einnahmenbeleg (Teilnehmerbeiträge)."""
        app = self._app()
        r = self._receipt(app, direction='income', category='tn_fees',
                          partner_name='Familie Beispiel',
                          description='Teilnehmerbeitrag', amount=45.0)
        self.assertEqual(r.direction, 'income')
        self.assertEqual(r.amount, 45.0)

    def test_receipt_amount_must_be_positive(self):
        """Beträge werden immer positiv erfasst – das Vorzeichen steckt in „Art"."""
        app = self._app()
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._receipt(app, amount=0.0)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._receipt(app, amount=-10.0)

    def test_receipt_expense_rejects_income_category(self):
        """Art „Ausgabe" mit der Einnahme-Position „Teilnehmerbeiträge" würde die
        Belegsummen gegen die falsche Seite der Kostenaufstellung laufen lassen."""
        app = self._app()
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._receipt(app, direction='expense', category='tn_fees')

    def test_receipt_income_rejects_expense_category(self):
        """Gegenprobe: Art „Einnahme" mit einer Ausgaben-Position."""
        app = self._app()
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._receipt(app, direction='income', category='transport')

    def test_receipt_income_categories_constant(self):
        """Die Klassenkonstante ist die gemeinsame Zuordnung für Controller,
        Views und Folgemodule – sie muss zu den „Einnahme:"-Positionen passen."""
        self.assertEqual(
            self.Receipt.INCOME_CATEGORIES,
            ('tn_fees', 'municipality', 'association', 'bjr', 'income_other'),
        )
        selection = self.Receipt.fields_get(['category'])['category']['selection']
        income_by_label = tuple(
            value for value, label in selection if label.startswith('Einnahme:')
        )
        self.assertEqual(income_by_label, self.Receipt.INCOME_CATEGORIES)

    # ══ Belegliste: Summen am Antrag ═════════════════════════════════════════
    def test_receipt_totals_on_application(self):
        """3 Belege: Ausgaben 120,00 + 30,50 = 150,50 €, Einnahme 45,00 €,
        Anzahl 3. Die Summen sind die Gegenprobe zur Kostenaufstellung."""
        app = self._app(use_digital_receipts=True)
        self._receipt(app)
        self._receipt(app, receipt_no='R-002', category='transport',
                      partner_name='Busreisen Allgäu',
                      description='Busfahrt', amount=30.5)
        self._receipt(app, receipt_no='R-003', direction='income',
                      category='tn_fees', partner_name='Familie Beispiel',
                      description='Teilnehmerbeiträge', amount=45.0)
        app.invalidate_recordset(
            ['receipt_count', 'receipt_income_total', 'receipt_expense_total'])
        self.assertEqual(app.receipt_count, 3)
        self.assertEqual(app.receipt_expense_total, 150.5)
        self.assertEqual(app.receipt_income_total, 45.0)

    def test_receipt_totals_without_receipts(self):
        """Ohne Belege sind Anzahl und Summen 0 (kein Fehler bei Papier-Belegliste)."""
        app = self._app()
        self.assertEqual(app.receipt_count, 0)
        self.assertEqual(app.receipt_expense_total, 0.0)
        self.assertEqual(app.receipt_income_total, 0.0)

    # ══ Altersfenster (§ 4.1: 5–27 Jahre) ════════════════════════════════════
    def test_age_range_checked_without_birthdate(self):
        """BUGFIX: geprüft wird das Feld „Alter", nicht mehr das Geburtsdatum.
        Ein/e 32-Jährige/r ohne Geburtsdatum liegt außerhalb von 5–27 Jahren."""
        app = self._app(tn_count=2, cost_accommodation=200.0)
        self._participant(app, name='Erwin Erwachsen', age=32)
        text = self._compliance_note(app)
        self.assertIn(self.AGE_WARNING, text)
        self.assertIn('1 Teilnehmer (ohne Gruppenleitungen)', text)

    def test_age_range_below_minimum(self):
        """Unterschreitung ebenfalls: 3 Jahre < Mindestalter 5."""
        app = self._app(tn_count=1, cost_accommodation=200.0)
        self._participant(app, name='Kleiner Krümel', age=3)
        self.assertIn(self.AGE_WARNING, self._compliance_note(app))

    def test_age_range_within_limits_no_warning(self):
        """14 Jahre liegt im Fenster 5–27 → kein Hinweis."""
        app = self._app(tn_count=1, cost_accommodation=200.0)
        self._participant(app, name='Lena Beispiel', age=14)
        self.assertNotIn(self.AGE_WARNING, self._compliance_note(app))

    def test_age_range_leader_exempt(self):
        """Für die Gruppenleitung besteht keine Altersgrenze (KJR-OA) – eine
        32-jährige Leitung löst keinen Hinweis aus."""
        app = self._app(tn_count=1, cost_accommodation=200.0)
        self._participant(app, name='Maxi Musterleiter', age=32, is_leader=True)
        self.assertNotIn(self.AGE_WARNING, self._compliance_note(app))

    def test_age_range_leader_via_role_code_exempt(self):
        """Gleiches Ergebnis über die Kennziffer: EA setzt per Onchange die
        Gruppenleitung, die damit von der Altersgrenze ausgenommen ist."""
        app = self._app(tn_count=1, cost_accommodation=200.0)
        p = self._participant(app, name='Maxi Musterleiter', age=32)
        p.role_code = 'EA'
        p._onchange_role_code()
        self.assertTrue(p.is_leader)
        self.assertNotIn(self.AGE_WARNING, self._compliance_note(app))

    def test_age_range_counts_only_participants_out_of_range(self):
        """Gemischte Liste: 14 (ok), 32 (außerhalb), 35 als Leitung (ausgenommen)
        → genau 1 beanstandeter Teilnehmer."""
        app = self._app(tn_count=2, cost_accommodation=200.0)
        self._participant(app, name='Lena Beispiel', age=14)
        self._participant(app, name='Erwin Erwachsen', age=32)
        self._participant(app, name='Maxi Musterleiter', age=35, is_leader=True)
        text = self._compliance_note(app)
        self.assertIn('1 Teilnehmer (ohne Gruppenleitungen)', text)

    def test_age_range_skips_participants_without_age(self):
        """Wer weder Alter noch Geburtsdatum hat (unvollständiger Papierantrag),
        wird übersprungen statt als 0-Jähriger beanstandet."""
        app = self._app(tn_count=1, cost_accommodation=200.0)
        self._participant(app, name='Ohne Angabe')
        self.assertNotIn(self.AGE_WARNING, self._compliance_note(app))
