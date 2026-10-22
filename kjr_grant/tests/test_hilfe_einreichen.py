# -*- coding: utf-8 -*-
"""Termin 13.10.2026 (19.0.18.0.0): Hilfeseite, Einreichen im Portal, Sprache.

* Hilfeseite unter /service/zuschuss/hilfe, alte Adresse leitet dauerhaft um,
  Texte im Website-Editor überschreibbar (oe_structure mit eigener id, ohne QWeb).
* Einreichen eines Entwurfs aus dem Portal: Erfolg und Fehlerpfad.
* Upload-Dateinamen tragen die Feldbeschriftung (Vollständigkeitsprüfung).
* Migration der Texte (Anrede, Gendern) in Mailvorlagen und Förderarten.
"""
import importlib.util

from lxml import etree

from odoo import http
from odoo.tests import tagged
from odoo.tests.common import HttpCase, TransactionCase, new_test_user
from odoo.tools.misc import file_path

from odoo.addons.kjr_grant.controllers.website import upload_attachment_name

MIGRATION = 'kjr_grant/migrations/19.0.18.0.0/post-sprache.py'


def _load_migration():
    spec = importlib.util.spec_from_file_location('kjr_grant_sprache_18', file_path(MIGRATION))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged('post_install', '-at_install')
class TestKjrHilfeTexte(TransactionCase):

    def test_editierbare_bereiche_ohne_qweb(self):
        """Jeder oe_structure-Bereich hat eine id und enthält kein QWeb, sonst
        würde der Editor gerenderte Werte als festen Text speichern."""
        view = self.env.ref('kjr_grant.website_kjr_apply_help')
        root = etree.fromstring(view.arch_db.encode())
        areas = root.xpath('//*[contains(concat(" ", @class, " "), " oe_structure ")]')
        self.assertGreaterEqual(len(areas), 8)
        ids = [a.get('id') for a in areas]
        self.assertTrue(all(ids), ids)
        self.assertEqual(len(ids), len(set(ids)))
        for area in areas:
            for el in area.iter():
                if not isinstance(el.tag, str):
                    continue
                self.assertNotEqual(el.tag, 't', area.get('id'))
                self.assertFalse([k for k in el.attrib if k.startswith('t-')], area.get('id'))

    def test_upload_name(self):
        self.assertEqual(upload_attachment_name('receipt_file', 'Scan.pdf'), 'Belegliste - Scan.pdf')
        self.assertEqual(upload_attachment_name('receipt_file', 'Belegliste.pdf'), 'Belegliste.pdf')
        self.assertEqual(upload_attachment_name('unbekannt', 'x.pdf'), 'x.pdf')

    def test_migration_textfunktion(self):
        mig = _load_migration()
        neu, n = mig.ersetze(
            "<p>Sehr geehrte/r <t t-out=\"object.contact_person or 'Antragsteller/in'\"/>,</p>",
            mig.MAIL_REPLACEMENTS)
        self.assertEqual(neu, "<p>Guten Tag <t t-out=\"object.contact_person or 'Antragsteller:in'\"/>,</p>")
        self.assertEqual(n, 2)
        # Gepflegter Text ohne die ausgelieferten Teilstücke bleibt stehen.
        self.assertEqual(mig.ersetze('<p>Hallo Verein,</p>', mig.MAIL_REPLACEMENTS), ('<p>Hallo Verein,</p>', 0))

    def test_migration_datenbank(self):
        mig = _load_migration()
        template = self.env.ref('kjr_grant.mail_template_grant_submitted')
        alt = str(template.body_html).replace('Guten Tag ', 'Sehr geehrte/r ').replace(
            "'Antragsteller:in'", "'Antragsteller/in'")
        template.body_html = alt
        gt = self.env.ref('kjr_grant.grant_type_4_9')
        gt.description = 'Jeder stimmberechtigte Delegierte, der zur KJR-Vollversammlung anreist, ' \
                         'erhält auf Antrag ... je Mitfahrer/in; ... auf das Konto des/der Delegierten möglich.'
        mig.migrate(self.env.cr, '19.0.17.0.0')
        template.invalidate_recordset()
        gt.invalidate_recordset()
        self.assertIn('Guten Tag ', str(template.body_html))
        self.assertNotIn('/r ', str(template.body_html))
        self.assertIn('Alle stimmberechtigten Delegierten', gt.description)
        self.assertIn('Mitfahrer:in', gt.description)
        self.assertIn('Konto der delegierten Person', gt.description)
        # Zweiter Lauf ändert nichts (idempotent).
        vorher = (str(template.body_html), gt.description)
        mig.migrate(self.env.cr, '19.0.17.0.0')
        template.invalidate_recordset()
        gt.invalidate_recordset()
        self.assertEqual(vorher, (str(template.body_html), gt.description))


