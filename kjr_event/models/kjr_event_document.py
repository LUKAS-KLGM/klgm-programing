# -*- coding: utf-8 -*-
"""E11: Dokumente (z. B. PDF-Merkblätter/Hinweise) zu einer Veranstaltung.

Mehrere Dateien pro Veranstaltung, anzeigbar auf der Website als optionaler
Sidebar-Block (siehe ``views/website_event_templates.xml``).

E7/E9 (Automatisierung): Zusätzlich liegen in dieser Datei die Auslöser für die
Mail-Vorlagen aus ``data/mail_templates.xml`` (Erinnerung, Packliste, Absage,
Anmeldebestätigung) sowie die Sammel-/Versandaktionen rund um die
Schulungsrechnung. Sie stehen bewusst hier und nicht in
``models/event_registration.py``: dort liegen die fachlichen Stammfelder der
Anmeldung, hier die reine Ablaufsteuerung (Cron, Merker, Aktionen). Ein zweites
``_inherit``-Modell im selben Modul ist in Odoo zulässig.
"""
import base64
import logging
from datetime import timedelta
from urllib.parse import quote

from markupsafe import Markup

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Systemparameter (Defaults siehe data/ir_config_parameter_data.xml).
# Alle Werte sind bewusst konservativ: Vorlauf 0 = Automatik AUS, kein
# Auto-Buchen, kein Auto-Versand. Die Geschäftsstelle schaltet frei.
# --------------------------------------------------------------------------
PARAM_CONSENT_LEAD = 'kjr_event.consent_reminder_lead_days'
PARAM_PACKING_LEAD = 'kjr_event.packing_list_lead_days'
PARAM_ACTIVE_FROM = 'kjr_event.automation_active_from'
PARAM_BATCH_LIMIT = 'kjr_event.automation_batch_limit'
PARAM_INVOICE_AUTO_POST = 'kjr_event.invoice_auto_post'
PARAM_INVOICE_AUTO_SEND = 'kjr_event.invoice_auto_send'

# Technische Obergrenze je Cron-Lauf (kein fachlicher Wert, nur Schutz vor
# Massenversand). Über PARAM_BATCH_LIMIT pflegbar.
DEFAULT_BATCH_LIMIT = 50

TRUE_VALUES = ('1', 'true', 'yes', 'ja', 'on', 'wahr')


def _kjr_send_template(record, xmlid, email_values=None):
    """Versendet eine Mail-Vorlage für genau EINEN Datensatz.

    Bewusst defensiv: ein fehlgeschlagener Mailversand darf weder den Cron noch
    eine Sachbearbeiter-Aktion abbrechen (gleiches Muster wie
    ``kjr_facility.kjr.facility.booking._send_template``).
    """
    record.ensure_one()
    template = record.env.ref(xmlid, raise_if_not_found=False)
    if not template:
        _logger.warning('Mail-Vorlage %s nicht gefunden – kein Versand für %s.',
                        xmlid, record.display_name)
        return False
    attempts = []
    if email_values:
        attempts.append({'force_send': False, 'email_values': email_values})
    attempts.append({'force_send': False})
    last_error = None
    for kwargs in attempts:
        try:
            template.send_mail(record.id, **kwargs)
            return True
        except TypeError as e:
            # Signaturabweichung (z. B. email_values nicht unterstützt):
            # ohne die Zusatzwerte erneut versuchen, statt gar nicht zu senden.
            last_error = e
            continue
        except Exception as e:  # noqa: BLE001 - Mailversand darf den Workflow nicht blockieren
            last_error = e
            break
    _logger.warning('Mailversand %s für %s fehlgeschlagen: %s',
                    xmlid, record.display_name, last_error)
    return False


