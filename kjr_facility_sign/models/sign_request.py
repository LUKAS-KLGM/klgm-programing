# -*- coding: utf-8 -*-
"""Hooks an sign.request: Unterschrift, Ablehnung, Storno, Ablauf.

Alle Hooks rufen super() ZUERST auf (Ausnahme: der Kontext bei _refuse, siehe
dort) und werfen selbst NIE: eine Unterschrift oder Ablehnung des Mieters darf
an einem Fehler auf KJR-Seite nicht scheitern. Wirkung entfalten sie nur, wenn
die Anfrage auf eine Buchung zeigt (reference_doc) UND diese Buchung genau
diese Anfrage als aktuelle führt (``kjr_sign_request_id``). Veraltete Anfragen,
etwa nach "Unterschrift erneut anfordern", bleiben damit ohne Wirkung.

Nur Anfragen, die die Brücke selbst angelegt hat (``kjr_facility_contract``),
gelten als Vertragsanfragen. Andere Anfragen, die die Geschäftsstelle über Odoo
Sign mit einer Buchung verknüpft (Hausordnung, Kautionsvereinbarung, ...),
bleiben unberührt, auch vom täglichen Lauf für verwaiste Anfragen.

Notizen und Aufgaben an der Buchung entstehen im Namen des Absenders der
Anfrage, wenn der Auslöser der öffentliche Benutzer bzw. ein Portalbenutzer
ist (Unterschrift und Ablehnung über den Mail-Link laufen ohne Anmeldung).

Notiztexte beim Storno kommen NIE als Freitext aus dem Kontext: der Schlüssel
``kjr_facility_sign_cancel_reason`` wählt nur einen festen Text aus.
"""
import logging

from markupsafe import Markup

from odoo import _, fields, models

_logger = logging.getLogger(__name__)

BOOKING_MODEL = 'kjr.facility.booking'


