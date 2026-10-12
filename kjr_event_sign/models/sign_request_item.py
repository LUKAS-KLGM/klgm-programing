# -*- coding: utf-8 -*-
"""Vorbefüllung aus der Anmeldung nur für die eigene Unterschriftsanfrage.

Odoo Sign (19, ``sign.request.item._get_auto_field_value``) liest den Wert
eines Feldtyps mit ``auto_field`` aus ``reference_doc`` der Anfrage, und zwar
in beiden Lesewegen mit Systemrechten:

* beim Anlegen der Anfrage (``sign.request._populate_constant_items``, auf
  ``self.sudo().request_item_ids``),
* auf der Signierseite (``sign/controllers/main.py``, ``auto_value`` für JEDEN
  Feldtyp mit ``auto_field``, unabhängig von der Vorlage).

Das Leserecht an ``reference_doc`` prüft Odoo Sign dabei nicht. Ohne diese
Sperre könnte jede Person mit Sign-Rechten (``sign.group_sign_user`` darf
Anfragen anlegen) eine Anfrage mit ``reference_doc = event.registration,<id>``
und sich selbst als Unterzeichner/in anlegen und so den feldgeschützten Namen
der/des Erziehungsberechtigten (``guardian_name``, KJR_SENSITIVE_DATA_GROUP)
oder den Namen des Kindes jeder Anmeldung lesen.

Regel: Für Feldtypen auf dem Modell ``event.registration`` liefert die
Methode nur dann einen Wert, wenn die Anfrage die aktuelle Anfrage der
Anmeldung ist (``kjr_sign_request_id``) oder gerade von der Brücke für diese
Anmeldung angelegt wird (Merker in ``cr.cache``, gesetzt in
``event.registration._kjr_sign_create_request``; per RPC nicht setzbar).
Sonst ein leerer Wert. ``kjr_sign_request_id`` setzt nur die Brücke mit
Systemrechten; ``event.registration.create/write`` weisen jeden anderen
Versuch ab (``_kjr_sign_check_request_link``), sonst könnte man die eigene
Anfrage per RPC zur aktuellen machen. Bereits gespeicherte Werte (sign.request.item.value)
bleiben unberührt; das Dokument einer früheren Anfrage zeigt weiter, was beim
Anlegen übernommen wurde.
"""
from odoo import models

from .event_registration import PREFILL_CACHE_KEY


class SignRequestItem(models.Model):
    _inherit = 'sign.request.item'

    def _get_auto_field_value(self, item_type):
        self.ensure_one()
        item_type_sudo = self.env['sign.item.type'].sudo().browse(item_type['id'])
        if item_type_sudo.model_id.model == 'event.registration' \
                and not self._kjr_sign_prefill_allowed():
            return ''
        return super()._get_auto_field_value(item_type)

    def _kjr_sign_prefill_allowed(self):
        """True, wenn die Anfrage dieses Unterzeichners Werte aus ihrer
        Anmeldung (reference_doc) übernehmen darf; siehe Moduldokumentation.
        Ohne Anmeldung als reference_doc True (Odoo Sign liefert dann selbst
        einen leeren Wert)."""
        self.ensure_one()
        request = self.sudo().sign_request_id
        doc = request.reference_doc
        if not doc or doc._name != 'event.registration':
            return True
        reg = doc.sudo().exists()
        if not reg:
            return False
        if reg.id in self.env.cr.cache.get(PREFILL_CACHE_KEY, ()):
            return True
        return reg.kjr_sign_request_id == request
