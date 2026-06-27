# -*- coding: utf-8 -*-
"""301-Weiterleitungen der alten /kjr/…-Pfade auf die neuen /service/…-Pfade
(Einrichtungsbuchung). Reine GET-Landingpages."""
from odoo import http
from odoo.http import request


class KjrFacilityLegacyRedirect(http.Controller):

    def _moved(self, target):
        qs = request.httprequest.query_string.decode()
        if qs:
            target = target + '?' + qs
        return request.redirect(target, code=301)

    @http.route('/kjr/einrichtungen', type='http', auth='public', website=True, sitemap=False)
    def legacy_facilities(self, **kw):
        return self._moved('/service/einrichtungen')

    @http.route('/kjr/einrichtung/<int:facility_id>', type='http', auth='public', website=True, sitemap=False)
    def legacy_facility(self, facility_id, **kw):
        return self._moved('/service/einrichtung/%d' % facility_id)
