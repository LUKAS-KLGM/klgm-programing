# -*- coding: utf-8 -*-
"""Tests zu Paket A der Kundenbesprechung (19.0.17.0.0).

Abgedeckt:
* B01/B06  Beispiele im Formular: „Ausflug Skyline Park", PLZ 86871, Ort Rammingen.
* B15      Gesamteinnahmen, Gesamtkosten und Fehlbetrag live im Formular; die
           Berechnung im Modell bleibt unverändert.
* B20      Alter je teilnehmender Person Pflicht, auch in angehängten Zeilen,
           Prüfung im Controller mit verständlicher Meldung.
* B31      Vorlage für Kostenaufstellung UND Belegliste, druckbar und als Excel.
* B33      Abgleich Belegsummen ⇄ Kostenaufstellung (Backend, Chatter, Formular).
* B34      Position je Beleg optional.
* B40      Hinweis zur Herkunft der Fördermittel an Checkbox 3 (einstellbar).
* B43      Link auf die Zuschussrichtlinien in Checkbox 2 (einstellbar), ohne
           gepflegte Adresse auf den Abschnitt „Zuschussrichtlinien" der
           Hilfeseite; Migration trägt das öffentliche Richtlinien-PDF ein.
* Texte    Zuschuss höchstens Fehlbetrag (nicht „bemisst sich am Fehlbetrag“).
* A11y     aria-label auch in den per JavaScript angehängten Zeilen; Belegabgleich
           über eine dauerhafte Live-Region statt über eingeblendete Boxen.
"""
import base64
import io
import zipfile

from odoo import http
from odoo.modules.module import get_manifest
from odoo.tests import tagged
from odoo.tests.common import HttpCase, TransactionCase, new_test_user
from odoo.tools.misc import file_open

from odoo.addons.http_routing.tests.common import MockRequest
from odoo.addons.kjr_grant.controllers.website import KjrWebsiteController
from odoo.addons.kjr_grant.models.res_config_settings_apply import (
    DEFAULT_FUNDING_NOTICE,
    DEFAULT_GUIDELINES_URL,
    PARAM_FUNDING_NOTICE,
    PARAM_GUIDELINES_URL,
    PARAM_HIDE_FUNDING_NOTICE,
    find_guidelines_attachment_url,
    get_apply_form_settings,
)

NBSP_EUR = ' €'


