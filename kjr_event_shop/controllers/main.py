# -*- coding: utf-8 -*-
"""Deterministische Reihenfolge der Anmelde-Controller (KJR außen, Verkauf innen).

Odoo baut die Controller beim Laden aus den BLATT-Klassen jeder
Vererbungslinie zusammen (``odoo/http.py``, ``_generate_routing_rules``:
``get_leaf_classes`` und ``type(name, tuple(reversed(leaf_controllers)), {})``).
Erben ``KjrWebsiteEventController`` (kjr_event) und
``WebsiteEventSaleController`` (website_event_sale) unabhängig voneinander von
``WebsiteEventController``, gibt es ZWEI Blätter. Ihre Reihenfolge hängt dann an
der Importreihenfolge der Module, und damit, ob die KJR-Vorprüfung vor oder
nach dem Anlegen des Warenkorbs läuft.

Diese Klasse ist das einzige gemeinsame Blatt beider Linien. Ihre MRO ist fest:
KjrWebsiteEventController, WebsiteEventSaleController, WebsiteEventController.
Für die Online-Anmeldung heißt das:

1. KJR-Vorprüfung der Einwilligung (bei Fehler zurück, es entsteht KEIN
   Warenkorb), danach der Kontext für die Einwilligungs-Sperre;
2. Verkaufslogik (Warenkorb bzw. Bestätigung bei 0 Euro, Weiterleitung in den
   Shop) und Kern (Captcha, Platzprüfung, Anlegen);
3. KJR-Angaben schreiben und die Sperren auflösen.

Kein anderes Modul darf von ``KjrWebsiteEventController`` erben (auch nicht
kjr_event_sign), sonst entstünde wieder ein zweites Blatt.
"""
from odoo import http

from odoo.addons.kjr_event.controllers.website_event import KjrWebsiteEventController
from odoo.addons.website_event_sale.controllers.main import WebsiteEventSaleController


class KjrEventShopController(KjrWebsiteEventController, WebsiteEventSaleController):

    @http.route()
    def registration_confirm(self, event, **post):
        """Reicht nur durch; die Reihenfolge ergibt sich aus der MRO (siehe Modulkopf)."""
        return super().registration_confirm(event, **post)
