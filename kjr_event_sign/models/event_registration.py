# -*- coding: utf-8 -*-
"""Anmeldung: Unterschriftsanfrage (Odoo Sign) für die Einwilligung.

Ablauf (Einzelheiten in der Spezifikation, Abschnitt 1 und 3):
* kjr_event sperrt die Online-Anmeldung Minderjähriger (``kjr_consent_hold``)
  und ruft ``_kjr_consent_request_start`` auf. Diese Brücke überschreibt die
  Methode: statt einer Aktivität entsteht eine sign.request, und Odoo Sign
  verschickt seine Standard-Mail an die Erziehungsberechtigten. super() läuft
  nur als Rückfall, wenn die Veranstaltung nicht (mehr) im Modus 'sign' ist.
* Unterschreiben die Eltern, setzt der Hook in ``sign_request._sign``
  ``parental_consent``; kjr_event gibt die Anmeldung daraufhin frei.
* Papier-Einwilligung, Absage und Löschung stornieren eine offene Anfrage.
* Ein täglicher Cron wiederholt fehlgeschlagene Versuche, legt bei Ablauf oder
  Ablehnung eine Aktivität an und storniert Anfragen ohne Anmeldung.

Datensparsamkeit: Referenz und Betreff der Anfrage tragen die Veranstaltung und
die Anmeldenummer, NIE den Namen des Kindes (unterschriebene Anfragen und
sign.log lassen sich nicht löschen). Ins Protokoll kommen nur IDs.

Vorbefüllung (19.0.1.1.0, Vorlage v2): Name des Kindes, Veranstaltung mit
Zeitraum und Name der/des Erziehungsberechtigten stehen schreibgeschützt im
Dokument. Odoo Sign füllt sie beim Anlegen der Anfrage selbst
(``sign.request._populate_constant_items``) über die Feldtypen aus
``data/sign_item_type_data.xml``; Quelle ist ``reference_doc`` (diese
Anmeldung). Diese Datei liefert dafür ``kjr_sign_event_label`` und prüft vor
dem Anlegen, dass die Vorbefüllung vollständig wäre
(``_kjr_sign_check_prefill``: Name der Eltern vorhanden und nicht der Name
des Kindes). Werte bekommt nur die eigene Anfrage der Anmeldung
(``models/sign_request_item.py``). Der Name des Kindes steht damit im Dokument,
weiterhin aber NICHT in Referenz, Betreff oder Begleittext der Mail.
"""
import logging
from datetime import timedelta

import pytz
from markupsafe import Markup

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import SQL

_logger = logging.getLogger(__name__)

PARAM_SENDER = 'kjr_event_sign.sender_user_id'
PARAM_VALIDITY_DAYS = 'kjr_event_sign.validity_days'
PARAM_REMINDER_DAYS = 'kjr_event_sign.reminder_days'
DEFAULT_VALIDITY_DAYS = 14
DEFAULT_REMINDER_DAYS = 3
# Technische Grenzen des Crons (kein fachlicher Wert)
CRON_BATCH_LIMIT = 200
MAX_ATTEMPTS = 3
# Stände, in denen bereits eine Anfrage existiert(e). Nach Ablehnung, Ablauf
# oder bewusstem Storno entscheidet die Geschäftsstelle (Spez. 1, E13); ein
# automatischer Neustart (z. B. Auftrag 'sent' -> 'sale') ist dann gesperrt.
# Nur die Schaltflächen und der Cron-Retry heben das per Kontext
# ``kjr_sign_force`` auf. 'sent' und 'signed' werden IMMER übersprungen.
SIGN_STATES_ALWAYS_SKIP = ('sent', 'signed')
SIGN_STATES_NEED_FORCE = ('refused', 'expired', 'canceled')
# Felder, deren Änderung den Empfänger der Anfrage ändern kann
# (_kjr_consent_recipient_email: guardian_email, email, partner_id.email).
RECIPIENT_FIELDS = ('guardian_email', 'email', 'partner_id')
# Felder der Anmeldung, die die Vorlage v2 schreibgeschützt in die Anfrage
# übernimmt (Name des Kindes, Name der/des Erziehungsberechtigten). Ändern sie
# sich bei offener Anfrage, stimmt das Dokument nicht mehr
# (_kjr_sign_check_prefilled). Die Veranstaltung (Name, Termine) prüft
# event.event.write.
PREFILL_FIELDS = ('name', 'guardian_name')
# auto_field des Feldtyps "Name der/des Erziehungsberechtigten"
# (data/sign_item_type_data.xml). Enthält eine Vorlage ein schreibgeschütztes
# Feld dieses Typs, ist guardian_name Pflicht für die Anfrage.
GUARDIAN_AUTO_FIELD = 'guardian_name'
# Schlüssel in cr.cache: IDs der Anmeldungen, deren Unterschriftsanfrage gerade
# in _kjr_sign_create_request angelegt wird (Freigabe der Vorbefüllung, siehe
# models/sign_request_item.py).
PREFILL_CACHE_KEY = 'kjr_event_sign_prefill_registration_ids'

SIGN_STATE_MAP = {
    'sent': 'sent',
    'shared': 'sent',
    'signed': 'signed',
    'canceled': 'canceled',
    'expired': 'expired',
}


def _norm_name(value):
    """Vergleichsform für Namen: Groß-/Kleinschreibung und Leerraum egal."""
    return ' '.join(str(value or '').split()).casefold()


