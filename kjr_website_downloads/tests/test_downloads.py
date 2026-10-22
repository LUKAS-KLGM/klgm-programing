# -*- coding: utf-8 -*-
"""Downloadbereich: Modell, Rechte, öffentliche Seite und Auslieferung."""
import base64

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import HttpCase, TransactionCase, new_test_user

from odoo.addons.kjr_website_downloads.models.website_download import format_file_size

PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n'


def _vals(**kw):
    vals = {
        'name': 'Positionspapier',
        'datas': base64.b64encode(PDF),
        'filename': 'positionspapier.pdf',
        'is_published': True,
        'date': '2026-10-01',
    }
    vals.update(kw)
    return vals


@tagged('post_install', '-at_install')
class TestWebsiteDownloadModel(TransactionCase):

    def test_groesse_und_typ(self):
        download = self.env['website.download'].create(_vals())
        self.assertEqual(download.file_size, len(PDF))
        self.assertEqual(download.file_size_label, '%d Byte' % len(PDF))
        self.assertEqual(download.file_type_label, 'PDF')
        self.assertEqual(download.mimetype, 'application/pdf')
        self.assertEqual(format_file_size(1536), '2 KB')
        self.assertEqual(format_file_size(int(1.45 * 1024 * 1024)), '1,4 MB')
        Download = self.env['website.download']
        self.assertEqual(Download._file_type_from_name('a.DOCX'), 'Word')
        self.assertEqual(Download._file_type_from_name('a.odg'), 'ODG')
        self.assertEqual(Download._file_type_from_name('ohne'), 'Datei')

    def test_rechte_designer_pflegt(self):
        designer = new_test_user(self.env, login='dl_designer',
                                 groups='base.group_user,website.group_website_designer')
        category = self.env['website.download.category'].with_user(designer).create({'name': 'Positionen'})
        download = self.env['website.download'].with_user(designer).create(_vals(category_id=category.id))
        download.with_user(designer).write({'name': 'Neu'})
        employee = new_test_user(self.env, login='dl_employee', groups='base.group_user')
        with self.assertRaises(AccessError):
            self.env['website.download'].with_user(employee).create(_vals())
        with self.assertRaises(AccessError):
            download.with_user(employee).read(['name'])

    def test_kein_website_menue(self):
        """Ein Menüpunkt auf der Website wird bewusst nicht angelegt."""
        self.assertFalse(self.env['website.menu'].search([('url', '=', '/service/downloads')]))


@tagged('post_install', '-at_install')
class TestWebsiteDownloadHttp(HttpCase):

    def setUp(self):
        super().setUp()
        Category = self.env['website.download.category']
        self.cat_b = Category.create({'name': 'Schutzkonzept', 'sequence': 20})
        self.cat_a = Category.create({'name': 'Positionen', 'sequence': 10})
        Download = self.env['website.download']
        self.pub = Download.create(_vals(name='Positionspapier Jugendarbeit', category_id=self.cat_a.id))
        self.pub_b = Download.create(_vals(name='Baustein Risikoanalyse', category_id=self.cat_b.id,
                                           filename='baustein.docx'))
        self.loose = Download.create(_vals(name='Ohne Rubrik'))
        self.hidden = Download.create(_vals(name='Entwurf intern', is_published=False))

    def test_seite_gruppiert_und_nur_veroeffentlicht(self):
        resp = self.url_open('/service/downloads')
        self.assertEqual(resp.status_code, 200)
        text = resp.text
        self.assertIn('Positionspapier Jugendarbeit', text)
        self.assertNotIn('Entwurf intern', text)
        # Kategorien nach Reihenfolge, ohne Kategorie zum Schluss.
        self.assertLess(text.index('Positionen'), text.index('Schutzkonzept'))
        self.assertLess(text.index('Schutzkonzept'), text.index('Weitere Downloads'))
        self.assertIn('(PDF, %d Byte)' % len(PDF), text)
        self.assertIn('Word', text)
        self.assertIn('datetime="2026-10-01"', text)
        self.assertIn('href="/service/downloads/%d"' % self.pub.id, text)

    def test_auslieferung(self):
        resp = self.url_open('/service/downloads/%d' % self.pub.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, PDF)
        self.assertIn('application/pdf', resp.headers.get('Content-Type'))
        self.assertEqual(self.url_open('/service/downloads/%d' % self.hidden.id).status_code, 404)
        self.cat_b.active = False
        self.assertEqual(self.url_open('/service/downloads/%d' % self.pub_b.id).status_code, 404)
        self.assertNotIn('Baustein Risikoanalyse', self.url_open('/service/downloads').text)

    def test_andere_website(self):
        other = self.env['website'].create({'name': 'Andere Website'})
        self.pub.website_id = other
        self.assertEqual(self.url_open('/service/downloads/%d' % self.pub.id).status_code, 404)
