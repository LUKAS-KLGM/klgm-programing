# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class KjrAntispamController(http.Controller):
    """Liefert das Zeittoken für Formulare, die nicht serverseitig gerendert
    werden können (Website-Builder-Formulare, form[data-captcha]).

    Das Token ist kein Geheimnis gegenüber dem Besucher: es belegt nur, dass
    die Seite mindestens min_seconds vor dem Absenden geladen wurde und nicht
    älter als max_age_hours ist. readonly=True: es wird nichts geschrieben.
    """

    @http.route('/service/antispam/token', type='jsonrpc', auth='public', website=True,
                methods=['POST'], csrf=False, sitemap=False, readonly=True)
    def kjr_antispam_token(self, **kwargs):
        return {'token': request.env['ir.http']._kjr_antispam_token()}
