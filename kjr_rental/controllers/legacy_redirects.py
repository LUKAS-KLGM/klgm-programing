# -*- coding: utf-8 -*-
"""301-Weiterleitungen der alten /kjr/…-Pfade auf die neuen /service/…-Pfade
(Materialverleih). Reine GET-Landingpages."""
from odoo import http
from odoo.http import request


class KjrRentalLegacyRedirect(http.Controller):

    def _moved(self, target):
        qs = request.httprequest.query_string.decode()
        if qs:
            target = target + '?' + qs
        return request.redirect(target, code=301)

    @http.route('/kjr/verleih', type='http', auth='public', website=True, sitemap=False)
    def legacy_rental(self, **kw):
        return self._moved('/service/verleih')

    @http.route('/kjr/verleih/warenkorb', type='http', auth='public', website=True, sitemap=False)
    def legacy_cart(self, **kw):
        return self._moved('/service/verleih/warenkorb')