class KjrEventDocument(models.Model):
    _name = 'kjr.event.document'
    _description = 'KJR Veranstaltungsdokument'
    _order = 'sequence, id'

    name = fields.Char(string='Bezeichnung', required=True)
    sequence = fields.Integer(string='Reihenfolge', default=10)
    event_id = fields.Many2one(
        'event.event', string='Veranstaltung', required=True, ondelete='cascade', index=True,
    )
    datas = fields.Binary(string='Datei', required=True)
    datas_fname = fields.Char(string='Dateiname')
    download_url = fields.Char(string='Download-URL', compute='_compute_download_url')

    # 'name' dient als Fallback für den Dateinamen und gehört deshalb ebenfalls
    # in die Abhängigkeiten — sonst bleibt die URL nach einer Umbenennung stehen.
    @api.depends('datas_fname', 'name')
    def _compute_download_url(self):
        for doc in self:
            if not doc.id:
                doc.download_url = False
                continue
            filename = quote(doc.datas_fname or doc.name or 'dokument')
            doc.download_url = f'/web/content/kjr.event.document/{doc.id}/datas/{filename}?download=true'


class EventRegistrationAutomation(models.Model):
    """E7/E9 – Auslöser für die Mail-Vorlagen und die Schulungsrechnung."""
    _inherit = 'event.registration'

    # ------------------------------------------------------------------
    # Merker-Felder: verhindern doppelten Versand durch den Cron.
    # readonly=True ist in Odoo 19 nur eine UI-Eigenschaft; ein Schutz gegen
    # RPC ist hier fachlich nicht nötig (Merker, keine Rechtsfolge) – die
    # Geschäftsstelle darf einen Merker bewusst zurücksetzen, um erneut zu
    # senden. copy=False, damit Duplikate wieder als "nicht versendet" gelten.
    # ------------------------------------------------------------------
    kjr_consent_reminder_sent = fields.Boolean(
        string='Einwilligungs-Erinnerung versendet', readonly=True, copy=False,
        help='Wird vom Cron gesetzt, sobald die Erinnerung zur fehlenden Einwilligung '
             'verschickt wurde. Zurücksetzen führt zu einem erneuten Versand.')
    kjr_consent_reminder_date = fields.Datetime(
        string='Einwilligungs-Erinnerung am', readonly=True, copy=False)
    kjr_packing_list_sent = fields.Boolean(
        string='Packliste versendet', readonly=True, copy=False,
        help='Wird vom Cron gesetzt, sobald die Packliste verschickt wurde. '
             'Zurücksetzen führt zu einem erneuten Versand.')
    kjr_packing_list_date = fields.Datetime(
        string='Packliste am', readonly=True, copy=False)
    kjr_cancellation_sent = fields.Boolean(
        string='Absage versendet', readonly=True, copy=False)
    kjr_cancellation_date = fields.Datetime(
        string='Absage am', readonly=True, copy=False)
    kjr_invoice_mail_sent = fields.Boolean(
        string='Rechnung versendet', readonly=True, copy=False)
    kjr_invoice_mail_date = fields.Datetime(
        string='Rechnung versendet am', readonly=True, copy=False)

    # ------------------------------------------------------------------
    # Systemparameter-Helfer
    # ------------------------------------------------------------------
    @api.model
    def _kjr_params(self):
        return self.env['ir.config_parameter'].sudo()

    @api.model
    def _kjr_param_int(self, key, default=0):
        raw = self._kjr_params().get_param(key)
        if raw in (None, False, ''):
            return default
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            _logger.warning('Systemparameter %s ist keine ganze Zahl (%r) – es gilt %s.',
                            key, raw, default)
            return default

    @api.model
    def _kjr_param_bool(self, key, default=False):
        raw = self._kjr_params().get_param(key)
        if raw in (None, False, ''):
            return default
        return str(raw).strip().lower() in TRUE_VALUES

    @api.model
    def _kjr_automation_active_from(self):
        """Sicherung gegen Massenversand an Bestandsveranstaltungen.

        Beim ersten Lauf einer aktivierten Automatik wird der Zeitpunkt in
        ``kjr_event.automation_active_from`` festgeschrieben. Berücksichtigt
        werden danach ausschließlich Veranstaltungen, die NACH diesem Zeitpunkt
        angelegt wurden. Ein Cron, der beim ersten Lauf sämtliche
        Bestandsveranstaltungen anschreibt, ist damit ausgeschlossen.

        Der Administrator kann den Parameter bewusst auf ein früheres Datum
        setzen, wenn Altbestände doch einbezogen werden sollen.
        """
        params = self._kjr_params()
        raw = params.get_param(PARAM_ACTIVE_FROM)
        if raw in (None, False, ''):
            now = fields.Datetime.now()
            params.set_param(PARAM_ACTIVE_FROM, fields.Datetime.to_string(now))
            _logger.info(
                'KJR-Veranstaltungsautomatik aktiviert: es werden nur Veranstaltungen '
                'berücksichtigt, die nach %s angelegt wurden (%s).', now, PARAM_ACTIVE_FROM)
            return now
        try:
            active_from = fields.Datetime.to_datetime(raw)
        except (TypeError, ValueError):
            active_from = False
        if not active_from:
            _logger.warning(
                'Systemparameter %s enthält kein gültiges Datum (%r) – Automatik pausiert.',
                PARAM_ACTIVE_FROM, raw)
            return False
        return active_from

    # ------------------------------------------------------------------
    # Gemeinsame Auswahl für die zeitgesteuerten Vorlagen
    # ------------------------------------------------------------------
    @api.model
    def _kjr_due_registrations(self, lead_days, flag_field, extra_domain=None):
        """Anmeldungen, deren Veranstaltung in den nächsten ``lead_days`` beginnt."""
        active_from = self._kjr_automation_active_from()
        if not active_from:
            return self.browse()
        now = fields.Datetime.now()
        domain = [
            ('state', 'not in', ('cancel', 'done')),
            (flag_field, '=', False),
            ('event_id.is_kjr', '=', True),
            ('event_id.date_begin', '>=', now),
            ('event_id.date_begin', '<=', now + timedelta(days=lead_days)),
            # Sicherung: nur Veranstaltungen ab dem Aktivierungszeitpunkt.
            ('event_id.create_date', '>=', active_from),
            # Ohne Empfänger kein Versand – sonst blockieren solche Anmeldungen
            # bei jedem Lauf erneut das Kontingent.
            '|', ('email', '!=', False), ('partner_id.email', '!=', False),
        ]
        if extra_domain:
            domain += extra_domain
        limit = self._kjr_param_int(PARAM_BATCH_LIMIT, DEFAULT_BATCH_LIMIT)
        if limit <= 0:
            limit = DEFAULT_BATCH_LIMIT
        return self.search(domain, limit=limit, order='id')

    def _kjr_mark_sent(self, flag_field, date_field):
        if self:
            self.write({flag_field: True, date_field: fields.Datetime.now()})

    @api.model
    def _kjr_notification(self, title, message, notif_type='info'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notif_type,
                'sticky': False,
            },
        }

    # ------------------------------------------------------------------
    # E7 – Cron: Einwilligungs-Erinnerung
    # ------------------------------------------------------------------
    @api.model
    def _cron_kjr_consent_reminder(self):
        """Erinnert an fehlende Einwilligungen, sobald der Beginn näher rückt.

        Der Vorlauf steht in ``kjr_event.consent_reminder_lead_days``.
        TODO(KJR): Der fachliche Vorlauf (wie viele Tage vor Beginn erinnert
        werden soll) ist mit der Geschäftsstelle abzustimmen; Default 0 = AUS,
        damit ohne Freigabe nichts hinausgeht.
        """
        lead = self._kjr_param_int(PARAM_CONSENT_LEAD, 0)
        if lead <= 0:
            _logger.info('KJR Einwilligungs-Erinnerung deaktiviert (%s = %s).',
                         PARAM_CONSENT_LEAD, lead)
            return 0
        regs = self._kjr_due_registrations(
            lead, 'kjr_consent_reminder_sent',
            extra_domain=[('consent_missing', '=', True)])
        sent = 0
        for reg in regs:
            if _kjr_send_template(reg, 'kjr_event.mail_template_consent_reminder'):
                reg._kjr_mark_sent('kjr_consent_reminder_sent', 'kjr_consent_reminder_date')
                sent += 1
        _logger.info('KJR Einwilligungs-Erinnerung: %d von %d fälligen Anmeldungen angeschrieben.',
                     sent, len(regs))
        return sent

    # ------------------------------------------------------------------
    # E7 – Cron: Packliste
    # ------------------------------------------------------------------
    @api.model
    def _cron_kjr_packing_list(self):
        """Versendet die Packliste vor der Anreise.

        Der Vorlauf steht in ``kjr_event.packing_list_lead_days``.
        TODO(KJR): Vorlauf fachlich festlegen; Default 0 = AUS.
        """
        lead = self._kjr_param_int(PARAM_PACKING_LEAD, 0)
        if lead <= 0:
            _logger.info('KJR Packlisten-Versand deaktiviert (%s = %s).',
                         PARAM_PACKING_LEAD, lead)
            return 0
        regs = self._kjr_due_registrations(lead, 'kjr_packing_list_sent')
        sent = 0
        for reg in regs:
            if _kjr_send_template(reg, 'kjr_event.mail_template_packing_list'):
                reg._kjr_mark_sent('kjr_packing_list_sent', 'kjr_packing_list_date')
                sent += 1
        _logger.info('KJR Packliste: %d von %d fälligen Anmeldungen angeschrieben.',
                     sent, len(regs))
        return sent

    # ------------------------------------------------------------------
    # E7 – Manuelle Auslöser (Server-Actions, Listen-/Formularauswahl)
    # ------------------------------------------------------------------
    def _kjr_send_to_selection(self, xmlid, flag_field=None, date_field=None):
        """Versendet eine Vorlage an die ausgewählten Anmeldungen.

        Manuelle Aktionen werden bewusst NICHT über den Merker blockiert – ein
        erneuter Versand ist eine bewusste Entscheidung der Geschäftsstelle.
        Ohne Empfängeradresse wird übersprungen und gezählt.

        Rückgabe: (tatsächlich versendete Anmeldungen, Anzahl ohne Adresse).
        """
        sent = self.browse()
        no_mail = 0
        for reg in self:
            if not (reg.email or reg.partner_id.email):
                no_mail += 1
                continue
            if _kjr_send_template(reg, xmlid):
                sent |= reg
                if flag_field and date_field:
                    reg._kjr_mark_sent(flag_field, date_field)
        return sent, no_mail

    def _kjr_send_result_notification(self, title, sent, no_mail):
        message = _('%(sent)s E-Mail(s) in die Warteschlange gestellt.', sent=len(sent))
        if no_mail:
            message += '\n' + _(
                '%(count)s Anmeldung(en) ohne E-Mail-Adresse übersprungen.', count=no_mail)
        return self._kjr_notification(
            title, message, notif_type='warning' if no_mail else 'success')

    def action_kjr_send_registration_confirm(self):
        """E7: Anmeldebestätigung an die Auswahl senden."""
        sent, no_mail = self._kjr_send_to_selection(
            'kjr_event.mail_template_registration_confirm')
        return self._kjr_send_result_notification(_('Anmeldebestätigung'), sent, no_mail)

    def action_kjr_send_consent_reminder(self):
        """E7: Einwilligungs-Erinnerung manuell senden (ergänzt den Cron)."""
        sent, no_mail = self._kjr_send_to_selection(
            'kjr_event.mail_template_consent_reminder',
            'kjr_consent_reminder_sent', 'kjr_consent_reminder_date')
        return self._kjr_send_result_notification(_('Einwilligungs-Erinnerung'), sent, no_mail)

    def action_kjr_send_packing_list(self):
        """E7: Packliste manuell senden (ergänzt den Cron)."""
        sent, no_mail = self._kjr_send_to_selection(
            'kjr_event.mail_template_packing_list',
            'kjr_packing_list_sent', 'kjr_packing_list_date')
        return self._kjr_send_result_notification(_('Packliste'), sent, no_mail)

    def action_kjr_send_cancellation(self):
        """E7: Absage versenden – bewusste Entscheidung der Geschäftsstelle.

        Der Anmeldestatus wird NICHT automatisch auf "Abgebrochen" gesetzt: ob
        die einzelne Anmeldung storniert oder die ganze Veranstaltung abgesagt
        wird, entscheidet die Sachbearbeitung über die Standardfunktionen.
        TODO(KJR): Falls gewünscht, kann die Aktion die Anmeldung zusätzlich
        stornieren – das ist eine offene Kundenentscheidung.
        """
        sent, no_mail = self._kjr_send_to_selection(
            'kjr_event.mail_template_cancellation',
            'kjr_cancellation_sent', 'kjr_cancellation_date')
        for reg in sent:
            reg.message_post(
                body=Markup('<p>%s</p>') % _(
                    'Absage per E-Mail an %(mail)s versendet.',
                    mail=reg.email or reg.partner_id.email or ''),
                subtype_xmlid='mail.mt_note')
        return self._kjr_send_result_notification(_('Absage'), sent, no_mail)

    # ------------------------------------------------------------------
    # E9 – Sammelaktion Schulungsrechnung (Listenauswahl)
    # ------------------------------------------------------------------
    def action_kjr_create_training_invoices(self):
        """Erzeugt Schulungsrechnungen für mehrere Anmeldungen auf einmal.

        Buchen und Versenden sind optional und laufen über Systemparameter –
        gleiches Muster wie ``kjr_facility.invoice_auto_post`` (Default: NICHT
        buchen, das Buchen bleibt eine bewusste Entscheidung der
        Geschäftsstelle).

        Anmeldungen, denen etwas fehlt (kein Schulungsprodukt, kein Kontakt),
        brechen die Sammelaktion NICHT ab: sie werden übersprungen und
        erhalten einen Hinweis im Chatter (Projektstandard: im Backend nur
        Hinweise, harte Pflichten nur im Website-Formular).
        """
        candidates = self.browse()
        skipped_not_required = 0
        skipped_already = 0
        skipped_sale = 0
        skipped_product = self.browse()
        skipped_partner = self.browse()
        for reg in self:
            if not reg.event_id.payment_required:
                skipped_not_required += 1
                continue
            if reg.kjr_training_invoice_id:
                skipped_already += 1
                continue
            if 'sale_order_id' in reg._fields and reg.sale_order_id:
                # Standardweg (event_sale) hat Vorrang – siehe action_create_training_invoice.
                skipped_sale += 1
                continue
            if not reg.event_id.training_product_id:
                skipped_product |= reg
                continue
            if not reg.partner_id:
                skipped_partner |= reg
                continue
            candidates |= reg

        for reg in skipped_product:
            reg.message_post(
                body=Markup('<p>%s</p>') % _(
                    'Keine Rechnung erzeugt: für die Veranstaltung "%(event)s" ist kein '
                    'Schulungsprodukt hinterlegt.', event=reg.event_id.name or ''),
                subtype_xmlid='mail.mt_note')
        for reg in skipped_partner:
            reg.message_post(
                body=Markup('<p>%s</p>') % _(
                    'Keine Rechnung erzeugt: der Anmeldung ist kein Kontakt zugeordnet.'),
                subtype_xmlid='mail.mt_note')

        if candidates:
            # Bestehende Einzel-Logik wiederverwenden (Entwurf je Anmeldung).
            candidates.action_create_training_invoice()
        new_moves = candidates.mapped('kjr_training_invoice_id')

        posted = 0
        if new_moves and self._kjr_param_bool(PARAM_INVOICE_AUTO_POST, False):
            for move in new_moves.filtered(lambda m: m.state == 'draft'):
                try:
                    move.action_post()
                    posted += 1
                except Exception as e:  # noqa: BLE001 - Buchen darf den Ablauf nicht abbrechen
                    _logger.warning('Auto-Buchen der Rechnung %s fehlgeschlagen: %s',
                                    move.name or move.id, e)
        if candidates and self._kjr_param_bool(PARAM_INVOICE_AUTO_SEND, False):
            candidates.action_kjr_send_training_invoice()

        _logger.info(
            'KJR Sammelrechnung: %d erzeugt, %d gebucht, übersprungen: %d ohne Zahlungspflicht, '
            '%d bereits fakturiert, %d über Verkaufsauftrag, %d ohne Produkt, %d ohne Kontakt.',
            len(new_moves), posted, skipped_not_required, skipped_already, skipped_sale,
            len(skipped_product), len(skipped_partner))

        invoices = self.mapped('kjr_training_invoice_id')
        if not invoices:
            return self._kjr_notification(
                _('Schulungsrechnung'),
                _('Für die Auswahl konnte keine Rechnung erzeugt werden. '
                  'Hinweise stehen im Chatter der betroffenen Anmeldungen.'),
                notif_type='warning')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Rechnungen'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', invoices.ids)],
        }

    # ------------------------------------------------------------------
    # E9 – Rechnungsversand per Mail-Vorlage
    # ------------------------------------------------------------------
    def action_kjr_send_training_invoice(self):
        """Versendet die Schulungsrechnung als PDF per Mail-Vorlage.

        Entwürfe werden bewusst NICHT versendet: eine Rechnung ohne Nummer darf
        das Haus nicht verlassen. Sie werden übersprungen und gemeldet.
        """
        sent = 0
        drafts = 0
        missing = 0
        no_mail = 0
        for reg in self:
            move = reg.kjr_training_invoice_id
            if not move:
                missing += 1
                continue
            if move.state != 'posted':
                drafts += 1
                continue
            if not move.partner_id.email:
                no_mail += 1
                continue
            attachment = move._kjr_invoice_pdf_attachment()
            email_values = {'attachment_ids': [(6, 0, attachment.ids)]} if attachment else None
            if _kjr_send_template(move, 'kjr_event.mail_template_training_invoice', email_values):
                sent += 1
                reg._kjr_mark_sent('kjr_invoice_mail_sent', 'kjr_invoice_mail_date')
                move.message_post(
                    body=Markup('<p>%s</p>') % _(
                        'Rechnung per E-Mail an %(mail)s versendet (KJR-Veranstaltung).',
                        mail=move.partner_id.email or ''),
                    subtype_xmlid='mail.mt_note')
        message = _('%(sent)s Rechnung(en) in die Warteschlange gestellt.', sent=sent)
        details = []
        if drafts:
            details.append(_('%(count)s Rechnung(en) im Entwurf – bitte zuerst buchen.',
                             count=drafts))
        if missing:
            details.append(_('%(count)s Anmeldung(en) ohne Rechnung.', count=missing))
        if no_mail:
            details.append(_('%(count)s Rechnungsempfänger ohne E-Mail-Adresse.', count=no_mail))
        if details:
            message += '\n' + '\n'.join(details)
        return self._kjr_notification(
            _('Rechnungsversand'), message,
            notif_type='warning' if details else 'success')


