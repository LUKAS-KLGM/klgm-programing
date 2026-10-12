# -*- coding: utf-8 -*-
"""Hooks an sign.request: Unterschrift, Ablehnung, Storno.

Alle Hooks rufen super() ZUERST auf und werfen selbst NIE: eine Unterschrift
oder Ablehnung der Eltern darf an einem Fehler auf KJR-Seite nicht scheitern.
Wirkung entfalten sie nur, wenn die Anfrage auf eine Anmeldung zeigt
(reference_doc) UND diese Anmeldung genau diese Anfrage als aktuelle führt
(``kjr_sign_request_id``). Veraltete Anfragen, etwa nach "Erneut senden",
bleiben damit ohne Wirkung.

Notiztexte beim Storno kommen NIE als Freitext aus dem Kontext: der Schlüssel
``kjr_sign_cancel_reason`` wählt nur einen festen Text aus (``_kjr_cancel_note``)
(sonst wäre per RPC beliebiger Text mit Systemrechten im Chatter der Anmeldung
eines Minderjährigen platzierbar).

Datenschutz beim Unterschreiben: Odoo Sign kopiert das unterschriebene PDF
(Name und Unterschrift der erziehungsberechtigten Person, Ort, Kindsname) als
ir.attachment an das reference_doc und hängt es an die Nachricht "fully signed".
An der Anmeldung wäre es für jede Person lesbar, die die Anmeldung lesen darf
(etwa die Registrierungstheke), und umginge den Feldschutz der
Erziehungsberechtigten-Daten in kjr_event (KJR_SENSITIVE_DATA_GROUP). Der
_sign-Hook entfernt diese Kopien deshalb wieder. Den Nachweis hält die
sign.request selbst (Smart-Button nur für Sign-Benutzer/innen).
"""
import logging

from markupsafe import Markup

from odoo import Command, _, models

_logger = logging.getLogger(__name__)


