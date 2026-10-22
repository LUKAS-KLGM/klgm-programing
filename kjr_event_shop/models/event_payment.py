# -*- coding: utf-8 -*-
"""Zahlungsablauf Ferienprogramm (Termin 13.10.2026), 19.0.2.2.0.

Schon vorhanden (event_sale + kjr_event_shop): Eine Anmeldung zu einem
kostenpflichtigen Ticket bleibt unbestätigt ('draft', nicht auf der
Teilnehmerliste), bis der Auftrag bestätigt ist; bei Überweisung bestätigt die
Geschäftsstelle den Auftrag nach Zahlungseingang von Hand ("Bestätigen") oder
setzt Sonderfälle direkt auf die Liste. Ergänzt wird hier nur:

* Rechnungs-/Kontaktpartner der Anmeldung auf den Auftrag übertragen
  (Rechnung an Erziehungsberechtigte bzw. volljährige Teilnehmer:in, mit
  Anschrift);
* Rechnung automatisch beim Bestätigen des Auftrags (Entscheidung 13.10.:
  "Rechnung automatisch: ja"); gebucht nur mit kjr_event.invoice_auto_post,
  versendet wird nichts;
* genau EINE Zahlungserinnerung nach einer konfigurierbaren Frist, danach
  Platz freigeben (Auftrag storniert, Anmeldung abgesagt) und, falls
  vorhanden, die Warteliste nachrücken lassen. Der Cron wird INAKTIV
  ausgeliefert und die Fristen stehen auf 0 (= aus): bis zum Start geht nichts
  automatisch hinaus;
* Steuer auf Teilnahmegebühren aus den Einstellungen (kjr_event.fee_tax_id).
"""
import logging
from datetime import timedelta

from markupsafe import Markup

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

PARAM_REMINDER_DAYS = 'kjr_event_shop.payment_reminder_days'
PARAM_RELEASE_DAYS = 'kjr_event_shop.payment_release_days'
PARAM_INVOICE_ON_CONFIRM = 'kjr_event_shop.invoice_on_confirm'
PARAM_INVOICE_AUTO_POST = 'kjr_event.invoice_auto_post'


class EventRegistrationPayment(models.Model):
    _inherit = 'event.registration'

    def _kjr_apply_invoice_partner(self):
        """Einen NEU angelegten Rechnungskontakt zusätzlich an den Warenkorb.

        Nur solange der Auftrag ein Warenkorb ist und nur mit einem Kontakt,
        der in DIESEM Aufruf neu angelegt wurde (Prüfbericht 22.10.2026: ein
        wiederverwendeter Kontakt bleibt nur an der Anmeldung, der Warenkorb
        bleibt unverändert). Gastbuchung (Kunde ist der öffentliche Kontakt
        oder der von website_event_sale angelegte Kontakt ohne Konto und
        Anschrift): Kunde UND Rechnungsadresse werden der neue Kontakt; der
        Checkout fragt die Anschrift dann nicht erneut ab. Kund:innen mit Konto
        behalten ihren Kontakt als Kunde, nur die Rechnungsadresse wechselt.
        """
        created = super()._kjr_apply_invoice_partner()
        for rec in self.sudo():
            order = rec.sale_order_id
            partner = rec.kjr_invoice_partner_id
            if not order or not partner or partner not in created or order.state != 'draft':
                continue
            try:
                with self.env.cr.savepoint():
                    customer = order.partner_id
                    public = order.website_id.user_id.partner_id
                    if (public and customer == public) or (
                            not customer.user_ids and not customer.street):
                        order.partner_id = partner
                    order.partner_invoice_id = partner
            except Exception:  # noqa: BLE001 - die Anmeldung hat Vorrang
                _logger.exception('KJR-Anmeldung %s: Rechnungskontakt nicht auf Auftrag %s '
                                  'übertragen.', rec.id, order.id)
        return created

    def _kjr_unpaid_order(self):
        """Auftrag dieser Anmeldung, wenn er noch auf Zahlung wartet, sonst leer."""
        self.ensure_one()
        order = self.sudo().sale_order_id
        if order and order.state in ('draft', 'sent') and order.amount_total > 0 \
                and not order._kjr_is_paid():
            return order
        return self.env['sale.order']

    def _kjr_promote_keeps_draft(self):
        """Unbezahlter Auftrag: nachrücken, aber erst nach Zahlung bestätigen.

        Ohne diesen Zweig schriebe das Nachrücken 'open' direkt an die
        Anmeldung; der Status-Compute von event_sale liefe dabei nicht erneut,
        und eine unbezahlte Anmeldung stünde auf der Teilnehmerliste
        (Prüfbericht 22.10.2026).
        """
        return bool(self._kjr_unpaid_order()) or super()._kjr_promote_keeps_draft()

    def action_kjr_promote_waitlist(self):
        """Nachrücker mit offenem Auftrag: Zahlungsfrist beginnt neu."""
        res = super().action_kjr_promote_waitlist()
        orders = self.sudo().filtered(lambda r: not r.kjr_is_waitlist).sale_order_id.filtered(
            lambda o: o.state in ('draft', 'sent'))
        if orders:
            orders.write({'kjr_payment_requested_date': fields.Datetime.now(),
                          'kjr_payment_reminder_date': False})
        return res