class EventRegistration(models.Model):
    _inherit = 'event.registration'

    kjr_sign_request_id = fields.Many2one(
        'sign.request', string='Unterschriftsanfrage', copy=False, readonly=True,
        ondelete='set null', index='btree_not_null', groups='sign.group_sign_user')
    kjr_sign_state = fields.Selection([
        ('none', 'Keine Anfrage'),
        ('sent', 'Gesendet'),
        ('signed', 'Unterschrieben'),
        ('refused', 'Abgelehnt'),
        ('expired', 'Abgelaufen'),
        ('canceled', 'Storniert'),
    ], string='Stand Unterschrift', compute='_compute_kjr_sign_state',
        store=True, compute_sudo=True,
        help='Stand der digitalen Einwilligung (Odoo Sign) dieser Anmeldung.')
    kjr_sign_refused = fields.Boolean(
        'Unterschrift abgelehnt', copy=False, readonly=True)
    kjr_sign_error = fields.Boolean(
        'Fehler beim Versand der Unterschriftsanfrage', copy=False, readonly=True,
        help='Gesetzt, wenn die Unterschriftsanfrage nicht angelegt werden konnte. '
             'Der tägliche Lauf versucht es bis zu drei Mal erneut.')
    kjr_sign_attempts = fields.Integer(
        'Fehlversuche Unterschriftsanfrage', copy=False, readonly=True)
    kjr_sign_followup_done = fields.Boolean(
        'Nachfassen angelegt', copy=False, readonly=True,
        help='Technischer Merker: Die Aktivität zu Ablauf oder Ablehnung ist '
             'bereits angelegt.')
    kjr_sign_enabled = fields.Boolean(
        'Digitale Einwilligung aktiv', compute='_compute_kjr_sign_enabled',
        help='Technisch: Einwilligungsverfahren der Veranstaltung ist "Digitale '
             'Unterschrift". Steuert die Sichtbarkeit der Schaltflächen.')
    # Quelle des schreibgeschützten Feldes "Veranstaltung" der Vorlage v2
    # (sign.item.type kjr_event_sign.sign_item_type_kjr_event_label, auto_field).
    # Nicht gespeichert; enthält nur Name und Zeitraum der Veranstaltung, keine
    # Personendaten, deshalb ohne groups. compute_sudo, weil Odoo Sign den Wert
    # mit sudo liest und die Anzeige nicht von den Rechten an der
    # Veranstaltung abhängen soll.
    kjr_sign_event_label = fields.Char(
        'Veranstaltung (Einwilligungsformular)',
        compute='_compute_kjr_sign_event_label', compute_sudo=True,
        help='Technisch: Veranstaltung mit Zeitraum, wie sie im Einwilligungsformular '
             '(Odoo Sign) vorbefüllt wird, z. B. "Sommerfreizeit, 01.08.2027 bis '
             '07.08.2027".')

    # ------------------------------------------------------------------
    # Berechnungen
    # ------------------------------------------------------------------
    @api.depends('kjr_sign_request_id.state', 'kjr_sign_refused')
    def _compute_kjr_sign_state(self):
        for rec in self:
            req = rec.kjr_sign_request_id
            state = SIGN_STATE_MAP.get(req.state, 'none') if req else 'none'
            # Abgelehnt hat Vorrang vor Storniert: Odoo Sign storniert die
            # Anfrage bei der Ablehnung intern (sign.request._refuse -> cancel).
            if rec.kjr_sign_refused and state in ('none', 'canceled'):
                state = 'refused'
            rec.kjr_sign_state = state

    @api.depends('event_id.name', 'event_id.date_begin', 'event_id.date_end',
                 'event_id.date_tz')
    def _compute_kjr_sign_event_label(self):
        """Format "<Veranstaltung>, <TT.MM.JJJJ> bis <TT.MM.JJJJ>" in der
        Zeitzone der Veranstaltung; eintägig nur ein Datum, ohne Termin nur
        der Name."""
        for rec in self:
            event = rec.event_id
            if not event:
                rec.kjr_sign_event_label = False
                continue
            period = rec._kjr_sign_event_period()
            rec.kjr_sign_event_label = (
                _('%(event)s, %(period)s', event=event.name, period=period)
                if period else event.name)

    @api.depends('event_id')
    def _compute_kjr_sign_enabled(self):
        for rec in self:
            rec.kjr_sign_enabled = bool(
                rec.event_id and rec.event_id.sudo().kjr_consent_mode == 'sign')

    def _compute_kjr_consent_action_url(self):
        """Frischer Signierlink der offenen Anfrage (für die KJR-Erinnerung).

        Überschreibt die Methode aus kjr_event; das Feld selbst (compute_sudo,
        groups=KJR_SENSITIVE_DATA_GROUP) bleibt dort deklariert. Der Link wird
        bei jedem Lesen neu erzeugt und trägt damit eine frische Ablaufzeit
        (sign.link_expiry_duration).
        """
        super()._compute_kjr_consent_action_url()
        today = fields.Date.context_today(self)
        for rec in self:
            url = False
            req = rec.sudo().kjr_sign_request_id
            if req and req.state == 'sent' and (not req.validity or req.validity >= today):
                item = req.request_item_ids.filtered(lambda i: i.state == 'sent')[:1].sudo()
                # Nur wenn der Unterzeichner der Anfrage noch der aktuelle
                # Empfänger ist: die KJR-Erinnerung geht an
                # _kjr_consent_recipient_email(), der Link darf nicht als
                # früherer (womöglich fremder) Kontakt signieren lassen.
                if item and item.signer_email == rec._kjr_consent_recipient_email():
                    url = item._get_sign_and_cancel_links(item)[0]
            rec.kjr_consent_action_url = url

    # ------------------------------------------------------------------
    # Unterschriftsanfrage anlegen
    # ------------------------------------------------------------------
    def _kjr_consent_request_start(self):
        """Legt je Anmeldung eine Unterschriftsanfrage an (Override; super() nur
        als Rückfall ohne aktive Brücke, siehe unten).

        Idempotent: Anmeldungen mit offener oder unterschriebener Anfrage
        werden immer übersprungen. Wurde die Anfrage abgelehnt, ist sie
        abgelaufen oder wurde sie storniert, startet KEINE neue Anfrage
        automatisch (die Sperre bleibt, die Geschäftsstelle entscheidet);
        nur mit dem Kontext ``kjr_sign_force`` (Schaltflächen, Cron-Retry).
        Ohne bisherige Anfrage ('none', auch nach einem Versandfehler) wird
        immer gestartet.
        Wirft NIE: jede Anmeldung läuft in ihrem eigenen Savepoint, ein Fehler
        setzt ``kjr_sign_error``, zählt den Versuch und legt eine Aktivität an.
        Der Savepoint wird bewusst AUSSERHALB des try geöffnet (Begründung in
        kjr_event, ``_kjr_auto_invoice``).

        Abgesagte und archivierte Anmeldungen werden nie angefragt (fail-safe
        für alle Aufrufer: Schaltflächen, Shop-Checkout, Cron). Archivieren
        ("Archivieren" in der Liste, Feld ``active`` aus dem Kern) gilt in der
        Brücke wie eine Absage.
        Rückfall (E10, 0.F Nr. 14): Ist die Veranstaltung NICHT (mehr) im
        Modus 'sign' (Brücke ausgeschaltet, Vorlage ungültig geworden), läuft
        die Anmeldung über kjr_event (super(): Aktivität "Einwilligung
        einholen"), ohne Fehlermerker und ohne Zählerstand. Typischer Fall:
        ein zurückgestellter Shop-Warenkorb aus der Zeit im Modus 'sign', der
        nach dem Zurückschalten auf 'sent' oder 'sale' wechselt.
        """
        force = self.env.context.get('kjr_sign_force')
        todo = self.browse()
        for rec in self:
            if rec.sudo().state == 'cancel' or not rec.sudo().active:
                continue
            sign_state = rec.sudo().kjr_sign_state
            if sign_state in SIGN_STATES_ALWAYS_SKIP:
                continue
            if sign_state in SIGN_STATES_NEED_FORCE and not force:
                continue
            todo |= rec
        if not todo:
            return
        sign_regs = todo._kjr_sign_mode_active()
        fallback = todo - sign_regs
        if fallback:
            super(EventRegistration, fallback)._kjr_consent_request_start()
        for rec in sign_regs:
            savepoint = self.env.cr.savepoint()
            try:
                with savepoint:
                    rec._kjr_sign_create_request()
            except Exception:  # noqa: BLE001 - die Anmeldung hat Vorrang
                _logger.exception(
                    'KJR Einwilligung: Unterschriftsanfrage für Anmeldung %s '
                    'konnte nicht angelegt werden.', rec.id)
                rec.sudo().write({
                    'kjr_sign_error': True,
                    'kjr_sign_attempts': rec.sudo().kjr_sign_attempts + 1,
                })
                rec._kjr_consent_activity(
                    _('Unterschriftsanfrage konnte nicht versendet werden'),
                    _('Bitte Absender, Vorlage, E-Mail-Adresse und Name der/des '
                      'Erziehungsberechtigten prüfen und erneut senden.'))

    def _kjr_sign_mode_active(self):
        """Teilmenge, deren Veranstaltung jetzt im Modus 'sign' ist.

        Bewusst über die Methode ``_kjr_consent_mode`` und nicht über das
        nicht gespeicherte Feld ``kjr_sign_enabled``: dessen Wert kann im
        Cache einer Transaktion veralten, wenn der Parameter oder die Vorlage
        sich ändert. Ergebnis je Veranstaltung nur einmal berechnet.
        """
        modes = {}
        result = self.browse()
        for rec in self:
            event = rec.sudo().event_id
            if not event:
                continue
            if event.id not in modes:
                modes[event.id] = event._kjr_consent_mode()
            if modes[event.id] == 'sign':
                result |= rec
        return result

    def _kjr_sign_create_request(self):
        """Erzeugt die sign.request; Odoo Sign versendet im create() die Mail."""
        self.ensure_one()
        reg = self.sudo()
        event = reg.event_id
        template = event._kjr_consent_sign_template()
        if not template:
            raise UserError(_(
                'Für die Veranstaltung ist keine gültige Einwilligungsvorlage (Sign) '
                'verfügbar, oder die digitale Einwilligung ist ausgeschaltet.'))
        role = template.sign_item_ids.responsible_id
        if len(role) != 1:
            raise UserError(_('Die Einwilligungsvorlage muss genau eine Rolle haben.'))
        reg._kjr_sign_check_prefill(template)
        partner = reg._kjr_sign_guardian_partner()
        sender = reg._kjr_sign_sender_user()
        company = event.company_id or reg.company_id or self.env.company
        reminder_days = self._kjr_sign_param_int(PARAM_REMINDER_DAYS, DEFAULT_REMINDER_DAYS)
        if reminder_days < 0:
            reminder_days = 0

        vals = {
            'template_id': template.id,
            'reference': _('Einwilligung %(event)s, Anmeldung Nr. %(id)s',
                           event=event.name, id=reg.id),
            'subject': _('Bitte um Einwilligung: %s', event.name),
            'message': reg._kjr_sign_message(
                company, prefilled=any(template.sign_item_ids.mapped('constant'))),
            'reference_doc': 'event.registration,%d' % reg.id,
            'validity': reg._kjr_sign_validity(),
            'reminder_enabled': reminder_days > 0,
            'reminder': reminder_days or 7,
            'communication_company_id': company.id,
            'request_item_ids': [Command.create({
                'partner_id': partner.id,
                'role_id': role.id,
                'mail_sent_order': 1,
            })],
        }
        # Als Absender, mit Systemrechten (auch auf dem Website-Pfad). Kontext
        # ohne default_*-Schlüssel, damit Vorbelegungen aus Aktionen nicht in
        # die Anfrage durchschlagen. Kein no_sign_mail: die Standard-Mail von
        # Odoo Sign ist gewollt (E6).
        SignRequest = self.env['sign.request'].with_user(sender).sudo().with_context(
            {k: v for k, v in self.env.context.items() if not k.startswith('default_')})
        # Vorbefüllung freigeben (sign.request.item._get_auto_field_value in
        # models/sign_request_item.py): nur für diese Anmeldung und nur während
        # dieses create(). Bewusst über cr.cache und NICHT über den Kontext,
        # den ein Aufruf per RPC frei setzen könnte.
        prefill = self.env.cr.cache.setdefault(PREFILL_CACHE_KEY, set())
        added = reg.id not in prefill
        prefill.add(reg.id)
        try:
            req = SignRequest.create(vals)
        finally:
            if added:
                prefill.discard(reg.id)
        # Erfolg: Fehlerzähler zurücksetzen. Sonst stünde er nach früheren
        # Fehlversuchen schon auf MAX_ATTEMPTS, und ein späterer Fehlschlag
        # (Neuversand nach Adresskorrektur, "Erneut senden") würde vom Cron nie
        # wiederholt.
        reg.write({
            'kjr_sign_request_id': req.id,
            'kjr_sign_error': False,
            'kjr_sign_attempts': 0,
            'kjr_sign_refused': False,
            'kjr_sign_followup_done': False,
        })
        reg.message_post(
            body=_('Unterschriftsanfrage versendet (Anfrage %s).', req.id),
            subtype_xmlid='mail.mt_note')
        return req

    def _kjr_sign_validity(self):
        """Gültig bis: höchstens ``validity_days`` ab heute, spätestens am Tag
        vor Beginn, mindestens aber bis morgen."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        days = self._kjr_sign_param_int(PARAM_VALIDITY_DAYS, DEFAULT_VALIDITY_DAYS)
        if days < 1:
            days = DEFAULT_VALIDITY_DAYS
        validity = today + timedelta(days=days)
        begin = self._kjr_sign_event_begin_date()
        if begin:
            validity = min(validity, begin - timedelta(days=1))
        return max(today + timedelta(days=1), validity)

    def _kjr_sign_event_begin_date(self):
        """Beginn der Veranstaltung als Datum in der Zeitzone der Veranstaltung."""
        self.ensure_one()
        event = self.sudo().event_id
        if not event.date_begin:
            return False
        tz = pytz.timezone(event.date_tz or 'UTC')
        return pytz.utc.localize(event.date_begin).astimezone(tz).date()

    def _kjr_sign_event_end_date(self):
        """Ende der Veranstaltung als Datum in der Zeitzone der Veranstaltung."""
        self.ensure_one()
        event = self.sudo().event_id
        if not event.date_end:
            return False
        tz = pytz.timezone(event.date_tz or 'UTC')
        return pytz.utc.localize(event.date_end).astimezone(tz).date()

    def _kjr_sign_event_period(self):
        """Zeitraum als Text ("01.08.2027 bis 07.08.2027", eintägig nur ein
        Datum) oder False ohne Beginn. Gemeinsame Quelle für den Begleittext
        der Mail und das Feld "Veranstaltung" im Formular."""
        self.ensure_one()
        begin = self._kjr_sign_event_begin_date()
        end = self._kjr_sign_event_end_date()
        if begin and end and end != begin:
            return _('%(begin)s bis %(end)s',
                     begin=begin.strftime('%d.%m.%Y'), end=end.strftime('%d.%m.%Y'))
        if begin:
            return begin.strftime('%d.%m.%Y')
        return False

    def _kjr_sign_message(self, company, prefilled=True):
        """Begleittext der Sign-Mail. Ohne Kindsnamen, Firmenname aus der Firma.

        :param prefilled: True, wenn die Vorlage Felder aus der Anmeldung
                          vorbefüllt (schreibgeschützte Felder, Vorlage v2).
                          Dann bitten wir um Prüfung der übernommenen
                          Angaben; sonst (v1, eigene Vorlagen ohne
                          Vorbefüllung) wie bisher um das Eintragen des
                          Kindsnamens.
        """
        self.ensure_one()
        event = self.sudo().event_id
        period = self._kjr_sign_event_period() or _('Termin folgt')
        if prefilled:
            hint = _('Bitte prüfen Sie die aus der Anmeldung übernommenen Angaben (Name '
                     'Ihres Kindes, Veranstaltung und Ihr Name), bestätigen Sie die '
                     'Einwilligung und unterschreiben Sie. Stimmen die Angaben nicht, '
                     'kennen Sie diese Anmeldung nicht oder sind Sie nicht '
                     'erziehungsberechtigt, unterschreiben Sie bitte nicht und melden Sie '
                     'sich bei uns.')
        else:
            hint = _('Bitte tragen Sie im Formular den Namen Ihres Kindes ein. Kennen Sie '
                     'diese Anmeldung nicht oder sind Sie nicht erziehungsberechtigt, '
                     'unterschreiben Sie bitte nicht und melden Sie sich bei uns.')
        return Markup('<p>%s</p><p>%s</p><p>%s</p>') % (
            _('Guten Tag,'),
            _('für die Veranstaltung "%(event)s" (%(period)s) von %(company)s liegt '
              'eine Anmeldung mit der Nummer %(id)s vor. Für Teilnehmende unter 18 '
              'Jahren benötigen wir die Einwilligung einer erziehungsberechtigten '
              'Person. Erst danach ist die Anmeldung verbindlich bestätigt.',
              event=event.name, period=period, company=company.name, id=self.id),
            hint,
        )

    def _kjr_sign_check_prefill(self, template):
        """Wirft UserError, wenn die Vorlage den Namen der/des
        Erziehungsberechtigten schreibgeschützt aus der Anmeldung übernimmt und
        er an der Anmeldung fehlt oder dem Namen des Kindes entspricht.

        Ein schreibgeschütztes Feld können die Eltern nicht selbst füllen; das
        unterschriebene Dokument trüge sonst keinen Namen der unterschreibenden
        Person. Ebenso, wenn dort der Name des Kindes steht (Vergleich ohne
        Groß-/Kleinschreibung und Mehrfach-Leerraum): sonst stünde der
        Kindername schreibgeschützt als Name der/des Erziehungsberechtigten im
        Dokument. Die Website-Vorprüfung (kjr_event) prüft beides im Verfahren
        'sign'; hier geht es um Anmeldungen aus dem Backend, ältere
        Anmeldungen und "Erneut senden". Der Fehler landet wie jeder andere in
        ``kjr_sign_error`` und einer Aktivität (``_kjr_consent_request_start``).
        """
        self.ensure_one()
        types = template.sudo().sign_item_ids.filtered('constant').type_id
        needs_guardian = any(
            t.model_name == self._name and t.auto_field == GUARDIAN_AUTO_FIELD
            for t in types)
        if not needs_guardian:
            return
        reg = self.sudo()
        guardian = _norm_name(reg.guardian_name)
        if not guardian:
            raise UserError(_(
                'Für die Unterschriftsanfrage fehlt der Name der/des '
                'Erziehungsberechtigten an der Anmeldung. Bitte ergänzen und erneut '
                'senden.'))
        if guardian == _norm_name(reg.name):
            # Gemeldeter Fall (19.0.1.1.0): Eltern trugen den Namen des Kindes
            # in das Feld der Erziehungsberechtigten ein. Das Dokument trüge
            # den Kindernamen schreibgeschützt als unterschreibende Person.
            # Betrifft vor allem ältere Anmeldungen (vor der Website-Prüfung
            # kjr_guardian_name_is_child) und das Backend.
            raise UserError(_(
                'An der Anmeldung steht als Name der/des Erziehungsberechtigten der '
                'Name des Kindes. Bitte den Namen der erziehungsberechtigten Person '
                'eintragen und erneut senden.'))

    def _kjr_sign_guardian_partner(self):
        """Kontakt der erziehungsberechtigten Person (Unterzeichner).

        Hintergrund (19.0.1.1.0): Die Website legt den Kontakt der Anmeldung
        (``partner_id``) oft mit dem Namen der angemeldeten Person an, also
        des KINDES. Wurde er wiederverwendet, stand im Sign-Feld "Name" der
        Kindername und die Sign-Mail sprach das Kind an.

        Mit Namen der/des Erziehungsberechtigten (``guardian_name``):
        1. der Kontakt der Anmeldung, wenn E-Mail UND Name passen,
        2. sonst ein Kontakt mit derselben normalisierten E-Mail UND demselben
           Namen (Vergleich ohne Groß-/Kleinschreibung und Mehrfach-Leerraum),
        3. sonst ein neuer Kontakt mit ``name = guardian_name``.
        Ohne Namen (ältere Anmeldungen, Backend): wie bisher der Kontakt der
        Anmeldung bzw. ein Kontakt mit derselben E-Mail; sonst ein neuer
        Kontakt mit der E-Mail-Adresse als Name.
        In beiden Fällen NIE ein Kontakt, dessen Name dem Namen des Kindes
        (``name`` der Anmeldung) entspricht. Steht in ``guardian_name`` der
        Name des Kindes, gilt der Name als fehlend.

        Bei mehreren Treffern haben Kontakte mit Benutzerkonto Vorrang (nur
        dann erscheint die Anfrage im Portal unter "Signaturanfragen"), danach
        Personen vor Firmen, jeweils der älteste. Neue Kontakte bekommen die
        Kategorie "KJR Erziehungsberechtigte" (für das Löschkonzept auffindbar)
        und Deutsch als Sprache. Bestehende Kontakte werden nie umbenannt.
        """
        self.ensure_one()
        reg = self.sudo()
        email = reg._kjr_consent_recipient_email()
        if not email:
            raise UserError(_(
                'Für die Unterschriftsanfrage fehlt eine gültige E-Mail-Adresse der '
                'Erziehungsberechtigten.'))
        guardian_name = ' '.join((reg.guardian_name or '').split())
        guardian = _norm_name(guardian_name)
        child = _norm_name(reg.name)
        if guardian and guardian == child:
            # Name des Kindes im Feld der Erziehungsberechtigten (gemeldeter
            # Fall): wie ein fehlender Name behandeln. Sonst würde der
            # Kind-Kontakt wiederverwendet oder ein neuer Kontakt mit dem
            # Kindernamen angelegt. Vorlagen mit vorbefülltem Namen weist
            # _kjr_sign_check_prefill vorher ab.
            guardian_name = guardian = ''

        def acceptable(partner):
            name = _norm_name(partner.name)
            # Nie der Kind-Kontakt, auch nicht mit Namen der Eltern.
            if child and name == child:
                return False
            return name == guardian if guardian else True

        if reg.partner_id and reg.partner_id.email_normalized == email \
                and acceptable(reg.partner_id):
            return reg.partner_id
        Partner = self.env['res.partner'].sudo()
        matches = Partner.search(
            [('email_normalized', '=', email)], order='id', limit=50).filtered(acceptable)
        if matches:
            return min(matches, key=lambda p: (not p.user_ids, bool(p.is_company), p.id))
        vals = {
            'name': guardian_name or email,
            'email': email,
        }
        if self.env['res.lang']._get_code('de_DE'):
            vals['lang'] = 'de_DE'
        category = self.env.ref('kjr_event_sign.partner_category_guardian',
                                raise_if_not_found=False)
        if category:
            vals['category_id'] = [Command.link(category.id)]
        return Partner.create(vals)

    @api.model
    def _kjr_sign_sender_candidates(self, event=None):
        """Erster geeigneter Absender oder ein leeres Recordset.

        Reihenfolge: Systemparameter ``kjr_event_sign.sender_user_id``, die
        verantwortliche Person der Veranstaltung, der Administrator. Geeignet ist
        ein aktiver interner Benutzer mit E-Mail-Adresse (Odoo Sign verlangt sie,
        sign.request._check_senders_validity).
        """
        Users = self.env['res.users'].sudo()
        candidates = []
        raw = self.env['ir.config_parameter'].sudo().get_param(PARAM_SENDER)
        try:
            if raw:
                candidates.append(Users.browse(int(raw)).exists())
        except (TypeError, ValueError):
            _logger.warning('KJR Einwilligung: Systemparameter %s ist keine Benutzer-ID.',
                            PARAM_SENDER)
        if event:
            candidates.append(event.sudo().user_id)
        candidates.append(self.env.ref('base.user_admin', raise_if_not_found=False) or Users)
        for user in candidates:
            user = user.sudo()
            if user and user.active and not user.share and user.email_formatted:
                return user
        return Users

    def _kjr_sign_sender_user(self):
        self.ensure_one()
        sender = self._kjr_sign_sender_candidates(event=self.sudo().event_id)
        if not sender:
            raise UserError(_('Kein Absender mit E-Mail-Adresse für Unterschriftsanfragen konfiguriert.'))
        return sender

    @api.model
    def _kjr_sign_param_int(self, key, default):
        raw = self.env['ir.config_parameter'].sudo().get_param(key)
        if raw in (None, False, ''):
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            _logger.warning('KJR Einwilligung: Systemparameter %s ist keine Zahl.', key)
            return default

    # ------------------------------------------------------------------
    # Storno offener Anfragen
    # ------------------------------------------------------------------
    def _kjr_sign_open_requests(self):
        return self.sudo().mapped('kjr_sign_request_id').filtered(lambda r: r.state == 'sent')

    def _kjr_sign_cancel_open_requests(self, reason=None):
        """Storniert offene Anfragen. Wirft nie; Notiz übernimmt der cancel-Hook.

        :param reason: Storno-Grund ('paper', 'resend', 'email', 'data'). Der cancel-Hook
                       bildet ihn auf einen festen Notiztext ab (so entsteht
                       genau EINE Notiz je Storno); ohne Grund gilt der
                       Standardtext "Unterschriftsanfrage storniert.".
        :return: die stornierten Anfragen
        """
        requests = self._kjr_sign_open_requests()
        if not requests:
            return requests
        if reason:
            requests = requests.with_context(kjr_sign_cancel_reason=reason)
        savepoint = self.env.cr.savepoint()
        try:
            with savepoint:
                requests.cancel()
        except Exception:  # noqa: BLE001 - Storno darf die Anmeldung nicht kippen
            _logger.exception('KJR Einwilligung: Storno der Unterschriftsanfrage(n) %s '
                              'fehlgeschlagen.', requests.ids)
            return requests.browse()
        return requests

    # ------------------------------------------------------------------
    # Verknüpfung zur Anfrage nur über die Brücke
    # ------------------------------------------------------------------
    @api.model
    def _kjr_sign_check_request_link(self, vals_list):
        """Wirft AccessError, wenn ``kjr_sign_request_id`` ohne Systemrechte
        gesetzt werden soll.

        ``readonly=True`` am Feld wirkt nur in der Oberfläche; per RPC (write,
        create, Kontext ``default_kjr_sign_request_id``) wäre das Feld für
        jede Person mit Sign-Rechten und Schreibrecht an der Anmeldung
        (Registrierungstheke) setzbar. Am Feld hängen aber die Freigabe der
        Vorbefüllung (models/sign_request_item.py: guardian_name und Name des
        Kindes über die Signierseite) und die Wirkung der Unterschrift
        (sign.request._kjr_registration: Einwilligung, Freigabe der Sperre).
        Gesetzt wird es nur von der Brücke (sudo): ``_kjr_sign_create_request``
        und die Anonymisierung (event.event._kjr_purge_registration_copies).
        """
        if self.env.su:
            return
        if self.env.context.get('default_kjr_sign_request_id') \
                or any('kjr_sign_request_id' in vals for vals in vals_list):
            raise AccessError(_(
                'Die Unterschriftsanfrage einer Anmeldung kann nicht von Hand gesetzt '
                'werden. Bitte die Schaltflächen "Unterschrift anfordern" bzw. '
                '"Erneut senden" verwenden.'))

    @api.model_create_multi
    def create(self, vals_list):
        self._kjr_sign_check_request_link(vals_list)
        return super().create(vals_list)

    def write(self, vals):
        self._kjr_sign_check_request_link([vals])
        res = super().write(vals)
        # Archivieren gilt wie eine Absage: sonst bliebe die Anfrage offen, Odoo
        # Sign erinnerte die Eltern weiter, und eine spätere Unterschrift gäbe
        # die archivierte Anmeldung frei (Rechnung inklusive).
        archived = 'active' in vals and not vals['active']
        if vals.get('state') == 'cancel' or archived:
            self._kjr_sign_cancel_open_requests()
        elif vals.get('parental_consent'):
            source = vals.get('kjr_consent_source') or self.env.context.get('kjr_consent_source')
            # Gleiche Regel wie in kjr_event (write): Der Kontext ist per RPC
            # frei wählbar, 'sign' gilt nur auf dem sudo-Weg der Brücke
            # (sign.request._sign). Sonst bucht kjr_event die Einwilligung als
            # Papier, und die offene Anfrage muss ebenso storniert werden.
            if source != 'sign' or not self.env.su:
                self._kjr_sign_cancel_open_requests(reason='paper')
        else:
            if any(field in vals for field in RECIPIENT_FIELDS):
                self._kjr_sign_check_recipient()
            # Nach dem Adresswechsel: eine dort neu versendete Anfrage trägt
            # schon die neuen Angaben und gilt nicht als veraltet.
            if any(field in vals for field in PREFILL_FIELDS):
                self._kjr_sign_check_prefilled()
        return res

    def _kjr_sign_check_recipient(self):
        """Empfänger geändert (z. B. Tippfehler in der Eltern-Adresse korrigiert):
        eine offene Anfrage an die ALTE Adresse wird storniert und, solange die
        Anmeldung noch gesperrt ist und die Einwilligung fehlt, sofort an die
        neue Adresse neu versendet. Sonst schickte Odoo Sign seine Erinnerungen
        weiter an die alte, womöglich fremde Adresse. Wirft nie.

        Automatisch neu versendet wird nur mit sudo oder für
        Veranstaltungs-Benutzer/innen (gleiche Grenze wie die Schaltflächen,
        ``_kjr_sign_check_button_access``). Die Anmelde-E-Mail darf auch die
        Registrierungstheke ändern; ein Neuversand von dort schickte den
        Signierlink an eine selbst gewählte Adresse und höbe nach der
        Unterschrift die Sperre auf, ohne dass die Person die Einwilligung
        eintragen dürfte. Ohne diese Rechte wird nur storniert, und es entsteht
        die Aktivität "Unterschriftsanfrage neu senden".
        """
        changed = self.browse()
        for rec in self:
            req = rec._kjr_sign_open_requests()
            if not req:
                continue
            item = req.request_item_ids.sudo().filtered(lambda i: i.state == 'sent')[:1]
            if item and item.signer_email != rec._kjr_consent_recipient_email():
                changed |= rec
        if not changed:
            return
        changed._kjr_sign_cancel_and_restart(
            'email',
            _('Die E-Mail-Adresse der Erziehungsberechtigten wurde geändert, die '
              'offene Unterschriftsanfrage an die alte Adresse konnte aber nicht '
              'storniert werden. Bitte die Anfrage stornieren und erneut senden.'),
            _('Die E-Mail-Adresse der Erziehungsberechtigten wurde geändert, die offene '
              'Unterschriftsanfrage an die alte Adresse ist storniert. Bitte prüfen und '
              'die Anfrage erneut senden.'))

    def _kjr_sign_check_prefilled(self):
        """Angaben der Anmeldung geändert (Name des Kindes, Name der/des
        Erziehungsberechtigten, über event.event.write auch Name oder Termine
        der Veranstaltung): Weicht ein schreibgeschützt übernommener Wert der
        offenen Anfrage (Vorlage v2) vom aktuellen Stand ab, wird die Anfrage
        storniert und wie bei einem Adresswechsel neu versendet bzw. die
        Aktivität "Unterschriftsanfrage neu senden" angelegt.

        Die Eltern können schreibgeschützte Felder nicht korrigieren, und Odoo
        Sign lehnt jede spätere Änderung des Werts ab
        (sign.request.item.value.write). Ohne Neuversand unterschrieben sie
        ein Dokument mit veralteten Angaben. Anfragen ohne vorbefüllte Felder
        (v1, eigene Vorlagen) bleiben unberührt. Wirft nie.
        """
        changed = self.browse()
        for rec in self:
            try:
                req = rec._kjr_sign_open_requests()
                if req and rec._kjr_sign_prefill_outdated(req):
                    changed |= rec
            except Exception:  # noqa: BLE001 - die Änderung hat Vorrang
                _logger.exception(
                    'KJR Einwilligung: Vorbefüllte Angaben der Anfrage zu Anmeldung %s '
                    'nicht prüfbar.', rec.id)
        if not changed:
            return
        changed._kjr_sign_cancel_and_restart(
            'data',
            _('Angaben der Anmeldung (Name des Kindes, Name der/des '
              'Erziehungsberechtigten oder Veranstaltung) wurden geändert, die offene '
              'Unterschriftsanfrage mit den alten Angaben konnte aber nicht storniert '
              'werden. Bitte die Anfrage stornieren und erneut senden.'),
            _('Angaben der Anmeldung (Name des Kindes, Name der/des '
              'Erziehungsberechtigten oder Veranstaltung) wurden geändert, die offene '
              'Unterschriftsanfrage mit den alten Angaben ist storniert. Bitte prüfen '
              'und die Anfrage erneut senden.'))

    def _kjr_sign_prefill_outdated(self, request):
        """True, wenn ein schreibgeschützter, aus der Anmeldung übernommener
        Wert der Anfrage nicht mehr dem aktuellen Stand entspricht. Der
        aktuelle Wert kommt aus derselben Methode, mit der Odoo Sign beim
        Anlegen gefüllt hat (``_get_auto_field_value``); die Anfrage ist hier
        die aktuelle der Anmeldung, die Sperre in models/sign_request_item.py
        gibt sie frei."""
        self.ensure_one()
        item = request.sudo().request_item_ids.filtered(lambda i: i.state == 'sent')[:1]
        if not item:
            return False
        for value in item.sign_item_value_ids:
            sign_item = value.sign_item_id
            item_type = sign_item.type_id
            if not sign_item.constant or not item_type.auto_field \
                    or item_type.model_id.model != self._name:
                continue
            current = item._get_auto_field_value(
                {'id': item_type.id, 'auto_field': item_type.auto_field})
            if (current or '') != (value.value or ''):
                return True
        return False

    def _kjr_sign_cancel_and_restart(self, reason, note_failed, note_canceled):
        """Storniert die offenen Anfragen mit ``reason`` und versendet neu.

        Automatisch neu versendet wird nur mit sudo oder für
        Veranstaltungs-Benutzer/innen (gleiche Grenze wie die Schaltflächen,
        siehe ``_kjr_sign_check_recipient``) und nur, solange die Anmeldung
        gesperrt ist und die Einwilligung fehlt. Sonst die Aktivität
        "Unterschriftsanfrage neu senden" mit ``note_canceled``. Scheitert das
        Storno, wird nicht neu gesendet (sonst gingen zwei Anfragen hinaus),
        sondern die Aktivität mit ``note_failed`` angelegt.
        """
        if not self._kjr_sign_cancel_open_requests(reason=reason):
            # Storno gescheitert (Fehler im Log): Die Geschäftsstelle entscheidet.
            self._kjr_consent_activity(_('Unterschriftsanfrage neu senden'), note_failed)
            return
        may_restart = self.env.su or self.env.user.has_group('event.group_event_user')
        restart = self.filtered(
            lambda r: r.sudo().kjr_consent_hold and r.sudo().consent_missing
            and r.sudo().state != 'cancel' and r.sudo().active
            and r.sudo().kjr_sign_enabled
            and r._kjr_consent_recipient_email()) if may_restart else self.browse()
        if restart:
            restart.with_context(kjr_sign_force=True)._kjr_consent_request_start()
        (self - restart)._kjr_consent_activity(
            _('Unterschriftsanfrage neu senden'), note_canceled)

    def unlink(self):
        # Vor dem Löschen: offene Anfragen stornieren. Die Anfrage selbst bleibt
        # (unterschriebene sind ohnehin nicht löschbar); der Cron räumt Fälle ab,
        # in denen Anmeldungen per Datenbank-Kaskade verschwinden.
        self._kjr_sign_cancel_open_requests()
        return super().unlink()

    # ------------------------------------------------------------------
    # Schaltflächen
    # ------------------------------------------------------------------
    def _kjr_sign_check_button_access(self, operation='write'):
        """Serverseitige Rechteprüfung der Schaltflächen.

        ``groups`` am Knopf wirkt nur in der Oberfläche. Öffentliche Methoden
        sind per RPC (call_kw/call_button) für jeden aufrufbar, der die
        Anmeldung lesen darf (Registration Desk, Portal-Kooperationspartner).
        Danach läuft alles mit sudo bzw. als konfigurierter Absender, deshalb
        hier: Veranstaltungs-Benutzer/in UND Recht auf ``operation`` an den
        Anmeldungen. sudo-Aufrufe sind vertrauenswürdig.
        """
        if not (self.env.su or self.env.user.has_group('event.group_event_user')):
            raise AccessError(_(
                'Nur Veranstaltungs-Benutzer/innen dürfen Unterschriftsanfragen '
                'anfordern, neu senden oder stornieren.'))
        self.check_access(operation)

    def _kjr_sign_reset_attempts(self):
        """Neue bewusste Anforderung: wieder drei Versuche für den Cron."""
        with_attempts = self.sudo().filtered('kjr_sign_attempts')
        if with_attempts:
            with_attempts.write({'kjr_sign_attempts': 0})

    def action_kjr_sign_request_send(self):
        self._kjr_sign_check_button_access()
        # Abgesagte und archivierte Anmeldungen nie anfragen (sonst ginge eine
        # Sign-Mail an die Eltern einer abgesagten Anmeldung).
        todo = self.filtered(
            lambda r: r.state != 'cancel' and r.active and r.consent_missing
            and r.kjr_sign_state not in ('sent', 'signed'))
        if not todo:
            return self._kjr_notification(
                _('Unterschrift anfordern'),
                _('Keine Anmeldung ohne Einwilligung und ohne offene Anfrage ausgewählt.'),
                'warning')
        inactive = todo.filtered(lambda r: not r.kjr_sign_enabled)
        if inactive:
            return self._kjr_notification(
                _('Unterschrift anfordern'),
                _('Die digitale Einwilligung ist für diese Veranstaltung nicht aktiv '
                  '(Einstellungen: "Einwilligung digital einholen", gültige Vorlage).'),
                'warning')
        # Bewusste Entscheidung der Geschäftsstelle: auch nach Ablehnung,
        # Ablauf oder Storno neu anfordern.
        todo._kjr_sign_reset_attempts()
        todo.with_context(kjr_sign_force=True)._kjr_consent_request_start()
        return self._kjr_sign_result_notification(todo, _('Unterschrift anfordern'))

    def action_kjr_sign_request_resend(self):
        self._kjr_sign_check_button_access()
        todo = self.filtered(
            lambda r: r.state != 'cancel' and r.active and r.consent_missing
            and r.kjr_sign_state != 'signed')
        if not todo:
            return self._kjr_notification(
                _('Erneut senden'), _('Keine passende Anmeldung ausgewählt.'), 'warning')
        if todo.filtered(lambda r: not r.kjr_sign_enabled):
            return self._kjr_notification(
                _('Erneut senden'),
                _('Die digitale Einwilligung ist für diese Veranstaltung nicht aktiv.'),
                'warning')
        todo._kjr_sign_cancel_open_requests(reason='resend')
        todo._kjr_sign_reset_attempts()
        todo.with_context(kjr_sign_force=True)._kjr_consent_request_start()
        return self._kjr_sign_result_notification(todo, _('Erneut senden'))

    def action_kjr_sign_request_cancel(self):
        self._kjr_sign_check_button_access()
        canceled = self._kjr_sign_cancel_open_requests()
        if not canceled:
            return self._kjr_notification(
                _('Anfrage stornieren'), _('Keine offene Unterschriftsanfrage vorhanden.'),
                'warning')
        return self._kjr_notification(
            _('Anfrage stornieren'),
            _('%s Unterschriftsanfrage(n) storniert.', len(canceled)), 'success')

    def action_kjr_open_sign_request(self):
        self.ensure_one()
        # Nur lesend; die Anfrage selbst prüft unten has_access (Odoo Sign).
        self.check_access('read')
        req = self.kjr_sign_request_id
        if not req:
            return self._kjr_notification(
                _('Unterschriftsanfrage'), _('Keine Unterschriftsanfrage vorhanden.'), 'warning')
        if not req.has_access('read'):
            return self._kjr_notification(
                _('Unterschriftsanfrage'),
                _('Keine Berechtigung für diese Unterschriftsanfrage (Odoo Sign).'), 'warning')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Unterschriftsanfrage'),
            'res_model': 'sign.request',
            'res_id': req.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def _kjr_sign_result_notification(self, regs, title):
        sent = regs.filtered(lambda r: r.kjr_sign_state == 'sent' and not r.kjr_sign_error)
        failed = regs - sent
        if failed:
            return self._kjr_notification(
                title,
                _('%(ok)s Anfrage(n) versendet, %(err)s fehlgeschlagen. Details stehen in '
                  'der Aktivität an der Anmeldung.', ok=len(sent), err=len(failed)),
                'warning')
        return self._kjr_notification(
            title, _('%s Unterschriftsanfrage(n) versendet.', len(sent)), 'success')

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------
    @api.model
    def _cron_kjr_event_sign(self):
        """Täglicher Lauf der Brücke (je Schritt höchstens CRON_BATCH_LIMIT).

        a) Wiederholung: gesperrte Anmeldungen mit Versandfehler, höchstens
           MAX_ATTEMPTS Versuche, nur bei Veranstaltungen im Modus 'sign'.
        b) Nachfassen: gesperrte Anmeldungen, deren Anfrage abgelaufen,
           abgelehnt oder storniert ist, bekommen einmalig eine Aktivität.
        c) Waisen: offene Anfragen, deren Anmeldung gelöscht (z. B. per
           Kaskade beim Löschen der Veranstaltung), abgesagt oder archiviert
           ist, werden storniert.
        """
        Reg = self.sudo()
        # a) Wiederholung
        # Nur Veranstaltungen im Modus 'sign' (der Modus ist nicht gespeichert,
        # daher Filter in Python und das Limit erst danach; die Domain ist eng,
        # die Treffermenge klein). Ist die Brücke ausgeschaltet, gibt es nichts
        # zu wiederholen: neue Anforderungen laufen dann über kjr_event.
        retry = Reg.search([
            ('kjr_consent_hold', '=', True),
            ('kjr_sign_error', '=', True),
            ('kjr_sign_attempts', '<', MAX_ATTEMPTS),
            ('parental_consent', '=', False),
            ('state', '!=', 'cancel'),
        ], order='id')._kjr_sign_mode_active()[:CRON_BATCH_LIMIT]
        if retry:
            # Nur Anmeldungen mit Versandfehler: der letzte Versuch kam von
            # einer bewussten oder automatischen Anforderung ohne Erfolg.
            retry.with_context(kjr_sign_force=True)._kjr_consent_request_start()

        # b) Nachfassen
        followup = Reg.search([
            ('kjr_consent_hold', '=', True),
            ('kjr_sign_state', 'in', ('expired', 'refused', 'canceled')),
            ('kjr_sign_followup_done', '=', False),
            # Liegt die Einwilligung (z. B. auf Papier) vor und bleibt die
            # Anmeldung nur mangels Platz gesperrt, gibt es nichts nachzufassen.
            ('parental_consent', '=', False),
            ('state', '!=', 'cancel'),
        ], limit=CRON_BATCH_LIMIT, order='id')
        for reg in followup:
            reg._kjr_consent_activity(
                _('Unterschrift abgelaufen oder abgelehnt'),
                _('Die Einwilligung liegt nicht vor. Bitte Kontakt mit den '
                  'Erziehungsberechtigten aufnehmen und die Anfrage erneut senden, '
                  'eine Papier-Einwilligung erfassen oder die Anmeldung absagen.'))
        if followup:
            followup.write({'kjr_sign_followup_done': True})

        # c) Waisen. Direkt per SQL: das ORM liefert für eine Referenz auf eine
        # gelöschte Anmeldung nur einen leeren Wert (fields.Reference prüft
        # exists()), der Bezug auf event.registration wäre dann nicht mehr
        # erkennbar. Die Waisen-Bedingung steht IM SQL und das LIMIT greift
        # erst danach: offene Anfragen zu lebenden Anmeldungen belegen sonst
        # das Fenster, und spätere Waisen kämen nie an die Reihe. Die ID wird
        # nur gecastet, wenn sie aus Ziffern besteht (CASE wertet in Reihenfolge
        # aus); eine nicht lesbare Referenz zählt nicht als Waise.
        SignRequest = self.env['sign.request'].sudo()
        SignRequest.flush_model(['state', 'active', 'reference_doc'])
        Reg.flush_model(['state', 'active'])
        self.env.cr.execute(SQL(
            """SELECT sr.id
                 FROM (SELECT id,
                              CASE WHEN split_part(reference_doc, ',', 2) ~ '^[0-9]{1,9}$'
                                   THEN split_part(reference_doc, ',', 2)::int
                              END AS reg_id
                         FROM sign_request
                        WHERE state = 'sent' AND active
                          AND reference_doc LIKE %s) sr
            LEFT JOIN event_registration er ON er.id = sr.reg_id
                WHERE sr.reg_id IS NOT NULL
                  AND (er.id IS NULL OR er.state = 'cancel' OR NOT er.active)
             ORDER BY sr.id
                LIMIT %s""",
            'event.registration,%', CRON_BATCH_LIMIT))
        orphans = SignRequest.browse([row[0] for row in self.env.cr.fetchall()])
        if orphans:
            savepoint = self.env.cr.savepoint()
            try:
                with savepoint:
                    orphans.cancel()
                _logger.info('KJR Einwilligung: %s verwaiste Unterschriftsanfrage(n) storniert.',
                             len(orphans))
            except Exception:  # noqa: BLE001
                _logger.exception('KJR Einwilligung: Storno verwaister Anfragen %s fehlgeschlagen.',
                                  orphans.ids)
