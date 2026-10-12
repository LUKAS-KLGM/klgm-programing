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

from odoo import Command, api, fields, models, _

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


def _kjr_send_template(record, xmlid, email_values=None, sudo=False, detach=False):
    """Versendet eine Mail-Vorlage für genau EINEN Datensatz.

    Bewusst defensiv: ein fehlgeschlagener Mailversand darf weder den Cron noch
    eine Sachbearbeiter-Aktion abbrechen (gleiches Muster wie
    ``kjr_facility.kjr.facility.booking._send_template``).

    :param sudo: Vorlage als Superuser rendern. Nötig für Vorlagen, die
        feldgeschützte Felder ausgeben (Einwilligungs-Erinnerung:
        ``kjr_consent_action_url`` mit ``groups=KJR_SENSITIVE_DATA_GROUP``).
        Ohne sudo liefe das Rendern für Cron, Administration und Benutzer ohne
        diese Gruppe in einen AccessError. Die Erhöhung betrifft nur das
        Rendern, das Feld bleibt per RPC geschützt.
    :param detach: die erzeugte Mail OHNE Bezug zum Datensatz ablegen
        (``model``/``res_id`` leer). Nötig, wenn der gerenderte Text einen
        Bearer-Link enthält (Signierlink der Einwilligung): send_mail legt ein
        mail.mail samt mail.message mit dem vollständigen Text an. Mit Bezug
        zur Anmeldung wäre diese Nachricht bis zum Versand (bei Fehlversand
        dauerhaft, auto_delete greift nur nach Erfolg) für jede Person per RPC
        lesbar, die die Anmeldung lesen darf, auch ohne die Gruppe, die das
        Feld selbst schützt. Ohne Bezug lesen sie nur Verfasser/in,
        erzeugende/r Benutzer/in und Administration
        (mail.message._get_forbidden_access). Es gibt dann bewusst keinen
        Rückfallversuch ohne email_values, der den Bezug wiederherstellen würde.
        Bei Anmeldungen bekommt die mail.mail stattdessen die technische
        Kennung ``kjr_detached_registration_id`` (nur Administration lesbar),
        damit die DSGVO-Anonymisierung nicht versendete oder fehlgeschlagene
        Mails wiederfindet und löscht.

        Außerdem geht eine abgekoppelte Mail AUSSCHLIESSLICH an das
        ``email_to`` aus ``email_values``; ohne diesen Empfänger wird nicht
        versendet. Grund: ``mail.template.use_default_to`` ist in Odoo 19
        standardmäßig True. Dann ermittelt send_mail die Standard-Empfänger
        des Datensatzes (``_message_get_default_recipients``), bei Anmeldungen
        mit passender Partner-Adresse also ``partner_ids=[partner_id]``, und
        legt daraus ``recipient_ids`` an (mail/models/mail_template.py,
        send_mail). ``email_values`` wird erst danach eingemischt und ersetzt
        nur die übergebenen Schlüssel. Ohne das Leeren von ``recipient_ids``,
        ``partner_ids`` und ``email_cc`` ginge der Bearer-Link zusätzlich an
        den Kontakt der Anmeldung (etwa die oder den Jugendlichen selbst), der
        die Einwilligung dann für sich unterschreiben könnte; ``partner_ids``
        gäbe dem Kontakt zudem Lesezugriff auf die gespeicherte Nachricht.

    Protokolliert werden nur Vorlage und Datensatz-ID, keine Namen oder
    Adressen (das Protokoll ist selbst ein Speicherort).
    """
    record.ensure_one()
    template = record.env.ref(xmlid, raise_if_not_found=False)
    if not template:
        _logger.warning('Mail-Vorlage %s nicht gefunden, kein Versand für %s %s.',
                        xmlid, record._name, record.id)
        return False
    if sudo:
        template = template.sudo()
    attempts = []
    if detach:
        if not (email_values or {}).get('email_to'):
            # Ohne ausdrücklichen Empfänger kein Versand: der Rückfall auf die
            # Standard-Empfänger des Datensatzes ist hier gerade unerwünscht.
            _logger.warning('Mail-Vorlage %s: kein ausdrücklicher Empfänger, kein '
                            'Versand für %s %s.', xmlid, record._name, record.id)
            return False
        detached_values = dict(
            email_values, model=False, res_id=False,
            # Standard-Empfänger der Vorlage verwerfen (Begründung im Docstring).
            recipient_ids=[Command.clear()], partner_ids=[Command.clear()],
            email_cc=False)
        if record._name == 'event.registration':
            # Auffindbare Kennung ohne Personendaten für die Anonymisierung
            # (models/mail_mail.py, event.event._kjr_purge_registration_copies).
            detached_values['kjr_detached_registration_id'] = record.id
        attempts.append({'force_send': False, 'email_values': detached_values})
    else:
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
    _logger.warning('Mailversand %s für %s %s fehlgeschlagen (%s).',
                    xmlid, record._name, record.id, type(last_error).__name__)
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
            extra_domain=self._kjr_consent_reminder_domain())
        sent = 0
        for reg in regs:
            if not reg._kjr_consent_reminder_allowed():
                # Sicherheitsnetz zur Domain: zurückgestellte Anfrage
                # (abgebrochener Warenkorb), kein Kontakt zu den Eltern.
                continue
            # Empfänger: E-Mail der Erziehungsberechtigten, sonst die der
            # Anmeldung (siehe _kjr_consent_recipient_email). Gerendert wird mit
            # sudo, weil die Vorlage den feldgeschützten Signierlink ausgibt.
            # detach: die Mail enthält den Signierlink (Bearer-Link) und wird
            # deshalb ohne Bezug zur Anmeldung abgelegt (_kjr_send_template).
            if _kjr_send_template(reg, 'kjr_event.mail_template_consent_reminder',
                                  reg._kjr_consent_email_values(), sudo=True,
                                  detach=True):
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
        # Gesperrte Anmeldungen (Einwilligung ausstehend) sind nicht bestätigt
        # und bekommen keine Packliste.
        regs = self._kjr_due_registrations(
            lead, 'kjr_packing_list_sent',
            extra_domain=[('kjr_consent_hold', '=', False)])
        sent = 0
        for reg in regs:
            if _kjr_send_template(reg, 'kjr_event.mail_template_packing_list'):
                reg._kjr_mark_sent('kjr_packing_list_sent', 'kjr_packing_list_date')
                sent += 1
        _logger.info('KJR Packliste: %d von %d fälligen Anmeldungen angeschrieben.',
                     sent, len(regs))
        return sent

    @api.model
    def _kjr_consent_reminder_domain(self):
        """Zusatzdomain für die fällige Einwilligungs-Erinnerung.

        kjr_event_shop ergänzt den Ausschluss gesperrter Anmeldungen, deren
        Auftrag noch ein Warenkorb ist (siehe _kjr_consent_reminder_allowed).
        Als Domain, damit solche Anmeldungen nicht bei jedem Lauf das
        Kontingent (``kjr_event.automation_batch_limit``) belegen.
        """
        return [('consent_missing', '=', True)]

    def _kjr_consent_reminder_allowed(self):
        """True, wenn die Einwilligungs-Erinnerung an diese Anmeldung gehen darf.

        Nicht bei gesperrten Anmeldungen mit zurückgestellter Anfrage
        (``_kjr_consent_defer_request``, in kjr_event_shop: Auftrag ist noch ein
        Warenkorb). Abgebrochene Warenkörbe sollen keinen Kontakt zu den
        Erziehungsberechtigten auslösen (Spezifikation E11); die Anfrage folgt
        erst mit dem Abschluss der Bestellung.
        """
        self.ensure_one()
        return not (self.kjr_consent_hold and self._kjr_consent_defer_request())

    # ------------------------------------------------------------------
    # E7 – Manuelle Auslöser (Server-Actions, Listen-/Formularauswahl)
    # ------------------------------------------------------------------
    def _kjr_consent_email_values(self):
        """``email_values`` für die Einwilligungs-Erinnerung (Empfänger) oder None."""
        self.ensure_one()
        recipient = self._kjr_consent_recipient_email()
        return {'email_to': recipient} if recipient else None

    def _kjr_send_to_selection(self, xmlid, flag_field=None, date_field=None,
                               recipient_getter=None, sudo=False, detach=False):
        """Versendet eine Vorlage an die ausgewählten Anmeldungen.

        Manuelle Aktionen werden bewusst NICHT über den Merker blockiert – ein
        erneuter Versand ist eine bewusste Entscheidung der Geschäftsstelle.
        Ohne Empfängeradresse wird übersprungen und gezählt.

        :param recipient_getter: optionale Funktion ``reg -> Adresse oder False``.
            Ist sie gesetzt, bestimmt sie den Empfänger (``email_to``) statt der
            Adresse aus der Vorlage; ohne Adresse wird übersprungen.
        :param sudo: Vorlage als Superuser rendern (siehe _kjr_send_template).
        :param detach: Mail ohne Bezug zum Datensatz ablegen (siehe
            _kjr_send_template).

        Rückgabe: (tatsächlich versendete Anmeldungen, Anzahl ohne Adresse).
        """
        sent = self.browse()
        no_mail = 0
        for reg in self:
            email_values = None
            if recipient_getter:
                recipient = recipient_getter(reg)
                if not recipient:
                    no_mail += 1
                    continue
                email_values = {'email_to': recipient}
            elif not (reg.email or reg.partner_id.email):
                no_mail += 1
                continue
            if _kjr_send_template(reg, xmlid, email_values, sudo=sudo, detach=detach):
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
        """E7: Anmeldebestätigung an die Auswahl senden.

        Gesperrte Anmeldungen (Einwilligung ausstehend) sind nicht bestätigt und
        werden übersprungen; die Meldung nennt ihre Anzahl.
        """
        held = self.filtered('kjr_consent_hold')
        sent, no_mail = (self - held)._kjr_send_to_selection(
            'kjr_event.mail_template_registration_confirm')
        result = self._kjr_send_result_notification(_('Anmeldebestätigung'), sent, no_mail)
        if held:
            result['params']['message'] += '\n' + _(
                '%s Anmeldung(en) wartet/warten auf die Einwilligung und wurden '
                'übersprungen.', len(held))
            result['params']['type'] = 'warning'
        return result

    def action_kjr_send_consent_reminder(self):
        """E7: Einwilligungs-Erinnerung manuell senden (ergänzt den Cron).

        Empfänger und Rendern wie im Cron: Adresse der Erziehungsberechtigten,
        Vorlage mit sudo (Signierlink ist feldgeschützt), Mail ohne Bezug zur
        Anmeldung abgelegt (Signierlink im gespeicherten Text).

        Gesperrte Anmeldungen mit zurückgestellter Anfrage (Auftrag noch
        Warenkorb, siehe _kjr_consent_reminder_allowed) werden wie im Cron
        übersprungen; die Meldung nennt ihre Anzahl.
        """
        deferred = self.filtered(lambda reg: not reg._kjr_consent_reminder_allowed())
        sent, no_mail = (self - deferred)._kjr_send_to_selection(
            'kjr_event.mail_template_consent_reminder',
            'kjr_consent_reminder_sent', 'kjr_consent_reminder_date',
            recipient_getter=lambda reg: reg._kjr_consent_recipient_email(),
            sudo=True, detach=True)
        result = self._kjr_send_result_notification(
            _('Einwilligungs-Erinnerung'), sent, no_mail)
        if deferred:
            result['params']['message'] += '\n' + _(
                '%(count)s Anmeldung(en) mit noch nicht abgeschlossener Bestellung '
                '(Warenkorb) übersprungen.', count=len(deferred))
            result['params']['type'] = 'warning'
        return result

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
    def _kjr_create_training_invoices(self, allow_send=True, allow_post=True):
        """Kern der Rechnungserzeugung: filtern, erzeugen, optional buchen.

        Herausgehoben aus ``action_kjr_create_training_invoices``, damit die
        automatische Erzeugung bei Bestätigung einer Anmeldung
        (``event.registration._kjr_auto_invoice``) GENAU DIESE Logik benutzt und
        keine zweite Fassung entsteht. Die Handaktion verhält sich unverändert.

        Buchen und Versenden sind optional und laufen über Systemparameter –
        gleiches Muster wie ``kjr_facility.invoice_auto_post`` (Default: NICHT
        buchen, das Buchen bleibt eine bewusste Entscheidung der
        Geschäftsstelle).

        :param allow_send: Wenn False, wird der Auto-Versand
            (``kjr_event.invoice_auto_send``) NICHT ausgewertet. Das braucht der
            Automatikpfad: wer den Versand-Parameter eingeschaltet hat, soll
            durch die neue Automatik nicht plötzlich Rechnungsmails verschicken,
            die er nie beauftragt hat. Erzeugen und Versenden bleiben getrennt.
        :param allow_post: Wenn False, wird das Auto-Buchen
            (``kjr_event.invoice_auto_post``) NICHT ausgewertet. Aus demselben
            Grund wie beim Versand, nur mit härterer Folge: eine gebuchte
            Rechnung trägt eine Nummer aus der Rechnungssequenz, ist nicht mehr
            löschbar und nur noch über eine Gutschrift zurückzudrehen. Der
            Automatikpfad ruft deshalb mit ``allow_post=False`` auf und erzeugt
            ausschließlich Entwürfe - genau das, was der Schalter "Rechnung
            automatisch erzeugen" zusagt. Beide Parameter gelten damit nur für
            die von Hand ausgelöste Sammelaktion.

        Anmeldungen, denen etwas fehlt (kein Schulungsprodukt, kein Kontakt),
        brechen die Verarbeitung NICHT ab: sie werden übersprungen und
        erhalten einen Hinweis im Chatter (Projektstandard: im Backend nur
        Hinweise, harte Pflichten nur im Website-Formular).

        Gesperrte Anmeldungen (``kjr_consent_hold``, Einwilligung ausstehend)
        werden übersprungen und gezählt (``skipped_hold``): sie sind nicht
        bestätigt, also keine Rechnung und keine Anmeldebestätigung, die
        action_create_training_invoice sonst mitverschickt. Die Rechnung folgt
        mit der Freigabe (_kjr_auto_invoice bzw. erneuter Handaktion).

        :return: Tupel ``(neu verknüpfte Rechnungen, Kennzahlen-dict)``.
        """
        candidates = self.browse()
        skipped_hold = 0
        skipped_not_required = 0
        skipped_already = 0
        skipped_sale = 0
        skipped_product = self.browse()
        skipped_partner = self.browse()
        for reg in self:
            if reg.kjr_consent_hold:
                skipped_hold += 1
                continue
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

        # Auto-Buchen nur auf dem bewusst ausgelösten Weg (Handaktion), siehe
        # Docstring zu allow_post. Der Automatikpfad ruft mit allow_post=False.
        posted = 0
        if allow_post and new_moves and self._kjr_param_bool(PARAM_INVOICE_AUTO_POST, False):
            for move in new_moves.filtered(lambda m: m.state == 'draft'):
                try:
                    move.action_post()
                    posted += 1
                except Exception as e:  # noqa: BLE001 - Buchen darf den Ablauf nicht abbrechen
                    _logger.warning('Auto-Buchen der Rechnung %s fehlgeschlagen: %s',
                                    move.name or move.id, e)
        # Auto-Versand nur auf dem bewusst ausgelösten Weg (Handaktion). Der
        # Automatikpfad ruft mit allow_send=False auf, siehe Docstring.
        if allow_send and candidates and self._kjr_param_bool(PARAM_INVOICE_AUTO_SEND, False):
            candidates.action_kjr_send_training_invoice()

        _logger.info(
            'KJR Sammelrechnung: %d erzeugt, %d gebucht, übersprungen: %d Einwilligung '
            'ausstehend, %d ohne Zahlungspflicht, %d bereits fakturiert, %d über '
            'Verkaufsauftrag, %d ohne Produkt, %d ohne Kontakt.',
            len(new_moves), posted, skipped_hold, skipped_not_required, skipped_already,
            skipped_sale, len(skipped_product), len(skipped_partner))

        return new_moves, {
            'created': len(new_moves),
            'posted': posted,
            'skipped_hold': skipped_hold,
            'skipped_not_required': skipped_not_required,
            'skipped_already': skipped_already,
            'skipped_sale': skipped_sale,
            'skipped_product': len(skipped_product),
            'skipped_partner': len(skipped_partner),
        }

    def action_kjr_create_training_invoices(self):
        """Erzeugt Schulungsrechnungen für mehrere Anmeldungen auf einmal.

        Reine Oberflächenaktion: die Arbeit macht
        :meth:`_kjr_create_training_invoices`. Verhalten unverändert gegenüber
        19.0.5.6.1 (einschließlich Auto-Buchen und Auto-Versand nach
        Systemparameter). Neu (19.0.5.9.0): gesperrte Anmeldungen (Einwilligung
        ausstehend) bleiben ohne Rechnung; die Meldung nennt ihre Anzahl.
        """
        _moves, stats = self._kjr_create_training_invoices(allow_send=True, allow_post=True)
        invoices = self.mapped('kjr_training_invoice_id')
        hold_message = _(
            '%(count)s Anmeldung(en) wartet/warten auf die Einwilligung der '
            'Erziehungsberechtigten und wurden übersprungen.',
            count=stats.get('skipped_hold', 0))
        if not invoices:
            message = _('Für die Auswahl konnte keine Rechnung erzeugt werden. '
                        'Hinweise stehen im Chatter der betroffenen Anmeldungen.')
            if stats.get('skipped_hold'):
                message += '\n' + hold_message
            return self._kjr_notification(
                _('Schulungsrechnung'), message, notif_type='warning')
        window = {
            'type': 'ir.actions.act_window',
            'name': _('Rechnungen'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', invoices.ids)],
        }
        if stats.get('skipped_hold'):
            # Hinweis zeigen und danach die Rechnungen öffnen ('next', wie in
            # mail/wizard/mail_template_reset.py).
            result = self._kjr_notification(
                _('Schulungsrechnung'), hold_message, notif_type='warning')
            result['params']['next'] = window
            return result
        return window

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
            details.append(_('%(count)s Rechnung(en) im Entwurf: bitte zuerst buchen.',
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