class SignRequest(models.Model):
    _inherit = 'sign.request'

    kjr_facility_contract = fields.Boolean(
        string='KJR-Buchungsvertrag', copy=False, readonly=True,
        help='Technisch: von kjr_facility_sign angelegte Unterschriftsanfrage zum '
             'Buchungsvertrag einer Einrichtungsbuchung. Nur solche Anfragen wirken auf '
             'die Buchung und werden als verwaist storniert.')

    def _kjr_facility_cancel_note(self, reason):
        return {
            'paper': _('Unterschriftsanfrage storniert: Vertrag liegt auf Papier vor.'),
            'resend': _('Unterschriftsanfrage storniert: wird neu versendet.'),
            'manual': _('Unterschriftsanfrage storniert.'),
            'booking_cancel': _('Unterschriftsanfrage storniert: Buchung storniert.'),
            'booking_reset': _('Unterschriftsanfrage storniert: Buchung auf Anfrage zurückgesetzt.'),
            'orphan': _('Unterschriftsanfrage storniert: gehört nicht mehr zur aktuellen Buchung.'),
        }.get(reason) or _('Unterschriftsanfrage storniert.')

    def _kjr_facility_reference_booking(self):
        """Buchung aus reference_doc (sudo), auch wenn diese Anfrage nicht (mehr)
        die aktuelle ist; sonst ein leeres Recordset. Nur für eigene
        Vertragsanfragen (``kjr_facility_contract``), nie für fremde Anfragen."""
        self.ensure_one()
        Booking = self.env[BOOKING_MODEL].sudo()
        if not self.sudo().kjr_facility_contract:
            return Booking
        doc = self.sudo().reference_doc
        if not doc or doc._name != BOOKING_MODEL:
            return Booking
        return doc.sudo().exists() or Booking

    def _kjr_facility_booking(self):
        """Buchung, die GENAU diese Anfrage führt; sonst leeres Recordset."""
        self.ensure_one()
        booking = self._kjr_facility_reference_booking()
        if booking and booking.kjr_sign_request_id == self:
            return booking
        return self.env[BOOKING_MODEL].sudo()

    def _kjr_facility_as_sender(self, booking, always=False):
        """Buchung im Namen des Absenders dieser Anfrage (Autor von Notiz,
        Aufgabe und write_uid), wenn der Aufrufer der öffentliche Benutzer bzw.
        ein Portalbenutzer ist oder ``always`` gesetzt ist. Sonst bleibt der
        handelnde interne Benutzer Autor."""
        self.ensure_one()
        sender = self.sudo().create_uid
        if not sender or not (always or self.env.user.share):
            return booking.sudo()
        return booking.with_user(sender).sudo().with_company(booking.company_id)

    def _sign(self):
        res = super()._sign()
        # Odoo Sign hat state='signed' gesetzt, die Nachricht "fully signed"
        # gepostet und eine Kopie des unterschriebenen PDF an die Buchung gehängt
        # (sign.request._sign / _send_completed_documents). Die Kopie bleibt: der
        # Portal-Download liefert das neueste PDF der Buchung.
        for req in self:
            booking = req._kjr_facility_booking()
            if not booking:
                continue
            if booking.state == 'cancelled':
                req._kjr_facility_as_sender(booking)._kjr_sign_activity(
                    _('Vertrag zu stornierter Buchung unterschrieben: %s', booking.name),
                    _('Der Vertrag wurde digital unterschrieben, die Buchung ist aber storniert. '
                      'Bitte prüfen.'))
                continue
            savepoint = self.env.cr.savepoint()
            try:
                with savepoint:
                    # _sign läuft als öffentlicher Benutzer mit sudo; geschrieben wird
                    # im Namen des Absenders (Autor der Feldhistorie).
                    writer = req._kjr_facility_as_sender(booking, always=True)
                    if not writer.contract_signed:
                        writer.with_context(kjr_facility_sign_digital=True).write(
                            {'contract_signed': True})
            except Exception as err:  # noqa: BLE001 - die Unterschrift hat Vorrang
                _logger.warning(
                    'KJR Einrichtung Sign: Übernahme der Unterschrift (Anfrage %s) in Buchung %s '
                    'fehlgeschlagen (%s).', req.id, booking.id, type(err).__name__,
                    exc_info=_logger.isEnabledFor(logging.DEBUG))
                req._kjr_facility_as_sender(booking)._kjr_sign_activity(
                    _('Vertrag digital unterschrieben, Übernahme fehlgeschlagen: %s', booking.name),
                    _('Bitte „Vertrag unterschrieben“ von Hand setzen.'))
        return res

    def _refuse(self, refuser, refusal_reason):
        # Kontext VOR super(): sign.request._refuse ruft intern cancel(); dort soll
        # keine zweite Notiz ("storniert") entstehen. Die Begründung des Mieters
        # bleibt an der Anfrage und kommt NICHT in den Chatter der Buchung.
        res = super(SignRequest, self.with_context(kjr_facility_sign_refusing=True))._refuse(
            refuser, refusal_reason)
        for req in self:
            booking = req._kjr_facility_booking()
            if not booking or booking.state == 'cancelled':
                continue
            savepoint = self.env.cr.savepoint()
            try:
                with savepoint:
                    # Ablehnung über den Mail-Link läuft als öffentlicher Benutzer
                    # (sign.request.item._refuse mit sudo): Notiz, Aufgabe und
                    # write_uid im Namen des Absenders, wie bei _sign.
                    writer = req._kjr_facility_as_sender(booking, always=True)
                    writer.write({'kjr_sign_refused': True})
                    writer._kjr_sign_notify_problem('refused')
            except Exception as err:  # noqa: BLE001 - die Ablehnung hat Vorrang
                _logger.warning(
                    'KJR Einrichtung Sign: Ablehnung (Anfrage %s) an Buchung %s nicht '
                    'übernommen (%s).', req.id, booking.id, type(err).__name__,
                    exc_info=_logger.isEnabledFor(logging.DEBUG))
        return res

    def cancel(self):
        ctx = self.env.context
        to_note = []
        note = False
        if not (ctx.get('kjr_facility_sign_refusing') or ctx.get('kjr_facility_sign_no_note')):
            reason = ctx.get('kjr_facility_sign_cancel_reason')
            # Zuordnung VOR super(): danach ist die Anfrage storniert.
            for req in self.filtered(lambda r: r.state not in ('signed', 'canceled')):
                if reason == 'orphan':
                    booking = req._kjr_facility_reference_booking()
                else:
                    booking = req._kjr_facility_booking()
                if booking:
                    to_note.append(req._kjr_facility_as_sender(booking))
            note = self._kjr_facility_cancel_note(reason)
        res = super().cancel()
        for booking in to_note:
            savepoint = self.env.cr.savepoint()
            try:
                with savepoint:
                    booking.message_post(body=Markup('<p>%s</p>') % note,
                                         subtype_xmlid='mail.mt_note')
            except Exception as err:  # noqa: BLE001 - der Storno hat Vorrang
                _logger.warning(
                    'KJR Einrichtung Sign: Storno-Notiz an Buchung %s fehlgeschlagen (%s).',
                    booking.id, type(err).__name__)
        return res

    def write(self, vals):
        # Ablauf erkennen: _cron_reminder setzt ``request.state = 'expired'``,
        # sign.request.write setzt state='expired' bei validity in der
        # Vergangenheit (dieser Teil läuft in super(), daher Prüfung des
        # Ergebnisses statt der vals). Nur der Übergang sent -> expired zählt.
        watch = self.browse()
        if 'state' in vals or 'validity' in vals:
            watch = self.filtered(lambda r: r.state == 'sent')
        res = super().write(vals)
        for req in watch.filtered(lambda r: r.state == 'expired'):
            booking = req._kjr_facility_booking()
            if not booking or booking.state == 'cancelled' or booking.contract_signed:
                continue
            savepoint = self.env.cr.savepoint()
            try:
                with savepoint:
                    req._kjr_facility_as_sender(booking)._kjr_sign_notify_problem('expired')
            except Exception as err:  # noqa: BLE001 - der Ablauf hat Vorrang
                _logger.warning(
                    'KJR Einrichtung Sign: Ablauf (Anfrage %s) an Buchung %s nicht übernommen (%s).',
                    req.id, booking.id, type(err).__name__)
        return res
