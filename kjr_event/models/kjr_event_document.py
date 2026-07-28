# -*- coding: utf-8 -*-
"""E11: Dokumente (z. B. PDF-Merkblätter/Hinweise) zu einer Veranstaltung.

Mehrere Dateien pro Veranstaltung, anzeigbar auf der Website als optionaler
Sidebar-Block (siehe ``views/website_event_templates.xml``).
"""
from urllib.parse import quote

from odoo import api, fields, models


class KjrEventDocument(models.Model):
    _name = 'kjr.event.document'
    _description = 'KJR Veranstaltungsdokument'
    _order = 'sequence, id'

    name = fields.Char(string='Bezeichnung', required=True)
    sequence = fields.Integer(string='Reihenfolge', default=10)
    event_id = fields.Many2one(
        'event.event', string='Veranstaltung', required=True, ondelete='cascade', index=True,
    )
    datas = fields.Binary(string='Datei', required=True)
    datas_fname = fields.Char(string='Dateiname')
    download_url = fields.Char(string='Download-URL', compute='_compute_download_url')

    @api.depends('datas_fname')
    def _compute_download_url(self):
        for doc in self:
            if not doc.id:
                doc.download_url = False
                continue
            filename = quote(doc.datas_fname or doc.name or 'dokument')
            doc.download_url = f'/web/content/kjr.event.document/{doc.id}/datas/{filename}?download=true'
