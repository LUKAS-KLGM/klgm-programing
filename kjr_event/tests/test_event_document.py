# -*- coding: utf-8 -*-
"""Tests für E11: Dokumente-Block (kjr.event.document)."""
import base64

from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestKjrEventDocument(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.event = cls.env['event.event'].create({
            'name': 'Herbstferienprogramm 2026',
            'date_begin': '2026-10-26 09:00:00',
            'date_end': '2026-10-30 17:00:00',
        })

    def _doc(self, **kw):
        vals = {
            'event_id': self.event.id,
            'name': 'Packliste',
            'datas': base64.b64encode(b'%PDF-1.4 fake'),
            'datas_fname': 'packliste.pdf',
        }
        vals.update(kw)
        return self.env['kjr.event.document'].create(vals)

    def test_document_linked_to_event(self):
        """Ein angelegtes Dokument taucht in event.kjr_document_ids auf."""
        doc = self._doc()
        self.assertIn(doc, self.event.kjr_document_ids)

    def test_download_url_contains_filename(self):
        """Download-URL referenziert Model/ID und enthält den (quotierten) Dateinamen."""
        doc = self._doc(datas_fname='eltern brief.pdf')
        self.assertIn(f'/web/content/kjr.event.document/{doc.id}/datas/', doc.download_url)
        self.assertIn('eltern%20brief.pdf', doc.download_url)

    def test_document_deleted_with_event(self):
        """ondelete='cascade': Löschen der Veranstaltung löscht auch ihre Dokumente."""
        doc = self._doc()
        doc_id = doc.id
        self.event.unlink()
        self.assertFalse(self.env['kjr.event.document'].search([('id', '=', doc_id)]))