@tagged('post_install', '-at_install')
class TestKjrApplyFormFeedback(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Application = cls.env['kjr.grant.application']
        cls.Receipt = cls.env['kjr.grant.receipt']
        cls.assoc = cls.env['res.partner'].create({
            'name': 'Testverband Paket A e. V.',
            'is_company': True,
            'is_kjr_member': True,
            'kjr_vr_right': True,
        })
        cls.website = cls.env.ref('website.default_website')
        cls.controller = KjrWebsiteController()

    def _app(self, **kw):
        vals = {
            'partner_id': self.assoc.id,
            'grant_type_id': self.env.ref('kjr_grant.grant_type_4_1a').id,
            'measure_name': 'Ausflug Skyline Park',
            'measure_start': '2026-07-01',
            'measure_end': '2026-07-01',
            'measure_zip': '86871',
            'measure_location': 'Rammingen',
        }
        vals.update(kw)
        return self.Application.create(vals)

    def _receipt(self, app, **kw):
        vals = {
            'application_id': app.id,
            'date': '2026-07-01',
            'partner_name': 'Freizeitpark GmbH',
            'description': 'Eintritt',
            'direction': 'expense',
            'amount': 100.0,
        }
        vals.update(kw)
        return self.Receipt.create(vals)

    def _arch(self):
        return self.env.ref('kjr_grant.website_kjr_apply').arch

    # ══ B01/B06: Beispiele ════════════════════════════════════════════════
    def test_placeholders_use_skyline_park(self):
        """Kundenwunsch (Besprechung 00:01:55, 00:05:25): konkretes Beispiel mit Ziel und ein
        Ort mit PLZ statt eines Platznamens."""
        arch = self._arch()
        self.assertIn('placeholder="z. B. Ausflug Skyline Park"', arch)
        self.assertIn('placeholder="z. B. 86871"', arch)
        self.assertIn('placeholder="z. B. Rammingen"', arch)
        self.assertNotIn('Jugendzeltplatz', arch)
        self.assertNotIn('Sommerfreizeit der Jungschar', arch)

    # ══ B15: Summen und Fehlbetrag ════════════════════════════════════════
    def test_deficit_model_unchanged(self):
        """Fehlbetrag = Kosten minus Einnahmen, nicht unter 0 (unverändert)."""
        app = self._app(cost_accommodation=250.0, cost_transport=50.0, income_tn_fees=120.0)
        self.assertEqual(app.cost_total, 300.0)
        self.assertEqual(app.income_total, 120.0)
        self.assertEqual(app.deficit, 180.0)
        app.income_municipality = 500.0
        self.assertEqual(app.deficit, 0.0)

    def test_form_totals_first_render(self):
        """Erste Anzeige im Formular: gleiche Formel, deutsche Schreibweise,
        Komma-Beträge werden verstanden, negative Eingaben zählen nicht."""
        totals = KjrWebsiteController._form_totals({
            'income_tn_fees': '100,50', 'income_bjr': '-20',
            'cost_accommodation': '1000', 'cost_other': '234.5',
        })
        self.assertAlmostEqual(totals['income'], 100.5)
        self.assertAlmostEqual(totals['cost'], 1234.5)
        self.assertAlmostEqual(totals['deficit'], 1134.0)
        self.assertEqual(totals['cost_label'], '1.234,50' + NBSP_EUR)
        self.assertEqual(totals['deficit_label'], '1.134,00' + NBSP_EUR)
        self.assertEqual(KjrWebsiteController._form_totals({})['deficit_label'], '0,00' + NBSP_EUR)

    def test_live_totals_wired_in_form(self):
        """Formular trägt die Haken für die Interaction, die Interaction ist im
        Frontend-Bundle registriert."""
        arch = self._arch()
        self.assertIn('o_kjr_apply_form', arch)
        self.assertIn('data-kjr-sum="income"', arch)
        self.assertIn('data-kjr-sum="cost"', arch)
        for key in ('income', 'cost', 'deficit'):
            self.assertIn('data-kjr-total="%s"' % key, arch)
        self.assertIn('Fehlbetrag (Defizit)', arch)
        assets = get_manifest('kjr_grant')['assets']['web.assets_frontend']
        self.assertIn('kjr_grant/static/src/interactions/kjr_apply_totals.js', assets)

    # ══ B20: Alter je Person Pflicht ══════════════════════════════════════
    def test_participant_rows_read_across_gaps(self):
        """Zeile 3 hinter einer fehlenden Zeile 2 geht nicht mehr verloren."""
        rows = KjrWebsiteController._participant_form_rows({
            'tn_name_1': 'Anna A', 'tn_age_1': '12',
            'tn_name_3': 'Carl C', 'tn_age_3': '13',
        })
        self.assertEqual([r['name'] for r in rows], ['Anna A', 'Carl C'])

    def test_participant_age_required_per_row(self):
        """Jede ausgefüllte Zeile braucht Name und Alter (0 bis 120, ganze Zahl).
        Leere Zeilen werden übergangen."""
        post = {
            'tn_name_1': 'Anna A', 'tn_age_1': '12',
            'tn_name_2': 'Ben B', 'tn_age_2': '',
            'tn_name_3': 'Carl C', 'tn_age_3': '13,5',
            'tn_name_4': '', 'tn_age_4': '',
            'tn_name_5': '', 'tn_age_5': '9',
            'tn_name_6': 'Dora D', 'tn_age_6': '121',
        }
        errors = {}
        with MockRequest(self.env, website=self.website):
            KjrWebsiteController._check_participant_rows(post, errors)
        text = errors.get('participants', '')
        # Nummern wie im erneut angezeigten Formular: die leere Zeile 4 fällt
        # weg, aus 5 und 6 werden 4 und 5.
        self.assertIn('Zeile 2 (Ben B): Alter fehlt', text)
        self.assertIn('Zeile 3 (Carl C): Alter muss eine ganze Zahl', text)
        self.assertIn('Zeile 4: Name fehlt', text)
        self.assertIn('Zeile 5 (Dora D)', text)
        self.assertNotIn('Zeile 1', text)
        self.assertNotIn('Zeile 6', text)

    def test_participant_rows_complete_or_empty_pass(self):
        errors = {}
        with MockRequest(self.env, website=self.website):
            KjrWebsiteController._check_participant_rows(
                {'tn_name_1': 'Anna A', 'tn_age_1': '0', 'tn_name_2': '', 'tn_age_2': ''}, errors)
            KjrWebsiteController._check_participant_rows({}, errors)
        self.assertFalse(errors)

    def test_added_rows_mark_age_required(self):
        """Auch die per JavaScript angehängten Zeilen kennzeichnen Alter (und Name)
        als Pflicht."""
        arch = self._arch()
        self.assertIn('''name="tn_age_' + nr + '"''', arch)
        self.assertIn('required="required" aria-label="Alter in Jahren"', arch)
        self.assertIn('required="required" aria-label="Name, Vorname"', arch)

    def test_added_rows_have_aria_labels(self):
        """Die per JavaScript angehängten Teilnehmer- und Belegzeilen tragen
        dieselben aria-label wie die gerenderten Zeilen."""
        arch = self._arch()
        expected = [
            ('tn_gender_', 'Geschlecht'), ('tn_zip_', 'PLZ'), ('tn_city_', 'Wohnort'),
            ('tn_role_', 'Kennziffer'), ('tn_juleica_', 'Juleica'),
            ('rc_date_', 'Datum'), ('rc_no_', 'Beleg-Nr.'),
            ('rc_partner_', 'Empfänger / Einzahler'), ('rc_desc_', 'Bezeichnung'),
            ('rc_direction_', 'Art'), ('rc_category_', 'Position (optional)'),
            ('rc_amount_', 'Betrag in Euro'),
        ]
        for prefix, label in expected:
            start = arch.find('''name="%s' + nr + '"''' % prefix)
            self.assertGreater(start, -1, prefix)
            # Ende des Elements: ">" bzw. "&gt;" im Skripttext.
            end = min(i for i in (arch.find('&gt;', start), arch.find('>', start)) if i > -1)
            self.assertIn('aria-label="%s"' % label, arch[start:end], prefix)
            # Dasselbe Label in der gerenderten Zeile (QWeb, t-attf-name).
            start = arch.find('t-attf-name="%s{{' % prefix)
            self.assertGreater(start, -1, prefix)
            self.assertIn('aria-label="%s"' % label, arch[start:arch.find('>', start)], prefix)

    # ══ Texte zum Fehlbetrag ══════════════════════════════════════════════
    def test_deficit_text_not_misleading(self):
        """Der Zuschuss richtet sich nach der Förderart; der Fehlbetrag ist nur
        die Obergrenze (§ 4.7, § 4.9 und Investitionszuschuss ausgenommen)."""
        for xmlid in ('kjr_grant.website_kjr_apply', 'kjr_grant.website_kjr_belegliste_vorlage',
                      'kjr_grant.website_kjr_apply_help'):
            arch = self.env.ref(xmlid).arch
            self.assertNotIn('bemisst sich', arch, xmlid)
        self.assertIn('höchstens so hoch', self._arch())
        content = KjrWebsiteController._build_template_xlsx(self.env)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            strings = archive.read('xl/sharedStrings.xml').decode()
        self.assertNotIn('bemisst sich', strings)
        self.assertIn('höchstens so hoch wie der Fehlbetrag', strings)

    # ══ B31: Vorlagen ═════════════════════════════════════════════════════
    def test_xlsx_template_has_both_sheets(self):
        content = KjrWebsiteController._build_template_xlsx(self.env)
        self.assertTrue(content.startswith(b'PK'))
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            workbook = archive.read('xl/workbook.xml').decode()
            self.assertIn('name="Kostenaufstellung"', workbook)
            self.assertIn('name="Belegliste"', workbook)
            sheets = ''.join(
                archive.read(name).decode() for name in archive.namelist()
                if name.startswith('xl/worksheets/sheet'))
            strings = archive.read('xl/sharedStrings.xml').decode()
        # Fehlbetrag und Belegsummen als Formeln
        self.assertIn('MAX(', sheets)
        self.assertIn('SUMIF(', sheets)
        self.assertIn('Fehlbetrag', strings)
        self.assertIn('Position (optional)', strings)
        self.assertIn(self.env.company.name, strings)

    def test_print_template_has_cost_statement(self):
        arch = self.env.ref('kjr_grant.website_kjr_belegliste_vorlage').arch
        self.assertIn('Kostenaufstellung zum Zuschussantrag', arch)
        self.assertIn('Belegliste zum Zuschussantrag', arch)
        self.assertIn('/service/zuschuss/vorlage-kostenaufstellung-belegliste.xlsx', arch)

    # ══ B33: Abgleich ═════════════════════════════════════════════════════
    def test_receipt_check_matches(self):
        app = self._app(use_digital_receipts=True, cost_accommodation=100.0, income_tn_fees=40.0)
        self._receipt(app, category='accommodation')
        self._receipt(app, direction='income', category='tn_fees', amount=40.0)
        self.assertFalse(app.receipt_mismatch)
        self.assertEqual(app.receipt_income_diff, 0.0)
        self.assertEqual(app.receipt_expense_diff, 0.0)
        self.assertIn('stimmen überein', app.receipt_check_info)

    def test_receipt_check_total_difference(self):
        """Belege 100 € Ausgaben gegen 150 € Kosten: Abweichung -50 €."""
        app = self._app(use_digital_receipts=True, cost_accommodation=150.0)
        self._receipt(app)
        self.assertTrue(app.receipt_mismatch)
        self.assertEqual(app.receipt_expense_diff, -50.0)
        self.assertIn('Ausgaben: Belege 100,00 €, Kostenaufstellung 150,00 €', app.receipt_check_info)

    def test_receipt_check_per_position(self):
        """Summen stimmen, aber die Belege liegen auf einer anderen Position."""
        app = self._app(use_digital_receipts=True, cost_accommodation=100.0)
        self._receipt(app, category='transport')
        self.assertEqual(app.receipt_expense_diff, 0.0)
        self.assertTrue(app.receipt_mismatch)
        self.assertIn('Fahrtkosten', app.receipt_check_info)

    def test_receipt_check_without_positions(self):
        """Belege ohne Position: nur der Gesamtabgleich, kein Positionsabgleich."""
        app = self._app(use_digital_receipts=True, cost_accommodation=100.0)
        self._receipt(app)
        self.assertFalse(app.receipt_mismatch)
        self.assertIn('ohne Position', app.receipt_check_info)

    def test_receipt_check_only_for_digital_list(self):
        app = self._app(cost_accommodation=150.0)
        self._receipt(app)
        self.assertFalse(app.receipt_mismatch)
        self.assertFalse(app.receipt_check_info)

    def test_receipt_mismatch_in_compliance_note(self):
        app = self._app(use_digital_receipts=True, tn_count=10, cost_accommodation=150.0)
        self._receipt(app)
        known = set(app.message_ids.ids)
        app._post_compliance_warnings()
        body = '\n'.join(str(m.body) for m in app.message_ids if m.id not in known)
        self.assertIn('stimmt nicht mit der Kostenaufstellung', body)

    # ══ B34: Position optional im Formular ════════════════════════════════
    def test_parse_receipts_category_optional(self):
        post = {
            'rc_date_1': '2026-07-01', 'rc_partner_1': 'Eltern', 'rc_desc_1': 'Beitrag',
            'rc_direction_1': 'income', 'rc_category_1': '', 'rc_amount_1': '45,00',
            # Position gewinnt über die Art
            'rc_date_2': '2026-07-01', 'rc_partner_2': 'Familie B', 'rc_desc_2': 'Beitrag',
            'rc_direction_2': 'expense', 'rc_category_2': 'tn_fees', 'rc_amount_2': '10',
            # unbekannte Position wird verworfen, die Art bleibt
            'rc_date_4': '2026-07-02', 'rc_partner_4': 'Bus GmbH', 'rc_desc_4': 'Fahrt',
            'rc_direction_4': 'expense', 'rc_category_4': 'xyz', 'rc_amount_4': '80',
            # ohne Art und ohne Position: unvollständig
            'rc_date_5': '2026-07-02', 'rc_partner_5': 'X', 'rc_desc_5': 'Y',
            'rc_direction_5': '', 'rc_category_5': '', 'rc_amount_5': '5',
        }
        with MockRequest(self.env, website=self.website):
            rows = self.controller._parse_receipt_rows(post)
        self.assertEqual(
            [(r['direction'], r['category'], r['amount']) for r in rows],
            [('income', False, 45.0), ('income', 'tn_fees', 10.0), ('expense', False, 80.0)],
        )

    def test_live_receipt_check_follows_position(self):
        """Live-Abgleich zählt einen Beleg wie der Controller: Eine gewählte
        Position bestimmt die Art, nur ohne Position zählt das Feld „Art".
        Die Einnahme-Positionen kommen vom Server, und eine Art, die nicht zur
        Position passt, leert die Position."""
        with MockRequest(self.env, website=self.website):
            self.assertEqual(
                KjrWebsiteController._receipt_income_categories(),
                self.Receipt.INCOME_CATEGORIES,
            )
        arch = self._arch()
        self.assertIn('t-att-data-kjr-income-categories', arch)
        self.assertIn('function syncReceiptCategory(sel)', arch)
        # Server- und JS-Zeile: die Art ruft syncReceiptCategory auf.
        self.assertIn(
            '''t-attf-name="rc_direction_{{ rc['nr'] }}" class="form-select form-select-sm" '''
            '''onchange="syncReceiptCategory(this)"''', arch)
        self.assertIn(
            '''name="rc_direction_' + nr + '" class="form-select form-select-sm" '''
            '''onchange="syncReceiptCategory(this)"''', arch)
        with file_open('kjr_grant/static/src/interactions/kjr_apply_totals.js') as handle:
            source = handle.read()
        self.assertIn("select[name^='rc_category_']", source)
        self.assertIn('kjrIncomeCategories', source)

    def test_receipt_check_live_region(self):
        """Barrierefreiheit: Die Hinweisboxen (anfangs d-none) sind keine
        Live-Regionen; eine dauerhafte, leere Live-Region außerhalb von
        #rc_wrapper übernimmt die Ansage."""
        arch = self._arch()
        for state in ('mismatch', 'match'):
            start = arch.find('data-kjr-receipt-check="%s"' % state)
            self.assertGreater(start, -1, state)
            tag_start = arch.rfind('<div', 0, start)
            self.assertNotIn('role=', arch[tag_start:arch.find('>', start)], state)
        live = arch.find('data-kjr-receipt-check-live=""')
        self.assertGreater(live, -1)
        tag = arch[arch.rfind('<div', 0, live):arch.find('>', live) + 1]
        self.assertIn('role="status"', tag)
        self.assertIn('aria-atomic="true"', tag)
        self.assertNotIn('d-none', tag)
        # Außerhalb des ausblendbaren Belegblocks: hinter dem schließenden
        # </div> von #rc_wrapper, also hinter der letzten Hinweisbox.
        self.assertGreater(live, arch.find('data-kjr-receipt-check="match"'))
        with file_open('kjr_grant/static/src/interactions/kjr_apply_totals.js') as handle:
            source = handle.read()
        self.assertIn('[data-kjr-receipt-check-live]', source)
        self.assertIn('this.debounced(', source)

    # ══ B40/B43: Einstellungen ════════════════════════════════════════════
    def test_apply_settings_defaults(self):
        Param = self.env['ir.config_parameter'].sudo()
        for key in (PARAM_FUNDING_NOTICE, PARAM_GUIDELINES_URL, PARAM_HIDE_FUNDING_NOTICE):
            Param.set_param(key, False)
        settings = get_apply_form_settings(self.env)
        self.assertEqual(settings['funding_notice'], DEFAULT_FUNDING_NOTICE)
        self.assertIn('Landkreis Oberallgäu', settings['funding_notice'])
        self.assertEqual(settings['guidelines_url'], DEFAULT_GUIDELINES_URL)
        self.assertEqual(DEFAULT_GUIDELINES_URL, '/service/zuschuss-hilfe#zuschussrichtlinien')
        # Keine eigene Adresse: die Hilfeseite zeigt den Hinweis statt eines Links.
        self.assertEqual(settings['guidelines_document_url'], '')
        # Speichert die Einstellungsmaske die Vorgabe (oder die alte Vorgabe ohne
        # Anker), gilt das ebenfalls als „nicht gepflegt".
        for value in (DEFAULT_GUIDELINES_URL, '/service/zuschuss-hilfe'):
            Param.set_param(PARAM_GUIDELINES_URL, value)
            self.assertEqual(get_apply_form_settings(self.env)['guidelines_document_url'], '')

    def test_apply_settings_custom_and_hidden(self):
        Param = self.env['ir.config_parameter'].sudo()
        Param.set_param(PARAM_FUNDING_NOTICE, 'Die Mittel stellt die Stadt Musterstadt.')
        Param.set_param(PARAM_GUIDELINES_URL, 'https://example.org/richtlinien.pdf')
        settings = get_apply_form_settings(self.env)
        self.assertEqual(settings['funding_notice'], 'Die Mittel stellt die Stadt Musterstadt.')
        self.assertEqual(settings['guidelines_url'], 'https://example.org/richtlinien.pdf')
        self.assertEqual(settings['guidelines_document_url'], 'https://example.org/richtlinien.pdf')
        Param.set_param(PARAM_HIDE_FUNDING_NOTICE, 'True')
        self.assertEqual(get_apply_form_settings(self.env)['funding_notice'], '')

    def test_guidelines_url_rejects_script_links(self):
        Param = self.env['ir.config_parameter'].sudo()
        for bad in ('javascript:alert(1)', '//evil.example', 'data:text/html,x'):
            Param.set_param(PARAM_GUIDELINES_URL, bad)
            self.assertEqual(get_apply_form_settings(self.env)['guidelines_url'],
                             DEFAULT_GUIDELINES_URL, bad)
        Param.set_param(PARAM_GUIDELINES_URL, '/web/content/42?download=true')
        self.assertEqual(get_apply_form_settings(self.env)['guidelines_url'],
                         '/web/content/42?download=true')

    def _pdf_attachment(self, name, public=True):
        return self.env['ir.attachment'].create({
            'name': name,
            'datas': base64.b64encode(b'%PDF-1.4\n%%EOF\n'),
            'mimetype': 'application/pdf',
            'public': public,
        })

    def test_find_guidelines_attachment(self):
        """Öffentliches Richtlinien-PDF mit der höchsten Jahreszahl; nicht
        öffentliche Anhänge zählen nicht."""
        old = self._pdf_attachment('2097-2096-12-01_zuschussrichtlinien_test.pdf')
        new = self._pdf_attachment('2098_Zuschussrichtlinien-Test.pdf')
        self._pdf_attachment('2099_Zuschussrichtlinien-Entwurf.pdf', public=False)
        url = find_guidelines_attachment_url(self.env)
        self.assertEqual(url, '/web/content/%s/2098_Zuschussrichtlinien-Test.pdf' % new.id)
        self.assertNotEqual(url, '/web/content/%s/%s' % (old.id, old.name))

    def test_settings_fields_roundtrip(self):
        """Einstellungsmaske schreibt und liest dieselben Parameter."""
        settings = self.env['res.config.settings'].create({
            'kjr_grant_guidelines_url': '/richtlinien',
            'kjr_grant_funding_notice': 'Mittel vom Bezirk.',
            'kjr_grant_hide_funding_notice': False,
        })
        settings.execute()
        result = get_apply_form_settings(self.env)
        self.assertEqual(result['guidelines_url'], '/richtlinien')
        self.assertEqual(result['funding_notice'], 'Mittel vom Bezirk.')


@tagged('post_install', '-at_install')
class TestKjrApplyFormHttp(HttpCase):
    """Antragsformular über HTTP: Anzeige, Fehlerpfad Alter, Speichern."""

    LOGIN = 'kjr_antrag_portal'

    def setUp(self):
        super().setUp()
        self.assoc = self.env['res.partner'].create({
            'name': 'Jugendverband Paket A e. V.',
            'is_company': True,
            'is_kjr_member': True,
            'kjr_vr_right': True,
        })
        self.user = new_test_user(self.env, login=self.LOGIN, groups='base.group_portal')
        self.user.partner_id.parent_id = self.assoc
        self.authenticate(self.LOGIN, self.LOGIN)
        self.csrf_token = http.Request.csrf_token(self)

    def _payload(self, **extra):
        payload = {
            'csrf_token': self.csrf_token,
            'partner_id': str(self.assoc.id),
            'grant_type_id': str(self.env.ref('kjr_grant.grant_type_4_1a').id),
            'measure_name': 'Ausflug Skyline Park',
            'measure_start': '2026-07-01', 'measure_start_time': '08:00',
            'measure_end': '2026-07-01', 'measure_end_time': '18:00',
            'measure_zip': '86871', 'measure_location': 'Rammingen',
            'tn_count': '2', 'tn_leader_count': '1',
            'contact_person': 'Petra Prüfer', 'contact_email': 'petra@example.com',
            'contact_phone': '0831 12345',
            'payment_iban': 'DE89370400440532013000', 'payment_account_holder': 'Jugendverband',
            'confirm_privacy': '1', 'confirm_guidelines': '1', 'confirm_truthful': '1',
            'cost_accommodation': '100', 'income_tn_fees': '40',
            'use_digital_receipts': '1',
            'rc_date_1': '2026-07-01', 'rc_partner_1': 'Skyline Park', 'rc_desc_1': 'Eintritt',
            'rc_direction_1': 'expense', 'rc_category_1': '', 'rc_amount_1': '100',
            'tn_name_1': 'Anna Beispiel', 'tn_age_1': '14',
        }
        payload.update(extra)
        return payload

    def _apps(self):
        return self.env['kjr.grant.application'].search([('partner_id', '=', self.assoc.id)])

    def test_form_shows_examples_link_and_notice(self):
        self.env['ir.config_parameter'].sudo().set_param(PARAM_GUIDELINES_URL, False)
        text = self.url_open('/service/antrag-stellen').text
        self.assertIn('z. B. Ausflug Skyline Park', text)
        # Attributreihenfolge legt QWeb fest, deshalb per Muster.
        self.assertRegex(
            text,
            r'<a[^>]*href="/service/zuschuss-hilfe#zuschussrichtlinien"[^>]*>Zuschussrichtlinien</a>')
        self.assertIn('höchstens so hoch', text)
        self.assertIn('Die Mittel für die Förderung der Jugendarbeit stellt der Landkreis Oberallgäu.', text)
        self.assertIn('Fehlbetrag (Defizit)', text)
        self.assertIn('vorlage-kostenaufstellung-belegliste.xlsx', text)
        # B33: Einnahme-Positionen für den Live-Abgleich kommen vom Server.
        self.assertIn('data-kjr-income-categories="tn_fees municipality association bjr income_other"', text)

    def test_help_page_guidelines_section(self):
        """Ziel des Links: Abschnitt „Zuschussrichtlinien" der Hilfeseite. Ohne
        gepflegte Adresse Hinweis auf die Geschäftsstelle, mit Adresse der Link."""
        Param = self.env['ir.config_parameter'].sudo()
        Param.set_param(PARAM_GUIDELINES_URL, False)
        text = self.url_open('/service/zuschuss-hilfe').text
        self.assertIn('id="zuschussrichtlinien"', text)
        self.assertIn('sendet Ihnen', text)
        self.assertNotIn('Zuschussrichtlinien öffnen', text)
        Param.set_param(PARAM_GUIDELINES_URL, '/web/content/42/richtlinien.pdf')
        text = self.url_open('/service/zuschuss-hilfe').text
        self.assertRegex(text, r'<a[^>]*href="/web/content/42/richtlinien.pdf"[^>]*>')
        self.assertIn('Zuschussrichtlinien öffnen', text)
        form = self.url_open('/service/antrag-stellen').text
        self.assertRegex(
            form, r'<a[^>]*href="/web/content/42/richtlinien.pdf"[^>]*>Zuschussrichtlinien</a>')

    def test_missing_age_keeps_rows(self):
        """Fehlt das Alter in Zeile 2, kommt der Antrag mit Meldung zurück und
        Zeile 2 steht weiter im Formular."""
        response = self.url_open('/service/antrag-stellen', data=self._payload(
            tn_name_2='Ben Beispiel', tn_age_2=''))
        self.assertIn('Zeile 2 (Ben Beispiel): Alter fehlt', response.text)
        self.assertIn('name="tn_name_2"', response.text)
        self.assertIn('value="Ben Beispiel"', response.text)
        self.assertFalse(self._apps())

    def test_complete_application_saved(self):
        response = self.url_open('/service/antrag-stellen', data=self._payload(
            tn_name_3='Carl Beispiel', tn_age_3='15'))
        self.assertIn('antrag-bestaetigung', response.url)
        app = self._apps()
        self.assertEqual(len(app), 1)
        self.assertEqual(sorted(app.participant_ids.mapped('age')), [14, 15])
        self.assertEqual(len(app.receipt_ids), 1)
        self.assertFalse(app.receipt_ids.category)
        self.assertEqual(app.deficit, 60.0)

    def test_templates_downloadable(self):
        response = self.url_open('/service/zuschuss/vorlage-kostenaufstellung-belegliste.xlsx')
        self.assertEqual(response.status_code, 200)
        self.assertIn('spreadsheetml', response.headers.get('Content-Type', ''))
        self.assertTrue(response.content.startswith(b'PK'))
        page = self.url_open('/service/zuschuss/belegliste-vorlage').text
        self.assertIn('Kostenaufstellung zum Zuschussantrag', page)