class AccountMoveKjrEvent(models.Model):
    """E9 – Hilfsfunktion für den Rechnungsversand aus dem Veranstaltungsmodul."""
    _inherit = 'account.move'

    def _kjr_invoice_pdf_attachment(self):
        """Rendert das Rechnungs-PDF und legt es als Anhang an der Rechnung ab.

        Der Standard-Report wird defensiv aufgelöst (``raise_if_not_found=False``):
        fehlt er auf der Instanz, geht die Mail ohne PDF hinaus, statt den
        Versand zu verhindern.
        """
        self.ensure_one()
        Attachment = self.env['ir.attachment']
        report_xmlid = 'account.account_invoices'
        if not self.env.ref(report_xmlid, raise_if_not_found=False):
            _logger.warning('Report %s nicht gefunden – Rechnungsmail ohne PDF.', report_xmlid)
            return Attachment
        name = _('Rechnung_%s.pdf') % (self.name or str(self.id)).replace('/', '-')
        existing = Attachment.search([
            ('res_model', '=', self._name),
            ('res_id', '=', self.id),
            ('name', '=', name),
        ], limit=1)
        if existing:
            return existing
        try:
            pdf_content, _dummy = self.env['ir.actions.report']._render_qweb_pdf(
                report_xmlid, res_ids=self.ids)
        except Exception as e:  # noqa: BLE001 - fehlendes PDF darf den Versand nicht stoppen
            _logger.warning('Rechnungs-PDF für %s konnte nicht erzeugt werden: %s',
                            self.name or self.id, e)
            return Attachment
        return Attachment.create({
            'name': name,
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })
