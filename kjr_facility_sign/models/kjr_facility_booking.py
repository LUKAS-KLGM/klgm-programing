# -*- coding: utf-8 -*-
"""Einrichtungsbuchung: Buchungsvertrag per Odoo Sign unterschreiben.

Ablauf:
* kjr_facility verschickt den Vertrag in ``action_confirm`` über die
  Erweiterungsstelle ``_send_contract`` (ab 19.0.7.4.0). Ist die digitale
  Unterschrift eingeschaltet (Systemparameter, Einrichtung nicht ausgenommen),
  entsteht statt der Vertragsmail eine Unterschriftsanfrage: das aktuell
  gerenderte Vertrags-PDF plus eine eigene Unterschriftsseite (Ort, Datum,
  Unterschrift) wird zu einer Einmal-Vorlage (archiviert) mit drei Feldern
  der Rolle "Mieter/in" auf der letzten Seite.
* Schlägt das fehl, geht der Vertrag wie bisher per Mail hinaus und die
  Geschäftsstelle erhält eine Aufgabe (der Buchungsablauf wird nie blockiert).
* Die Unterschrift setzt nur ``contract_signed`` (plus Datum und Quelle). Der
  Buchungsstatus bleibt unverändert: kjr_facility kennt keinen Übergang, der
  an den Vertragsrücklauf gekoppelt ist ("Gebucht" entsteht mit
  "Verbindlich buchen", also VOR dem Vertragsversand).
* Papierweg, Storno, Zurücksetzen und Löschen der Buchung stornieren eine
  offene Anfrage. Ablehnung und Ablauf erzeugen Notiz und Aufgabe.

Datensparsamkeit: Betreff, Referenz, Dokumentname, Notizen und Aufgaben
tragen nur die Buchungsnummer. Ins Protokoll kommen nur IDs, Anzahlen und
Ausnahmetypen (Traceback nur auf DEBUG).
"""
import base64
import io
import logging
from datetime import timedelta

from markupsafe import Markup

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import SQL, email_normalize, str2bool
from odoo.tools.pdf import PdfFileReader, merge_pdf

from ..tools import sign_page

_logger = logging.getLogger(__name__)

PARAM_ENABLED = 'kjr_facility_sign.enabled'           # nicht geseedet = AUS
PARAM_SENDER = 'kjr_facility_sign.sender_user_id'
PARAM_VALIDITY = 'kjr_facility_sign.validity_days'
PARAM_REMINDER = 'kjr_facility_sign.reminder_days'
DEFAULT_VALIDITY_DAYS = 14
DEFAULT_REMINDER_DAYS = 3
REPORT_CONTRACT = 'kjr_facility.action_report_booking_contract'
XMLID_ROLE = 'kjr_facility_sign.sign_item_role_tenant'
XMLID_SIGNER_CATEGORY = 'kjr_facility_sign.partner_category_signer'
SIGNABLE_BOOKING_STATES = ('confirmed', 'deposit', 'checked_in')
SIGN_STATE_MAP = {
    'sent': 'sent',
    'shared': 'sent',
    'signed': 'signed',
    'canceled': 'canceled',
    'expired': 'expired',
}


