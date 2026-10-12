# -*- coding: utf-8 -*-
"""B51: Ziel der QR-Codes auf den Inventaretiketten.

Der QR-Code trägt die Adresse /kjr_rental/scan/<Barcode>. Scannt man ihn mit der
normalen Kamera-App eines Handys, öffnet sich der Browser; nach der Anmeldung
(auth='user' leitet ohne Sitzung auf /web/login mit Rücksprung) landet man direkt
im Artikel mit Lagerort, Lagerplatz und dem Button "Rückgabe zuordnen".
Der Scanner im Backend (Client-Aktion "Scannen") liest dieselbe Adresse und
braucht diese Route nicht.
"""
from odoo import http
from odoo.http import request

SCAN_ACTION_URL = '/odoo/action-kjr_rental.action_kjr_rental_scan'
ITEM_FORM_URL = '/odoo/action-kjr_rental.action_kjr_rental_item/%d'


class KjrRentalScanController(http.Controller):

    # website=True: nur damit die Hinweisseite für fehlende Rechte im Layout der
    # Website gerendert werden kann (website.layout braucht request.website).
    @http.route('/kjr_rental/scan/<path:code>', type='http', auth='user',
                website=True, methods=['GET'], sitemap=False)
    def kjr_rental_scan(self, code, **kwargs):
        # Nur Verleih-Personal: Portalbenutzer sind ebenfalls "angemeldet",
        # dürfen den Artikelstamm im Backend aber nicht öffnen.
        user = request.env.user
        if not user.has_group('kjr_rental.group_kjr_rental_user'):
            if user._is_internal():
                # Interne Mitarbeitende (z. B. Geschäftsstelle mit der Handykamera):
                # der QR-Code ist echt, es fehlt nur die Gruppe. Ein 404 "Seite
                # nicht gefunden" wäre hier irreführend.
                return request.render(
                    'kjr_rental.scan_no_access', {}, status=403)
            # Portal- und sonstige Benutzer: nicht verraten, dass es die Route gibt.
            raise request.not_found()
        item = request.env['kjr.rental.item']._find_by_scan(code)
        if not item:
            # Unbekannter Code: Scanansicht öffnen, dort kann neu gescannt bzw.
            # die Nummer von Hand eingegeben werden.
            return request.redirect(SCAN_ACTION_URL)
        return request.redirect(ITEM_FORM_URL % item.id)