class SignRequest(models.Model):
    _inherit = 'sign.request'

    def _kjr_reference_registration(self):
        """Anmeldung aus reference_doc (sudo), auch wenn diese Anfrage nicht
        (mehr) die aktuelle ist; sonst ein leeres Recordset."""
        self.ensure_one()
        empty = self.env['event.registration'].sudo()
        doc = self.sudo().reference_doc
        if not doc or doc._name != 'event.registration':
            return empty
        return doc.sudo().exists()

    def _kjr_registration(self):
        """Zugehörige Anmeldung (sudo), nur wenn sie GENAU diese Anfrage als
        aktuelle führt; sonst ein leeres Recordset."""
        self.ensure_one()
        reg = self._kjr_reference_registration()
        if not reg or reg.kjr_sign_request_id != self:
            return self.env['event.registration'].sudo()
        return reg

    # ------------------------------------------------------------------
    # Kopien des unterschriebenen PDF an der Anmeldung entfernen
    # ------------------------------------------------------------------
    def _kjr_copy_snapshot(self):
        """Stand VOR super()._sign(): vorhandene Anhänge und letzte Nachricht
        der Anmeldung. Nur was danach entsteht, wird als Kopie behandelt.
        Wirft nie.

        :return: {sign.request.id: (Anmeldung, set(Anhang-IDs), letzte Nachricht-ID)}
        """
        snapshot = {}
        Attachment = self.env['ir.attachment'].sudo()
        Message = self.env['mail.message'].sudo()
        for req in self:
            try:
                reg = req._kjr_reference_registration()
                if not reg:
                    continue
                attachments = Attachment.search([
                    ('res_model', '=', 'event.registration'), ('res_id', '=', reg.id)])
                last_message = Message.search([
                    ('model', '=', 'event.registration'), ('res_id', '=', reg.id)],
                    order='id desc', limit=1)
                snapshot[req.id] = (reg, set(attachments.ids), last_message.id or 0)
            except Exception:  # noqa: BLE001 - die Unterschrift hat Vorrang
                _logger.exception(
                    'KJR Einwilligung: Stand der Anhänge vor der Unterschrift (Anfrage %s) '
                    'nicht ermittelbar; Kopien des PDF bleiben an der Anmeldung.', req.id)
        return snapshot

    def _kjr_remove_registration_copies(self, snapshot):
        """Entfernt die Kopien, die Odoo Sign in ``_sign`` an die Anmeldung legt.

        * ir.attachment mit res_model='event.registration' an dieser Anmeldung,
          die erst während der Unterschrift entstanden sind und den Namen eines
          fertigen Dokuments tragen: gelöscht.
        * Neue Nachrichten an der Anmeldung (u. a. "The document ... has been
          fully signed"): die Verknüpfung zu den fertigen Dokumenten der Anfrage
          wird gelöst. Die Anhänge selbst gehören der sign.request und bleiben
          dort als Nachweis erhalten.
        Wirft nie (eigener Savepoint je Anfrage).
        """
        Attachment = self.env['ir.attachment'].sudo()
        Message = self.env['mail.message'].sudo()
        for req in self:
            if req.id not in snapshot:
                continue
            reg, attachments_before, last_message_id = snapshot[req.id]
            savepoint = self.env.cr.savepoint()
            try:
                with savepoint:
                    sreq = req.sudo()
                    names = set(sreq.completed_document_ids.document_id.mapped('name'))
                    copies = Attachment.search([
                        ('res_model', '=', 'event.registration'), ('res_id', '=', reg.id),
                    ]).filtered(lambda a: a.id not in attachments_before and a.name in names)
                    signed = sreq.completed_document_attachment_ids | sreq.attachment_ids | copies
                    messages = Message.search([
                        ('model', '=', 'event.registration'), ('res_id', '=', reg.id),
                        ('id', '>', last_message_id)])
                    for message in messages:
                        linked = message.attachment_ids & signed
                        if linked:
                            message.write({'attachment_ids': [
                                Command.unlink(att.id) for att in linked]})
                    if copies:
                        copies.unlink()
            except Exception:  # noqa: BLE001 - die Unterschrift hat Vorrang
                _logger.exception(
                    'KJR Einwilligung: Kopie des unterschriebenen Dokuments (Anfrage %s) '
                    'an Anmeldung %s konnte nicht entfernt werden.', req.id, reg.id)
                reg._kjr_consent_activity(
                    _('Unterschriebenes Dokument an der Anmeldung entfernen'),
                    _('Odoo Sign hat eine Kopie der unterschriebenen Einwilligung an die '
                      'Anmeldung gehängt, die nicht automatisch entfernt werden konnte. '
                      'Bitte den Anhang an der Anmeldung löschen; der Nachweis liegt an '
                      'der Unterschriftsanfrage.'))

    def _sign(self):
        snapshot = self._kjr_copy_snapshot()
        res = super()._sign()
        self._kjr_remove_registration_copies(snapshot)
        for req in self:
            reg = req._kjr_registration()
            if not reg:
                continue
            if reg.state == 'cancel':
                # Eine abgesagte Anmeldung wird NIE über eine Unterschrift
                # reaktiviert (die Freigabe in kjr_event prüft den Status nicht).
                # Die Unterschrift bleibt an der Anfrage, die Geschäftsstelle
                # entscheidet.
                reg._kjr_consent_activity(
                    _('Einwilligung zu abgesagter Anmeldung unterschrieben'),
                    _('Die Erziehungsberechtigten haben unterschrieben, die Anmeldung ist '
                      'aber abgesagt. Sie bleibt abgesagt. Bitte Kontakt aufnehmen und '
                      'gegebenenfalls neu anmelden.'))
                continue
            if not reg.active:
                # Archiviert gilt wie abgesagt: keine Freigabe (kjr_event prüft
                # ``active`` nicht und erzeugte sonst eine Entwurfsrechnung).
                reg._kjr_consent_activity(
                    _('Einwilligung zu archivierter Anmeldung unterschrieben'),
                    _('Die Erziehungsberechtigten haben unterschrieben, die Anmeldung ist '
                      'aber archiviert. Sie bleibt archiviert und gesperrt. Bitte Kontakt '
                      'aufnehmen und gegebenenfalls neu anmelden.'))
                continue
            # Savepoint bewusst außerhalb des try (siehe kjr_event,
            # _kjr_auto_invoice): scheitert schon der Flush, gibt es nichts
            # zurückzurollen.
            savepoint = self.env.cr.savepoint()
            try:
                with savepoint:
                    company = reg.event_id.company_id or reg.company_id or req.communication_company_id
                    # Als Ersteller der Anfrage (interner Absender) und mit der
                    # Firma der Veranstaltung, NICHT als öffentlicher Benutzer
                    # der Signierseite (E9). kjr_event gibt die Anmeldung nach
                    # dem Schreiben von parental_consent frei (Quelle 'sign').
                    writer = reg.with_user(req.create_uid).sudo()
                    if company:
                        writer = writer.with_company(company)
                    writer.with_context(kjr_consent_source='sign').write({
                        'parental_consent': True,
                        'kjr_consent_source': 'sign',
                    })
                    reg.write({'kjr_sign_followup_done': True})
            except Exception:  # noqa: BLE001 - die Unterschrift hat Vorrang
                _logger.exception(
                    'KJR Einwilligung: Übernahme der Unterschrift (Anfrage %s) in die '
                    'Anmeldung %s fehlgeschlagen.', req.id, reg.id)
                reg._kjr_consent_activity(
                    _('Einwilligung unterschrieben, Übernahme fehlgeschlagen'),
                    _('Die digitale Einwilligung liegt vor. Bitte die Anmeldung prüfen '
                      'und die Einwilligung manuell bestätigen.'))
        return res

    def _refuse(self, refuser, refusal_reason):
        # Kontext VOR super(): sign.request._refuse ruft intern cancel() auf, der
        # cancel-Hook darf dann keine zweite Notiz schreiben (E13).
        res = super(SignRequest, self.with_context(kjr_sign_refusing=True))._refuse(
            refuser, refusal_reason)
        for req in self:
            reg = req._kjr_registration()
            if not reg:
                continue
            savepoint = self.env.cr.savepoint()
            try:
                with savepoint:
                    reg.write({'kjr_sign_refused': True, 'kjr_sign_followup_done': True})
                    # Bewusst OHNE die Begründung der Eltern: sie steht an der
                    # Anfrage selbst und gehört nicht in den Chatter der Anmeldung.
                    reg.message_post(
                        body=Markup('<p>%s</p>') % _('Unterschrift abgelehnt.'),
                        subtype_xmlid='mail.mt_note')
                    reg._kjr_consent_activity(
                        _('Unterschrift abgelehnt'),
                        _('Die erziehungsberechtigte Person hat die Unterschrift abgelehnt. '
                          'Die Anmeldung bleibt gesperrt. Bitte Kontakt aufnehmen und '
                          'entscheiden: erneut senden, Papier-Einwilligung oder Absage.'))
            except Exception:  # noqa: BLE001
                _logger.exception(
                    'KJR Einwilligung: Ablehnung (Anfrage %s) konnte an Anmeldung %s nicht '
                    'vermerkt werden.', req.id, reg.id)
        return res

    def _kjr_cancel_note(self, reason):
        """Fester Notiztext je Storno-Grund; unbekannte Gründe ergeben den
        Standardtext. Bewusst kein Freitext aus dem Kontext."""
        if reason == 'paper':
            return _('Unterschriftsanfrage storniert: Einwilligung liegt auf Papier vor.')
        if reason == 'resend':
            return _('Unterschriftsanfrage storniert: wird neu versendet.')
        if reason == 'email':
            return _('Unterschriftsanfrage storniert: E-Mail-Adresse geändert.')
        return _('Unterschriftsanfrage storniert.')

    def cancel(self):
        # Nur Anfragen, die durch DIESEN Aufruf storniert werden (Odoo Sign
        # lässt unterschriebene aus; bereits stornierte bekommen keine zweite Notiz).
        to_note = self.filtered(lambda r: r.state not in ('signed', 'canceled'))
        res = super().cancel()
        ctx = self.env.context
        if ctx.get('kjr_sign_refusing') or ctx.get('kjr_sign_no_note'):
            return res
        note = self._kjr_cancel_note(ctx.get('kjr_sign_cancel_reason'))
        for req in to_note:
            reg = req._kjr_registration()
            if not reg:
                continue
            savepoint = self.env.cr.savepoint()
            try:
                with savepoint:
                    reg.message_post(body=Markup('<p>%s</p>') % note,
                                     subtype_xmlid='mail.mt_note')
            except Exception:  # noqa: BLE001
                _logger.exception(
                    'KJR Einwilligung: Storno-Notiz (Anfrage %s) an Anmeldung %s fehlgeschlagen.',
                    req.id, reg.id)
        return res
