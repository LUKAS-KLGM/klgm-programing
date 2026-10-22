# -*- coding: utf-8 -*-
"""Downloadbereich der Website: Kategorien und Dateien.

Die Datei liegt als Anhang am Datensatz (Binary mit attachment=True). Öffentlich
ausgeliefert wird sie nur über den Controller /service/downloads/<id>, der
Veröffentlichung und Website prüft; Besucher brauchen deshalb keine Leserechte
am Modell.
"""
import os

from odoo import api, fields, models

# Anzeige des Dateityps nach Endung. Unbekannte Endungen erscheinen in
# Großbuchstaben (z. B. „ODT“), ohne Endung als „Datei“.
FILE_TYPE_LABELS = {
    'pdf': 'PDF',
    'doc': 'Word', 'docx': 'Word', 'odt': 'Text (ODT)', 'rtf': 'Text (RTF)', 'txt': 'Text',
    'xls': 'Excel', 'xlsx': 'Excel', 'ods': 'Tabelle (ODS)', 'csv': 'CSV',
    'ppt': 'PowerPoint', 'pptx': 'PowerPoint', 'odp': 'Präsentation (ODP)',
    'jpg': 'Bild (JPG)', 'jpeg': 'Bild (JPG)', 'png': 'Bild (PNG)', 'gif': 'Bild (GIF)',
    'svg': 'Bild (SVG)', 'zip': 'ZIP-Archiv', 'mp3': 'Audio (MP3)', 'mp4': 'Video (MP4)',
}


def format_file_size(size):
    """Dateigröße deutsch formatiert: „850 Byte“, „12 KB“, „1,4 MB“."""
    if not size:
        return ''
    if size < 1024:
        return '%d Byte' % size
    if size < 1024 * 1024:
        return '%d KB' % round(size / 1024.0)
    return ('%.1f MB' % (size / (1024.0 * 1024.0))).replace('.', ',')


class WebsiteDownloadCategory(models.Model):
    _name = 'website.download.category'
    _description = 'Download-Kategorie'
    _order = 'sequence, name, id'

    name = fields.Char(string='Name', required=True, translate=True)
    sequence = fields.Integer(string='Reihenfolge', default=10)
    active = fields.Boolean(string='Aktiv', default=True)
    download_ids = fields.One2many('website.download', 'category_id', string='Downloads')
    download_count = fields.Integer(string='Anzahl Downloads', compute='_compute_download_count')

    @api.depends('download_ids')
    def _compute_download_count(self):
        for category in self:
            category.download_count = len(category.download_ids)


class WebsiteDownload(models.Model):
    _name = 'website.download'
    _description = 'Download'
    _order = 'sequence, date desc, name, id'

    name = fields.Char(string='Titel', required=True, translate=True)
    description = fields.Text(string='Beschreibung', translate=True)
    datas = fields.Binary(string='Datei', attachment=True, required=True)
    filename = fields.Char(string='Dateiname')
    category_id = fields.Many2one(
        'website.download.category', string='Kategorie', index=True, ondelete='restrict',
        help='Ohne Kategorie erscheint der Download unter „Weitere Downloads“.')
    is_published = fields.Boolean(string='Veröffentlicht', default=False, copy=False, index=True)
    sequence = fields.Integer(string='Reihenfolge', default=10)
    date = fields.Date(string='Datum', default=fields.Date.context_today,
                       help='Stand bzw. Ausgabedatum des Dokuments, wird auf der Website angezeigt.')
    website_id = fields.Many2one(
        'website', string='Website', ondelete='cascade', index=True,
        help='Leer = auf allen Websites sichtbar.')
    active = fields.Boolean(string='Aktiv', default=True)
    file_size = fields.Integer(string='Größe (Byte)', compute='_compute_file_info')
    file_size_label = fields.Char(string='Größe', compute='_compute_file_info')
    file_type_label = fields.Char(string='Dateityp', compute='_compute_file_info')
    mimetype = fields.Char(string='MIME-Typ', compute='_compute_file_info')

    @api.depends('datas', 'filename')
    def _compute_file_info(self):
        attachments = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', self._name), ('res_field', '=', 'datas'),
            ('res_id', 'in', [rid for rid in self.ids if isinstance(rid, int)]),
        ])
        by_res = {att.res_id: att for att in attachments}
        for download in self:
            att = by_res.get(download.id) if isinstance(download.id, int) else None
            download.file_size = att.file_size if att else 0
            download.file_size_label = format_file_size(download.file_size)
            download.mimetype = att.mimetype if att else False
            download.file_type_label = download._file_type_from_name(download.filename or (att and att.name))

    @staticmethod
    def _file_type_from_name(name):
        ext = os.path.splitext(name or '')[1].lstrip('.').lower()
        if not ext:
            return 'Datei'
        return FILE_TYPE_LABELS.get(ext, ext.upper())

    def _download_url(self):
        """Öffentliche Adresse der Datei (Controller prüft Veröffentlichung)."""
        self.ensure_one()
        return '/service/downloads/%d' % self.id

    @api.model
    def _public_domain(self, website):
        return [
            ('is_published', '=', True),
            ('website_id', 'in', (False, website.id)),
            '|', ('category_id', '=', False), ('category_id.active', '=', True),
        ]

    def action_toggle_published(self):
        for download in self:
            download.is_published = not download.is_published