@tagged('post_install', '-at_install')
class TestKjrHilfeHttp(HttpCase):

    LOGIN = 'kjr_einreichen_portal'

    def test_hilfeseite_und_umleitung(self):
        resp = self.url_open('/service/zuschuss/hilfe')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Wie stelle ich einen Zuschussantrag?', resp.text)
        self.assertIn('id="oe_structure_kjr_help_registrierung"', resp.text)
        self.assertIn('Verwendungsnachweis', resp.text)
        resp = self.url_open('/service/zuschuss-hilfe', allow_redirects=False)
        self.assertEqual(resp.status_code, 301)
        self.assertTrue(resp.headers['Location'].endswith('/service/zuschuss/hilfe'))
        landing = self.url_open('/service/zuschuss').text
        self.assertIn('href="/service/zuschuss/hilfe"', landing)

    def _setup_portal(self):
        assoc = self.env['res.partner'].create({
            'name': 'Jugendverband Einreichen e. V.', 'is_company': True,
            'is_kjr_member': True, 'kjr_vr_right': True,
        })
        user = new_test_user(self.env, login=self.LOGIN, groups='base.group_portal')
        user.partner_id.parent_id = assoc
        self.authenticate(self.LOGIN, self.LOGIN)
        return assoc

    def _draft(self, assoc, **kw):
        vals = {
            'partner_id': assoc.id,
            'grant_type_id': self.env.ref('kjr_grant.grant_type_4_1a').id,
            'measure_name': 'Zeltlager', 'measure_start': '2026-07-01', 'measure_end': '2026-07-03',
            'measure_zip': '87527', 'measure_location': 'Sonthofen',
        }
        vals.update(kw)
        return self.env['kjr.grant.application'].create(vals)

    def test_einreichen_fehlerpfad(self):
        """Unvollständiger Entwurf: Meldung auf der Detailseite, bleibt Entwurf."""
        assoc = self._setup_portal()
        app = self._draft(assoc)
        detail = self.url_open('/my/kjr-antraege/%d' % app.id).text
        self.assertIn('Antrag einreichen', detail)
        resp = self.url_open('/my/kjr-antraege/%d/einreichen' % app.id,
                             data={'csrf_token': http.Request.csrf_token(self)})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Antrag unvollständig', resp.text)
        app.invalidate_recordset()
        self.assertEqual(app.state, 'draft')

    def test_einreichen_erfolg(self):
        assoc = self._setup_portal()
        app = self._draft(
            assoc, tn_count=2, tn_leader_count=1, cost_accommodation=100.0,
            payment_iban='DE89370400440532013000', payment_account_holder='Jugendverband',
            contact_person='Petra Prüfer', contact_email='petra@example.com',
            measure_report='Bericht zum Zeltlager.',
        )
        # Pflichtunterlagen der Förderart als Dateien mit Feldbeschriftung.
        for field, name in (('tn_list_file', 'tn.pdf'), ('report_file', 'b.pdf'), ('receipt_file', 'r.pdf')):
            self.env['ir.attachment'].create({
                'name': upload_attachment_name(field, name), 'raw': b'%PDF-1.4',
                'res_model': 'kjr.grant.application', 'res_id': app.id,
            })
        resp = self.url_open('/my/kjr-antraege/%d/einreichen' % app.id,
                             data={'csrf_token': http.Request.csrf_token(self)})
        self.assertEqual(resp.status_code, 200)
        app.invalidate_recordset()
        self.assertEqual(app.state, 'submitted', resp.text[:2000] if app.state == 'draft' else '')
        self.assertIn('Ihr Antrag ist eingereicht', resp.text)