class EventEventPayment(models.Model):
    _inherit = 'event.event'

    def _kjr_unpaid_reserved_count(self):
        """Unbezahlte Shop-Anmeldungen mit abgeschlossener Bestellung.

        Sie stehen im Kern unbestätigt ('draft') und zählen dort nicht auf die
        belegten Plätze. Damit die Zahlungsfrist einen Platz wirklich
        freihält und die Platzfreigabe einen Platz freigibt (Prüfbericht
        22.10.2026), reservieren sie hier einen Platz. Nur Bestellungen im
        Status "gesendet" (Checkout abgeschlossen); abgebrochene Warenkörbe
        reservieren nichts.
        """
        self.ensure_one()
        if not self._origin.id:
            return 0
        return self.env['event.registration'].sudo().search_count([
            ('event_id', '=', self._origin.id),
            ('state', '=', 'draft'),
            ('kjr_is_waitlist', '=', False),
            ('kjr_consent_hold', '=', False),
            ('sale_order_id.state', '=', 'sent'),
            ('sale_status', '=', 'to_pay'),
        ])

    def _kjr_free_seats(self):
        free = super()._kjr_free_seats()
        if free is None:
            return None
        return max(free - self._kjr_unpaid_reserved_count(), 0)


class SaleOrderPayment(models.Model):
    _inherit = 'sale.order'

    kjr_payment_requested_date = fields.Datetime(
        string='Zahlung angefordert am', copy=False, readonly=True,
        help='Zeitpunkt, ab dem die Zahlungsfrist läuft (Abschluss der Bestellung bzw. '
             'Nachrücken von der Warteliste).')
    kjr_payment_reminder_date = fields.Datetime(
        string='Zahlungserinnerung am', copy=False, readonly=True)
    kjr_payment_release_date = fields.Datetime(
        string='Platzfreigabe ab', compute='_compute_kjr_payment_release_date',
        help='Ohne Zahlungseingang bis zu diesem Zeitpunkt wird der Auftrag storniert '
             'und der Platz freigegeben (Zahlungserinnerung + Frist aus den Einstellungen).')

    @api.depends('kjr_payment_reminder_date')
    def _compute_kjr_payment_release_date(self):
        days = self._kjr_param_days(PARAM_RELEASE_DAYS)
        for order in self:
            order.kjr_payment_release_date = (
                order.kjr_payment_reminder_date + timedelta(days=days)
                if order.kjr_payment_reminder_date and days else False)

    def _kjr_kjr_event_lines(self):
        self.ensure_one()
        return self.order_line.filtered(lambda l: l.event_id and l.event_id.is_kjr)

    def write(self, vals):
        if vals.get('state') == 'sent':
            start = self.filtered(lambda o: not o.kjr_payment_requested_date
                                  and o.state != 'sent' and o._kjr_kjr_event_lines())
        else:
            start = self.browse()
        res = super().write(vals)
        if start:
            super(SaleOrderPayment, start).write(
                {'kjr_payment_requested_date': fields.Datetime.now()})
        return res

    # ------------------------------------------------------------------
    # Rechnung automatisch beim Bestätigen
    # ------------------------------------------------------------------
    def action_confirm(self):
        res = super().action_confirm()
        params = self.env['ir.config_parameter'].sudo()
        if params.get_param(PARAM_INVOICE_ON_CONFIRM, '0') in ('1', 'True', 'true'):
            self._kjr_invoice_on_confirm(
                post=params.get_param(PARAM_INVOICE_AUTO_POST, '0') in ('1', 'True', 'true'))
        return res

    def _kjr_invoice_on_confirm(self, post=False):
        """Rechnung für bestätigte Aufträge mit KJR-Veranstaltung; versendet nichts.

        Wirft nie: Fehler (z. B. fehlendes Erlöskonto) landen im Protokoll und
        als Notiz am Auftrag, die Bestätigung bleibt bestehen.
        """
        for order in self.sudo():
            if order.state != 'sale' or not order._kjr_kjr_event_lines() \
                    or order.amount_total <= 0 or order.invoice_status != 'to invoice':
                continue
            regs = order._kjr_kjr_event_lines().registration_ids.filtered(
                lambda r: r.state != 'cancel')
            if regs.filtered(lambda r: r.kjr_is_waitlist or r.kjr_consent_hold):
                # Wie beim Schulungspfad: Rechnung erst nach Nachrücken bzw.
                # Freigabe der Einwilligung, sonst bräuchte es eine Gutschrift.
                continue
            if order._kjr_is_paid() and self.env['ir.config_parameter'].sudo().get_param(
                    'sale.automatic_invoice'):
                # Online-Zahlung mit sale.automatic_invoice: Odoo fakturiert und
                # gleicht die Zahlung selbst ab (payment_transaction).
                continue
            savepoint = self.env.cr.savepoint()
            try:
                with savepoint:
                    moves = order._create_invoices()
                    if post:
                        moves.action_post()
            except Exception as e:  # noqa: BLE001 - die Bestätigung hat Vorrang
                _logger.exception('KJR: automatische Rechnung zu Auftrag %s fehlgeschlagen.',
                                  order.id)
                order.message_post(body=Markup('<p>%s</p>') % _(
                    'Die Rechnung konnte nicht automatisch erzeugt werden: %s. Bitte von Hand '
                    'erstellen.', e), subtype_xmlid='mail.mt_note')

    # ------------------------------------------------------------------
    # Zahlungserinnerung und Platzfreigabe
    # ------------------------------------------------------------------
    @api.model
    def _kjr_param_days(self, key):
        raw = self.env['ir.config_parameter'].sudo().get_param(key, '0')
        try:
            return max(int(str(raw).strip()), 0)
        except (TypeError, ValueError):
            _logger.warning('Systemparameter %s ist keine ganze Zahl (%r), Automatik aus.', key, raw)
            return 0

    def _kjr_payment_open(self):
        """True, wenn der Auftrag auf Zahlung wartet und erinnert/freigegeben werden darf.

        Nur abgeschlossene, unbezahlte Bestellungen ('sent') mit Betrag über 0
        zu KJR-Veranstaltungen, die noch nicht begonnen haben. Ausgenommen sind
        Aufträge mit Wartelistenplätzen oder gesperrten Anmeldungen (Einwilligung
        ausstehend): dort wartet nicht die Zahlung, sondern die Geschäftsstelle.
        Ausgenommen sind ferner Aufträge mit bereits bestätigten Anmeldungen:
        Sonderfälle, die die Geschäftsstelle von Hand auf die Liste gesetzt hat.
        """
        self.ensure_one()
        lines = self._kjr_kjr_event_lines()
        if self.state != 'sent' or not lines or self.amount_total <= 0 or self._kjr_is_paid():
            return False
        regs = lines.registration_ids.filtered(lambda r: r.state != 'cancel')
        if not regs or regs.filtered(lambda r: r.kjr_is_waitlist or r.kjr_consent_hold):
            return False
        if regs.filtered(lambda r: r.state in ('open', 'done')):
            # Von der Geschäftsstelle von Hand bestätigt (Sonderfall, z. B.
            # halber Preis, Entscheidung 1 vom 13.10.): keine Erinnerung,
            # keine Freigabe.
            return False
        now = fields.Datetime.now()
        return all(ev.date_begin and ev.date_begin > now for ev in lines.event_id)

    @api.model
    def _kjr_recompute_fee_taxes(self):
        """Steuer offener Auftragszeilen zu KJR-Veranstaltungen neu berechnen.

        Nur Warenkörbe und gesendete Angebote; bestätigte Aufträge und
        Rechnungen bleiben unberührt. Rückgabe: Anzahl der Zeilen.
        """
        lines = self.env['sale.order.line'].sudo().search([
            ('order_id.state', 'in', ('draft', 'sent')),
            ('event_id.is_kjr', '=', True),
        ])
        if lines:
            lines._compute_tax_ids()
        return len(lines)

    @api.model
    def _kjr_payment_cron_domain(self, now):
        """Vorauswahl für den Cron (Prüfbericht 22.10.2026).

        Schließt Aufträge, die _kjr_payment_open() dauerhaft ablehnen würde,
        schon in der Suche aus, damit sie das Kontingent (limit) nicht bei
        jedem Lauf erneut belegen: begonnene Veranstaltungen, erledigte
        Zahlung, Wartelisten-/gesperrte/bestätigte Anmeldungen.
        """
        return [
            ('state', '=', 'sent'),
            ('amount_total', '>', 0),
            ('order_line', 'any', [('event_id.is_kjr', '=', True)]),
            ('order_line', 'not any', [('event_id.date_begin', '<=', now)]),
            ('transaction_ids', 'not any', [('state', '=', 'done')]),
            ('order_line', 'not any', [('registration_ids', 'any', [
                ('state', '!=', 'cancel'),
                '|', '|', ('kjr_is_waitlist', '=', True), ('kjr_consent_hold', '=', True),
                ('state', 'in', ('open', 'done'))])]),
        ]

    @api.model
    def _cron_kjr_payment_reminder(self):
        """Eine Zahlungserinnerung, danach Platz freigeben (Termin 13.10.2026).

        Fristen in Tagen (Einstellungen → KJR Veranstaltungen → Zahlung):
        Erinnerung ``payment_reminder_days`` nach Abschluss der Bestellung,
        Freigabe ``payment_release_days`` nach der Erinnerung. 0 = aus.
        Der Cron selbst wird inaktiv ausgeliefert.
        """
        reminder_days = self._kjr_param_days(PARAM_REMINDER_DAYS)
        release_days = self._kjr_param_days(PARAM_RELEASE_DAYS)
        now = fields.Datetime.now()
        reminded = released = 0
        if reminder_days:
            orders = self.sudo().search(self._kjr_payment_cron_domain(now) + [
                ('kjr_payment_reminder_date', '=', False),
                ('kjr_payment_requested_date', '!=', False),
                ('kjr_payment_requested_date', '<=', now - timedelta(days=reminder_days)),
                ('partner_id.email', '!=', False),
            ], limit=200, order='id')
            for order in orders.filtered(lambda o: o._kjr_payment_open()):
                if order._kjr_send_payment_reminder():
                    reminded += 1
        if release_days:
            orders = self.sudo().search(self._kjr_payment_cron_domain(now) + [
                ('kjr_payment_reminder_date', '!=', False),
                ('kjr_payment_reminder_date', '<=', now - timedelta(days=release_days)),
            ], limit=200, order='id')
            for order in orders.filtered(lambda o: o._kjr_payment_open()):
                savepoint = self.env.cr.savepoint()
                try:
                    with savepoint:
                        order._kjr_release_unpaid()
                        released += 1
                except Exception:  # noqa: BLE001 - nächster Auftrag
                    _logger.exception('KJR: Platzfreigabe für Auftrag %s fehlgeschlagen.', order.id)
        _logger.info('KJR Zahlungserinnerung: %d erinnert, %d Plätze freigegeben.',
                     reminded, released)
        return reminded, released

    def _kjr_send_payment_reminder(self):
        """Versendet die (einzige) Zahlungserinnerung und merkt sie am Auftrag."""
        self.ensure_one()
        template = self.env.ref('kjr_event_shop.mail_template_payment_reminder',
                                raise_if_not_found=False)
        if not template or not self.partner_id.email:
            _logger.warning('KJR Zahlungserinnerung: Auftrag %s ohne Vorlage oder E-Mail.', self.id)
            return False
        # Merker VOR dem Versand: lieber keine als eine zweite Erinnerung.
        self.kjr_payment_reminder_date = fields.Datetime.now()
        try:
            template.send_mail(self.id, force_send=False)
        except Exception:  # noqa: BLE001 - Merker bleibt, Notiz zeigt den Fehler
            _logger.exception('KJR Zahlungserinnerung zu Auftrag %s nicht versendet.', self.id)
            self.message_post(body=_('Zahlungserinnerung konnte nicht versendet werden.'),
                              subtype_xmlid='mail.mt_note')
            return False
        return True

    def _kjr_release_unpaid(self):
        """Storniert den unbezahlten Auftrag und lässt die Warteliste nachrücken.

        Mit dem Auftrag sagt event_sale die Anmeldungen ab
        (_compute_registration_status). Danach rückt je betroffener
        Veranstaltung mit aktiver Warteliste die nächste wartende Anmeldung nach,
        höchstens so viele, wie der Auftrag Anmeldungen hatte, und nur, solange
        ein regulärer Platz frei ist (FIFO, gleicher Weg wie der Knopf
        "Nächste/n nachrücken"; bei kostenpflichtigen Plätzen beginnt dort die
        Zahlungsfrist neu).
        """
        self.ensure_one()
        lines = self._kjr_kjr_event_lines()
        events = lines.event_id
        released = {
            event: len(lines.registration_ids.filtered(
                lambda r, ev=event: r.event_id == ev and r.state != 'cancel'))
            for event in events}
        self._action_cancel()
        self.message_post(body=Markup('<p>%s</p>') % _(
            'Keine Zahlung nach der Zahlungserinnerung: Auftrag storniert, Platz freigegeben.'),
            subtype_xmlid='mail.mt_note')
        for event in events.filtered('kjr_waitlist_enabled'):
            # Höchstens so viele nachrücken lassen, wie dieser Auftrag Plätze
            # freigegeben hat.
            for _i in range(released.get(event, 0)):
                free = event._kjr_free_seats()
                waiting = event._kjr_waitlist_registrations()
                if not waiting or (free is not None and free <= 0):
                    break
                try:
                    with self.env.cr.savepoint():
                        event.action_kjr_promote_from_waitlist()
                except Exception:  # noqa: BLE001 - Nachrücken ist Nebensache
                    _logger.exception('KJR: Nachrücken für Veranstaltung %s fehlgeschlagen.',
                                      event.id)
                    break


class SaleOrderLineFeeTax(models.Model):
    _inherit = 'sale.order.line'

    @api.depends('event_id')
    def _compute_tax_ids(self):
        """Steuer auf Teilnahmegebühren (Einstellung) für KJR-Veranstaltungen."""
        super()._compute_tax_ids()
        for line in self.filtered('event_id'):
            taxes = line.event_id._kjr_fee_taxes()
            if taxes:
                line.tax_ids = line.order_id.fiscal_position_id.map_tax(taxes)
