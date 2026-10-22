# -*- coding: utf-8 -*-
"""Öffentliche Downloadseite /service/downloads und Auslieferung der Dateien."""
from odoo import http
from odoo.http import request

INLINE_MIMETYPES = ('application/pdf', 'image/png', 'image/jpeg', 'image/gif')


class WebsiteDownloadController(http.Controller):

    def _public_downloads(self):
        Download = request.env['website.download'].sudo()
        return Download.search(Download._public_domain(request.website))

    @http.route('/service/downloads', type='http', auth='public', website=True, sitemap=True)
    def downloads(self, **kw):
        downloads = self._public_downloads()
        # Gruppen in der Reihenfolge der Kategorien; ohne Kategorie zum Schluss.
        categories = downloads.mapped('category_id').sorted(lambda c: (c.sequence, c.name or '', c.id))
        groups = [(category, downloads.filtered(lambda d, c=category: d.category_id == c))
                  for category in categories]
        uncategorized = downloads.filtered(lambda d: not d.category_id)
        if uncategorized:
            groups.append((None, uncategorized))
        return request.render('kjr_website_downloads.downloads_page', {
            'download_groups': groups,
            'page_name': 'downloads',
        })

    @http.route('/service/downloads/<int:download_id>', type='http', auth='public',
                website=True, sitemap=False)
    def download_file(self, download_id, **kw):
        Download = request.env['website.download'].sudo()
        download = Download.search(
            Download._public_domain(request.website) + [('id', '=', download_id)], limit=1)
        if not download:
            raise request.not_found()
        stream = request.env['ir.binary']._get_stream_from(
            download, 'datas', filename=download.filename or download.name)
        # PDFs und Rasterbilder öffnet der Browser direkt, alles andere (auch SVG)
        # wird gespeichert.
        inline = (stream.mimetype or '') in INLINE_MIMETYPES
        return stream.get_response(as_attachment=not inline)
