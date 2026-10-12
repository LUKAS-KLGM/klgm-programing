# -*- coding: utf-8 -*-
"""Einwilligungs-Sperre (kjr_event 19.0.5.9.0) bei Anmeldungen mit Verkaufsauftrag.

Mit event_sale ist ``event.registration.state`` ein gespeichertes Compute-Feld
(``_compute_registration_status``, abhängig vom Status und Betrag des
Auftrags). Würde die Freigabe der Sperre einen festen Status schreiben, käme ein
UNBEZAHLTER Auftrag auf "registriert". Deshalb schreibt kjr_event bei Anmeldungen
mit Auftrag nur ``kjr_consent_hold = False`` (``_kjr_consent_release_state`` ist
dort None) und dieser Override macht die Sperre zur zusätzlichen Abhängigkeit
des Computes:

* gesperrt: bleibt unbestätigt, auch wenn der Auftrag bestätigt oder kostenlos
  ist (der Kern-Compute würde sonst auf "registriert" setzen);
* entsperrt: event_sale entscheidet wie gewohnt (zu bezahlen bleibt
  unbestätigt, verkauft oder kostenlos wird registriert). Die Kern-Mails startet
  event_sale dabei genau einmal (``_compute_field_value``, nur beim Übergang
  nach "registriert").
* Wartelistenplatz (``kjr_is_waitlist``): bleibt ebenfalls unbestätigt, auch
  nach Wegfall der Sperre oder Bestätigung des Auftrags. Sonst würde
  event_sale einen kostenlosen bzw. verkauften Wartelistenplatz ohne
  Platzprüfung auf "registriert" setzen (bei voller Veranstaltung scheitert
  stattdessen die Platzprüfung des Kerns). Registriert wird ein
  Wartelistenplatz nur über "Von Warteliste nachrücken", das Status und
  Wartelisten-Merker gemeinsam schreibt.
"""
from odoo import api, models


class EventRegistration(models.Model):
    _inherit = 'event.registration'

    @api.depends('kjr_consent_hold', 'kjr_is_waitlist')
    def _compute_registration_status(self):
        super()._compute_registration_status()
        self.filtered(
            lambda r: (r.kjr_consent_hold or r.kjr_is_waitlist)
            and r.state in ('open', 'done')
        ).state = 'draft'

    def _kjr_consent_defer_request(self):
        """Unterschriftsanfrage zurückstellen, solange der Auftrag ein Warenkorb ist.

        Abgebrochene Warenkörbe sollen weder eine Anfrage noch einen Kontakt der
        Erziehungsberechtigten erzeugen. Ausgelöst wird die Anfrage beim Wechsel
        des Auftrags auf "gesendet" oder "Auftrag" (models/sale_order.py).
        """
        self.ensure_one()
        order = self.sudo().sale_order_id
        return bool(order and order.state == 'draft') or super()._kjr_consent_defer_request()

    @api.model
    def _kjr_consent_reminder_domain(self):
        """Keine Einwilligungs-Erinnerung an gesperrte Anmeldungen im Warenkorb.

        Gleiche Bedingung wie _kjr_consent_defer_request als Domain: ein
        abgebrochener Warenkorb soll keinen Kontakt zu den Erziehungsberechtigten
        auslösen (kjr_event prüft zusätzlich je Datensatz,
        _kjr_consent_reminder_allowed).
        """
        return super()._kjr_consent_reminder_domain() + [
            '|', ('kjr_consent_hold', '=', False),
            '|', ('sale_order_id', '=', False), ('sale_order_id.state', '!=', 'draft'),
        ]
