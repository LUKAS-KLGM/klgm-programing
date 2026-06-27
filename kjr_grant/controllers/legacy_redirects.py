# -*- coding: utf-8 -*-
"""301-Weiterleitungen der alten /kjr/…-Pfade auf die neuen /service/…-Pfade.

Damit laufen bereits geteilte, gebookmarkte oder von Suchmaschinen indexierte
alte Links nicht ins Leere. Reine GET-Landingpages; Formular-POST-Endpunkte
brauchen keine Weiterleitung (ihre Formular-Action zeigt bereits auf /service/…).
"""
from odoo import http
from odoo.http import request


class KjrGrantLegacyRedirect(http.Controller):

    def _moved(self, target):
        qs = request.httprequest.query_string.decode()
        if qs:
            target = target + '?' + qs
        return request.redirect(target, code=301)

    @http.route('/kjr/zuschuss', type='http', auth='public', website=True, sitemap=False)
    def legacy_zuschuss(self, **kw):
        return self._moved('/service/zuschuss')

    @http.route('/kjr/antrag-stellen', type='http', auth='public', website=True, sitemap=False)
    def legacy_antrag_stellen(self, **kw):
        return self._moved('/service/antrag-stellen')

    @http.route('/kjr/antrag-bestaetigung', type='http', auth='public', website=True, sitemap=False)
    def legacy_antrag_bestaetigung(self, **kw):
        return self._moved('/service/antrag-bestaetigung')