class KjrFacilityBooking(models.Model):
    _inherit = 'kjr.facility.booking'

    kjr_sign_request_id = fields.Many2one(
        'sign.request', string='Unterschriftsanfrage', copy=False, readonly=True,
        ondelete='set null', index='btree_not_null', groups='sign.group_sign_user')
    kjr_sign_refused = fields.Boolean(
        string='Unterschrift abgelehnt', copy=False, readonly=True)
    kjr_sign_state = fields.Selection([
        ('none', 'Keine Anfrage'),
        ('sent', 'Unterschrift ausstehend'),
        ('signed', 'Unterschrieben'),
        ('refused', 'Abgelehnt'),
        ('expired', 'Abgelaufen'),
        ('canceled', 'Storniert'),
    ], string='Stand Unterschrift', compute='_compute_kjr_sign_state', store=True,
        compute_sudo=True, index=True, copy=False,
        help='Stand der digitalen Vertragsunterschrift (Odoo Sign) dieser Buchung.')
    contract_signed_date = fields.Date(
        string='Vertrag unterschrieben am', copy=False, readonly=True, tracking=True)
    contract_signed_source = fields.Selection([
        ('digital', 'Digital (Odoo Sign)'),
        ('paper', 'Papier'),
    ], string='Unterschrieben über', copy=False, readonly=True, tracking=True)
    kjr_sign_available = fields.Boolean(
        string='Digitale Unterschrift möglich', compute='_compute_kjr_sign_available',
        help='Technisch: digitale Vertragsunterschrift eingeschaltet und für die '
             'Einrichtung nicht abgeschaltet. Steuert die Sichtbarkeit der Schaltflächen.')

    # ------------------------------------------------------------------
    # Berechnungen
    # ------------------------------------------------------------------
    @api.depends('kjr_sign_request_id.state', 'kjr_sign_refused',
                 'contract_signed', 'contract_signed_source')
    def _compute_kjr_sign_state(self):
        for rec in self:
            req = rec.sudo().kjr_sign_request_id
            if rec.contract_signed and rec.contract_signed_source == 'paper' \
                    and req and req.state != 'signed':
                # Papierweg ersetzt eine abgelehnte, abgelaufene oder offene
                # Anfrage: kein rotes "Abgelehnt"/"Abgelaufen" neben "Papier".
                rec.kjr_sign_state = 'canceled'
            elif rec.kjr_sign_refused:
                # Abgelehnt hat Vorrang: Odoo Sign storniert die Anfrage bei der
                # Ablehnung intern (sign.request._refuse -> cancel).
                rec.kjr_sign_state = 'refused'
            elif not req:
                rec.kjr_sign_state = 'none'
            else:
                rec.kjr_sign_state = SIGN_STATE_MAP.get(req.state, 'none')

    @api.depends('facility_id.kjr_sign_disabled')
    def _compute_kjr_sign_available(self):
        enabled = self._kjr_sign_globally_enabled()
        for rec in self:
            rec.kjr_sign_available = enabled and not rec.sudo().facility_id.kjr_sign_disabled

    def _kjr_sign_portal_url_for(self, user):
        """Portal-Link '/my/signature/<id>' NUR für den Unterzeichner selbst.

        ``user`` ist der ANGEMELDETE Betrachter (im Template
        ``request.env.user``), nie ``self.env.user``: der Portal-Controller
        reicht die Buchung aus ``_document_check_access`` als
        ``with_user(SUPERUSER_ID)`` (odoo-19 portal/controllers/portal.py), dort
        wäre env.user der Superuser.

        Die Route verlangt item.partner_id == Benutzer und is_mail_sent
        (ent-19 sign/controllers/portal.py, portal_my_signature). Bewusst NIE
        der Bearer-Link aus _get_sign_and_cancel_links.
        """
        self.ensure_one()
        if not user or user._is_public() or self.kjr_sign_state != 'sent':
            return False
        partner = user.sudo().partner_id
        item = self.sudo().kjr_sign_request_id.request_item_ids[:1]
        if partner and item and item.partner_id == partner and item.is_mail_sent \
                and item.state == 'sent':
            return item.access_url
        return False

    # ------------------------------------------------------------------
    # Modus / Parameter
    # ------------------------------------------------------------------
    @api.model
    def _kjr_sign_globally_enabled(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(PARAM_ENABLED) or ''
        return str2bool(raw, False)

    def _kjr_sign_mode_active(self):
        self.ensure_one()
        return self._kjr_sign_globally_enabled() and not self.sudo().facility_id.kjr_sign_disabled

    @api.model
    def _kjr_sign_param_int(self, key, default):
        raw = self.env['ir.config_parameter'].sudo().get_param(key)
        if raw in (None, False, ''):
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            _logger.warning('KJR Einrichtung Sign: Systemparameter %s ungültig, Standard %s.',
                            key, default)
            return default

    # ------------------------------------------------------------------
    # Erweiterungsstelle Vertragsversand (kjr_facility 19.0.7.4.0)
    # ------------------------------------------------------------------
    def _send_contract(self):
        """Unterschriftsanfrage statt Vertragsmail, wenn eingeschaltet.

        Wirft NIE: Fehler führen zum bisherigen Mailversand plus Aufgabe. Der
        Savepoint wird bewusst AUSSERHALB des try geöffnet (er schreibt beim
        Öffnen offene Änderungen in die Datenbank; ein Fehler dabei darf nicht
        als "Anfrage fehlgeschlagen" verbucht werden).
        """
        self.ensure_one()
        if not self._kjr_sign_mode_active() or self.contract_signed:
            return super()._send_contract()
        savepoint = self.env.cr.savepoint()
        try:
            with savepoint:
                self._kjr_sign_create_request()
            return None
        except UserError as err:
            # Nur feste Texte (eigene bzw. aus Odoo Sign); landen ausschließlich
            # in der internen Aufgabe, nie im Protokoll.
            reason = str(err)
        except Exception as err:  # noqa: BLE001 - Rückfall auf Mail darf den Workflow nicht blockieren
            _logger.warning(
                'KJR Einrichtung Sign: Unterschriftsanfrage für Buchung %s fehlgeschlagen (%s), '
                'Rückfall auf Mailversand.', self.id, type(err).__name__,
                exc_info=_logger.isEnabledFor(logging.DEBUG))
            reason = _('Technischer Fehler beim Anlegen der Unterschriftsanfrage.')
        self._kjr_sign_activity(
            _('Vertrag ohne digitale Unterschrift versendet: %s', self.name),
            _('Die Unterschriftsanfrage konnte nicht angelegt werden (%s). Der Vertrag wurde '
              'wie bisher als PDF per Mail verschickt.', reason))
        return super()._send_contract()

    # ------------------------------------------------------------------
    # Anfrage anlegen
    # ------------------------------------------------------------------
    def _kjr_sign_create_request(self):
        """Legt Vorlage (Einmal-Vorlage, archiviert) und Anfrage an.

        Wirft UserError mit festen Texten. Die Sign-Mail landet in der
        Mail-Warteschlange (force_send=False) und wird bei einem Rollback mit
        zurückgenommen.
        """
        self.ensure_one()
        bk = self.sudo()
        bk._kjr_sign_cancel_open_requests('resend')        # höchstens eine offene Anfrage
        sender = bk._kjr_sign_sender_user()
        partner = bk._kjr_sign_signer_partner()
        company = bk.company_id or self.env.company
        pdf, page_w, page_h = bk._kjr_sign_contract_pdf()
        clean_ctx = {k: v for k, v in self.env.context.items() if not k.startswith('default_')}

        Template = self.env['sign.template'].with_user(sender).sudo().with_context(clean_ctx)
        doc_name = _('Buchungsvertrag_%s_digital.pdf', (bk.name or '').replace('/', '-'))
        res = Template.create_from_attachment_data(
            [{'name': doc_name, 'datas': base64.b64encode(pdf)}], active=False)
        template = Template.browse(res['id'])
        doc = template.document_ids[:1]
        page = doc.num_pages
        if page < 2:
            raise UserError(_('Das Vertrags-PDF für die Unterschrift ist unvollständig.'))
        role = self.env.ref(XMLID_ROLE)
        self.env['sign.item'].with_user(sender).sudo().with_context(clean_ctx).create(
            bk._kjr_sign_item_vals(doc, page, page_w, page_h, role))

        reminder_days = bk._kjr_sign_param_int(PARAM_REMINDER, DEFAULT_REMINDER_DAYS)
        SignRequest = self.env['sign.request'].with_user(sender).sudo().with_context(
            clean_ctx, force_send=False)
        req = SignRequest.create({
            'template_id': template.id,
            'reference': _('Buchungsvertrag %s', bk.name),
            'subject': _('Bitte unterschreiben: Buchungsvertrag %s', bk.name),
            'message': bk._kjr_sign_message(company),
            'reference_doc': '%s,%d' % (bk._name, bk.id),
            'validity': bk._kjr_sign_validity(),
            'reminder_enabled': reminder_days > 0,
            'reminder': reminder_days if reminder_days > 0 else 7,
            'communication_company_id': company.id,
            'request_item_ids': [Command.create({
                'partner_id': partner.id,
                'role_id': role.id,
                'mail_sent_order': 1,
            })],
            # Kennzeichen der Brücke: nur diese Anfragen wirken auf die Buchung
            # und fallen unter den Lauf für verwaiste Anfragen.
            'kjr_facility_contract': True,
        })
        bk.write({
            'kjr_sign_request_id': req.id,
            'kjr_sign_refused': False,
            # Idempotent zu action_confirm; nötig für "Unterschrift anfordern".
            'contract_sent_date': fields.Date.context_today(self),
            # Papier-Nachfass (kjr_facility._cron_contract_followup) unterdrücken:
            # der Mieter hat keine Vertragsmail bekommen, Odoo Sign erinnert selbst.
            'contract_followup_sent': True,
        })
        bk.message_post(
            body=Markup('<p>%s</p>') % _('Unterschriftsanfrage zum Vertrag versendet (Anfrage %s).',
                                         req.id),
            subtype_xmlid='mail.mt_note')
        return req

    def _kjr_sign_validity(self):
        """Gültig bis: höchstens ``validity_days`` ab heute, spätestens am Tag
        vor der Anreise, mindestens aber bis morgen."""
        self.ensure_one()
        days = self._kjr_sign_param_int(PARAM_VALIDITY, DEFAULT_VALIDITY_DAYS)
        if days < 1:
            days = DEFAULT_VALIDITY_DAYS
        today = fields.Date.context_today(self)
        validity = today + timedelta(days=days)
        if self.check_in:
            validity = min(validity, self.check_in - timedelta(days=1))
        return max(validity, today + timedelta(days=1))

    def _kjr_sign_message(self, company):
        """Begleittext der Sign-Mail. Ohne Gruppen-/Personennamen und Beträge,
        Firmenname aus der Gesellschaft der Buchung (White-Label)."""
        self.ensure_one()
        bk = self.sudo()
        return Markup('<p>%s</p><p>%s</p><p>%s</p>') % (
            _('Guten Tag,'),
            _('über den folgenden Link können Sie den Buchungsvertrag Nr. %(nr)s für '
              '%(facility)s (%(von)s bis %(bis)s) von %(company)s prüfen und auf der letzten '
              'Seite digital unterschreiben (Ort, Datum, Unterschrift).',
              nr=bk.name or '',
              facility=bk.facility_id.name or '',
              von=bk.check_in.strftime('%d.%m.%Y') if bk.check_in else '',
              bis=bk.check_out.strftime('%d.%m.%Y') if bk.check_out else '',
              company=company.name or ''),
            _('Kennen Sie diese Buchung nicht oder sind Sie nicht berechtigt, für die Gruppe '
              'zu unterschreiben, unterschreiben Sie bitte nicht und melden Sie sich bei uns.'),
        )

    # ------------------------------------------------------------------
    # Unterzeichner und Absender
    # ------------------------------------------------------------------
    def _kjr_sign_recipient_email(self):
        """Gleiche Quelle wie email_to der Mailvorlagen von kjr_facility."""
        self.ensure_one()
        bk = self.sudo()
        return email_normalize(bk.contact_email or bk.partner_id.email or '') or False

    def _kjr_sign_signer_partner(self):
        """Kontakt der unterschreibenden Person.

        Reihenfolge:
        0. der buchende Portalbenutzer (Website-Buchung: create_uid), wenn
           dessen E-Mail passt;
        1. ein Personen-Kontakt unter der eigenen Organisation mit dieser
           E-Mail (Kontakte mit Benutzerkonto zuerst, dann der älteste);
        2. sonst ein neuer Kontakt (unter der Organisation, falls diese eine
           Firma ist) mit der Kategorie "KJR Vertragsunterzeichner".
        Fremde Kontakte mit gleicher E-Mail werden bewusst NICHT genommen,
        Firmen nie (unterschreiben muss eine Person). Bestehende Kontakte werden
        nie geändert.
        """
        self.ensure_one()
        bk = self.sudo()
        email = bk._kjr_sign_recipient_email()
        if not email:
            raise UserError(_('Für die Unterschriftsanfrage fehlt eine E-Mail-Adresse '
                              '(Ansprechpartner/in oder Mieter).'))
        Partner = self.env['res.partner'].sudo()
        commercial = bk.partner_id.commercial_partner_id
        creator = bk.create_uid
        if creator.share and creator.partner_id.email_normalized == email:
            return creator.partner_id
        candidates = Partner.search([
            ('id', 'child_of', commercial.id),
            ('email_normalized', '=', email),
            ('is_company', '=', False),
        ], order='id')
        if candidates:
            with_user = candidates.filtered('user_ids')
            return (with_user or candidates)[:1]
        name = ' '.join((bk.contact_person or '').split()) or email
        vals = {
            'name': name,
            'email': email,
            'type': 'contact',
            'parent_id': commercial.id if commercial.is_company else False,
            'category_id': [Command.link(self.env.ref(XMLID_SIGNER_CATEGORY).id)],
            'company_id': False,
        }
        if self.env['res.lang'].sudo().search_count([('code', '=', 'de_DE')]):
            vals['lang'] = 'de_DE'
        return Partner.create(vals)

    def _kjr_sign_sender_user(self):
        """Erster geeigneter Absender (aktiver interner Benutzer mit E-Mail).

        Reihenfolge: Systemparameter, verantwortliche Person der Einrichtung,
        der handelnde interne Benutzer, der Administrator. Odoo Sign verlangt
        eine E-Mail-Adresse des Absenders (sign.request._check_senders_validity).
        """
        self.ensure_one()
        Users = self.env['res.users'].sudo()
        candidates = []
        raw = self.env['ir.config_parameter'].sudo().get_param(PARAM_SENDER)
        if raw:
            try:
                candidates.append(Users.browse(int(raw)).exists())
            except (TypeError, ValueError):
                _logger.warning('KJR Einrichtung Sign: Systemparameter %s ungültig.', PARAM_SENDER)
        candidates.append(self.sudo().facility_id.responsible_user_id)
        if not self.env.user.share:
            candidates.append(self.env.user)
        candidates.append(self.env.ref('base.user_admin', raise_if_not_found=False) or Users)
        for user in candidates:
            user = user.sudo()
            if user and user.active and not user.share and user.email_formatted:
                return user
        raise UserError(_('Kein Absender mit E-Mail-Adresse für Unterschriftsanfragen eingerichtet.'))

    # ------------------------------------------------------------------
    # PDF: Vertrag + Unterschriftsseite
    # ------------------------------------------------------------------
    def _kjr_sign_contract_pdf_base(self):
        """Aktuell gerendertes Vertrags-PDF (wie Druck und Vertragsmail)."""
        self.ensure_one()
        content, report_type = self.env['ir.actions.report'].sudo()._render_qweb_pdf(
            REPORT_CONTRACT, res_ids=[self.id])
        # Im Testmodus liefert Odoo HTML statt PDF (ir_actions_report._pre_render_qweb_pdf).
        if report_type != 'pdf' or not content or not content.startswith(b'%PDF'):
            raise UserError(_('Das Vertrags-PDF konnte nicht erzeugt werden.'))
        return content

    def _kjr_sign_contract_pdf(self):
        """-> (pdf_bytes, page_w_pt, page_h_pt); Seitengröße = letzte Vertragsseite."""
        self.ensure_one()
        base = self._kjr_sign_contract_pdf_base()
        reader = PdfFileReader(io.BytesIO(base), strict=False)
        pages = reader.getNumPages()
        if pages < 1:
            raise UserError(_('Das Vertrags-PDF hat ein nicht unterstütztes Seitenformat.'))
        last = reader.getPage(pages - 1)
        rotate = last.get('/Rotate', 0) or 0
        try:
            rotated = int(rotate) % 360
        except (TypeError, ValueError):
            rotated = 1
        if rotated:
            raise UserError(_('Das Vertrags-PDF hat ein nicht unterstütztes Seitenformat.'))
        # Gleiche Zugriffe wie Odoo Sign (sign_document.render_document_with_items);
        # die Kompatibilitätsschicht odoo.tools.pdf bildet sie für alle pypdf-Versionen ab.
        width = float(abs(last.mediaBox.getWidth()))
        height = float(abs(last.mediaBox.getHeight()))
        page_pdf = sign_page.build_signature_page(width, height, self._kjr_sign_page_texts(pages))
        return merge_pdf([base, page_pdf]), width, height

    def _kjr_sign_page_texts(self, contract_pages):
        """Texte der Unterschriftsseite (übersetzbar hier, sign_page bleibt ohne env).

        TODO(KJR): Wortlaut der Erklärung freigeben.
        """
        self.ensure_one()
        bk = self.sudo()

        def fmt(day):
            return day.strftime('%d.%m.%Y') if day else ''

        party = bk.partner_id.name or ''
        if bk.group_name:
            party = '%s, %s' % (party, bk.group_name) if party else bk.group_name
        nr = bk.name or ''
        return {
            'nr': nr,
            'facility': bk.facility_id.name or '',
            'period': _('%(von)s bis %(bis)s', von=fmt(bk.check_in), bis=fmt(bk.check_out)),
            'party': party,
            'company': (bk.company_id or self.env.company).name or '',
            'pages': contract_pages,
            'title': _('Unterschrift zum Buchungsvertrag %s', nr),
            'label_facility': _('Einrichtung'),
            'label_period': _('Zeitraum'),
            'label_party': _('Mieter / Gruppe'),
            'label_company': _('Vermieter'),
            'declaration': _(
                'Mit meiner Unterschrift auf dieser Seite erkenne ich den vorstehenden '
                'Buchungsvertrag Nr. %(nr)s (Seiten 1 bis %(n)s) für die genannte Gruppe an. '
                'Diese Seite ersetzt die Unterschriftszeile „Mieter / Gruppe“ im Vertrag.',
                nr=nr, n=contract_pages),
            'label_place': _('Ort'),
            'label_date': _('Datum'),
            'label_signature': _('Unterschrift'),
            'caption': _('Unterschrift der Mieterin / des Mieters bzw. der bevollmächtigten Person'),
            'footer_page': _('Seite %s', contract_pages + 1),
        }

    def _kjr_sign_item_vals(self, doc, page, page_w, page_h, role):
        """sign.item-Werte (Ort, Datum, Unterschrift) auf der letzten Seite."""
        types = {
            'place': self.env.ref('sign.sign_item_type_text'),
            'date': self.env.ref('sign.sign_item_type_date'),
            'signature': self.env.ref('sign.sign_item_type_signature'),
        }
        names = {'place': _('Ort'), 'date': _('Datum'), 'signature': _('Unterschrift')}
        return [{
            'document_id': doc.id,
            'type_id': types[geo['key']].id,
            'responsible_id': role.id,
            'required': True,
            'name': names[geo['key']],
            'page': page,
            'posX': geo['posX'],
            'posY': geo['posY'],
            'width': geo['width'],
            'height': geo['height'],
            'alignment': 'left',
        } for geo in sign_page.field_geometry(page_w, page_h)]

    # ------------------------------------------------------------------
    # Offene Anfragen, Aufgaben, Rechte
    # ------------------------------------------------------------------
    def _kjr_sign_open_requests(self):
        return self.sudo().kjr_sign_request_id.filtered(lambda r: r.state == 'sent')

    def _kjr_sign_cancel_open_requests(self, reason):
        """Storniert offene Anfragen; ``reason`` wählt nur einen festen Notiztext
        (sign.request._kjr_facility_cancel_note)."""
        for rec in self:
            open_reqs = rec._kjr_sign_open_requests()
            if open_reqs:
                open_reqs.with_context(kjr_facility_sign_cancel_reason=reason).sudo().cancel()

    def _kjr_sign_activity(self, summary, note):
        """Aufgabe für die Geschäftsstelle (dedupliziert über den Betreff)."""
        self.ensure_one()
        bk = self.sudo()
        if bk._has_open_activity(summary):
            return
        user = bk.facility_id.responsible_user_id
        if not user or user.share or not user.active:
            user = self.env.ref('base.user_admin', raise_if_not_found=False) or self.env.user
        bk.activity_schedule(
            'mail.mail_activity_data_todo',
            date_deadline=fields.Date.context_today(self),
            summary=summary, note=note, user_id=user.id)

    def _kjr_sign_notify_problem(self, kind):
        """kind in ('refused', 'expired'): Notiz + Aufgabe, ohne Begründungstext."""
        self.ensure_one()
        if kind == 'refused':
            note = _('Unterschrift des Vertrags abgelehnt.')
            summary = _('Vertragsunterschrift abgelehnt: %s', self.name)
        else:
            note = _('Unterschriftsanfrage zum Vertrag abgelaufen.')
            summary = _('Vertragsunterschrift abgelaufen: %s', self.name)
        self.sudo().message_post(body=Markup('<p>%s</p>') % note, subtype_xmlid='mail.mt_note')
        self._kjr_sign_activity(
            summary,
            _('Bitte Kontakt aufnehmen und entscheiden: Unterschrift erneut anfordern, '
              'Vertrag auf Papier oder Storno.'))

    def _kjr_sign_check_button_access(self):
        self.check_access('write')
        if not self.env.user.has_group('kjr_facility.group_kjr_facility_user'):
            raise AccessError(_('Nur Mitarbeitende der Einrichtungsverwaltung dürfen das.'))

    def _kjr_sign_check_sendable(self, allow_states):
        self.ensure_one()
        if not self._kjr_sign_mode_active():
            raise UserError(_('Die digitale Vertragsunterschrift ist für diese Einrichtung '
                              'nicht eingeschaltet.'))
        if self.state not in SIGNABLE_BOOKING_STATES:
            raise UserError(_('Eine Unterschrift kann nur für gebuchte Buchungen angefordert werden.'))
        if self.contract_signed:
            raise UserError(_('Der Vertrag ist bereits unterschrieben.'))
        if self.kjr_sign_state not in allow_states:
            raise UserError(_('Für diese Buchung ist dieser Schritt im aktuellen Stand nicht möglich.'))

    # ------------------------------------------------------------------
    # Schaltflächen
    # ------------------------------------------------------------------
    def action_kjr_sign_request_send(self):
        """Unterschrift anfordern (noch keine Anfrage). Fehler sind sichtbar."""
        self._kjr_sign_check_button_access()
        for rec in self:
            rec._kjr_sign_check_sendable(allow_states=('none',))
            rec._kjr_sign_create_request()
        return True

    def action_kjr_sign_request_resend(self):
        """Unterschrift erneut anfordern; storniert eine offene Anfrage selbst."""
        self._kjr_sign_check_button_access()
        for rec in self:
            rec._kjr_sign_check_sendable(allow_states=('sent', 'refused', 'expired', 'canceled'))
            rec._kjr_sign_create_request()
        return True

    def action_kjr_sign_request_cancel(self):
        """Offene Anfrage stornieren. contract_followup_sent bleibt gesetzt: kein
        automatischer Papier-Nachfass (der Mieter bekam keine Vertragsmail); die
        Geschäftsstelle entscheidet (neu anfordern oder Papier)."""
        self._kjr_sign_check_button_access()
        self._kjr_sign_cancel_open_requests('manual')
        return True

    def action_kjr_contract_paper(self):
        """„Vertrag liegt unterschrieben vor (Papier)“.

        Der write-Override setzt Datum und Quelle 'paper' und storniert offene
        Anfragen.
        """
        self._kjr_sign_check_button_access()
        self.filtered(lambda r: not r.contract_signed).write({'contract_signed': True})
        return True

    def action_kjr_open_sign_request(self):
        """Smart-Button. Ein einfacher Sign-Benutzer darf nur Anfragen lesen, die
        er angelegt hat, denen er folgt oder die er unterschreibt (ent-19 sign
        security.xml, ir_rule_sign_request_group_sign_user_*); angelegt wird
        die Anfrage im Namen des Absenders. Statt eines technischen
        Zugriffsfehlers kommt ein klarer Hinweis."""
        self.ensure_one()
        req = self.kjr_sign_request_id          # Feld nur für sign.group_sign_user
        try:
            req.check_access('read')
        except AccessError:
            raise UserError(_(
                'Die Unterschriftsanfrage können nur der Absender, ihre Follower und '
                'Sign-Administratoren öffnen. Stand und unterschriebenes PDF stehen an der '
                'Buchung (Chatter).')) from None
        return {
            'type': 'ir.actions.act_window',
            'name': _('Unterschriftsanfrage'),
            'res_model': 'sign.request',
            'view_mode': 'form',
            'res_id': req.id,
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------
    def write(self, vals):
        changed = self.browse()
        if 'contract_signed' in vals:
            new = bool(vals['contract_signed'])
            changed = self.filtered(lambda r: bool(r.contract_signed) != new)
        res = super().write(vals)
        if changed:
            if vals['contract_signed']:
                today = fields.Date.context_today(self)
                # "Digital" nur mit Beleg: der Kontextschlüssel allein genügt NICHT
                # (er kommt per RPC ungeprüft vom Client); die aktuelle Anfrage der
                # Buchung muss tatsächlich unterschrieben sein (sign.request._sign
                # setzt state='signed' vor unserem Hook).
                hint = bool(self.env.context.get('kjr_facility_sign_digital'))
                digital = changed.filtered(
                    lambda r: hint and r.sudo().kjr_sign_request_id.state == 'signed')
                paper = changed - digital
                if digital:
                    digital.write({'contract_signed_date': today,
                                   'contract_signed_source': 'digital'})
                if paper:
                    paper.write({
                        'contract_signed_date': today,
                        'contract_signed_source': 'paper',
                        # Eine frühere Ablehnung ist mit dem Papiervertrag erledigt.
                        'kjr_sign_refused': False,
                    })
                    # Häkchen von Hand bzw. Papier-Knopf = Papierweg.
                    paper._kjr_sign_cancel_open_requests('paper')
            else:
                changed.write({'contract_signed_date': False, 'contract_signed_source': False})
        return res

    def action_cancel(self):
        res = super().action_cancel()
        self._kjr_sign_cancel_open_requests('booking_cancel')
        return res

    def action_reset_draft(self):
        had_sign = self.filtered(lambda r: r.sudo().kjr_sign_request_id)
        res = super().action_reset_draft()
        self._kjr_sign_cancel_open_requests('booking_reset')
        # Bei erneutem "Verbindlich buchen" ohne Sign wirkt der Papier-Nachfass wieder.
        had_sign.filtered(lambda r: not r.contract_signed).write({'contract_followup_sent': False})
        return res

    def unlink(self):
        self.with_context(kjr_facility_sign_no_note=True)._kjr_sign_cancel_open_requests(
            'booking_delete')
        return super().unlink()

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------
    @api.model
    def _cron_kjr_facility_sign(self):
        """Storniert offene Vertragsanfragen der Brücke, deren Buchung fehlt,
        storniert ist oder die Anfrage nicht mehr als aktuelle führt.

        Nur Anfragen mit ``kjr_facility_contract``: andere Anfragen, die die
        Geschäftsstelle über Odoo Sign mit einer Buchung verknüpft (reference_doc
        ist für jedes Modell mit Chatter wählbar), bleiben unberührt.

        Ablauf und Ablehnung brauchen keinen Cron (Hooks in sign.request).
        Das CASE verhindert Cast-Fehler bei fremden reference_doc-Formaten.
        """
        self.env.flush_all()
        self.env.cr.execute(SQL(
            """
            SELECT sr.id
              FROM sign_request sr
         LEFT JOIN kjr_facility_booking b
                ON b.id = CASE WHEN sr.reference_doc ~ %(rx)s
                               THEN split_part(sr.reference_doc, ',', 2)::int END
             WHERE sr.state = 'sent'
               AND sr.kjr_facility_contract
               AND sr.reference_doc LIKE %(prefix)s
               AND (b.id IS NULL OR b.state = 'cancelled'
                    OR b.kjr_sign_request_id IS DISTINCT FROM sr.id)
            """,
            rx=r'^kjr\.facility\.booking,[0-9]+$',
            prefix='kjr.facility.booking,%',
        ))
        ids = [row[0] for row in self.env.cr.fetchall()]
        if ids:
            self.env['sign.request'].sudo().browse(ids).with_context(
                kjr_facility_sign_cancel_reason='orphan').cancel()
        _logger.info('KJR Einrichtung Sign: %d verwaiste Unterschriftsanfragen storniert.', len(ids))
