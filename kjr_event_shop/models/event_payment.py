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
from odoo.tools.misc import format_amount, format_date

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
                    current = order.partner_invoice_id
                    if current != partner and current in rec._kjr_cart_siblings().kjr_invoice_partner_id:
                        # Prüfbericht 22.10.2026: gemischter Warenkorb mit
                        # verschiedenen Rechnungskontakten (z. B. eine
                        # minderjährige und eine volljährige Person). Der
                        # Auftrag kennt nur EINE Rechnungsadresse: es bleibt
                        # die der zuerst angemeldeten Person, statt mit jeder
                        # Anmeldung zu wechseln; die Geschäftsstelle sieht es
                        # in der Notiz.
                        order.message_post(body=_(
                            'Der Warenkorb enthält Anmeldungen mit verschiedenen '
                            'Rechnungskontakten (%(first)s, %(other)s). Rechnungsadresse '
                            'des Auftrags bleibt %(first)s; bei Bedarf aufteilen.',
                            first=current.display_name, other=partner.display_name),
                            subtype_xmlid='mail.mt_note')
                        continue
                    if (public and customer == public) or (
                            not customer.user_ids and not customer.street):
                        order.partner_id = partner
                    order.partner_invoice_id = partner
            except Exception:  # noqa: BLE001 - die Anmeldung hat Vorrang
                _logger.exception('KJR-Anmeldung %s: Rechnungskontakt nicht auf Auftrag %s '
                                  'übertragen.', rec.id, order.id)
        return created

    def _kjr_cart_siblings(self):
        """Andere Anmeldungen desselben Warenkorbs (Auftrag im Status 'draft')."""
        self.ensure_one()
        order = self.sudo().sale_order_id
        if not order or order.state != 'draft':
            return self.browse()
        return self.sudo().search([
            ('sale_order_id', '=', order.id), ('id', '!=', self.id),
            ('kjr_invoice_partner_id', '!=', False), ('state', '!=', 'cancel')])

    def _kjr_same_booking_invoice_partner(self, values):
        """Gleiche Erziehungsberechtigte bzw. Person im SELBEN Warenkorb nur einmal.

        Prüfbericht 22.10.2026: Meldet ein Elternteil Geschwister in einem
        Warenkorb an, entstand je Anmeldung ein eigener, gleicher Kontakt.
        Wiederverwendet wird nur ein Kontakt, der für eine andere Anmeldung
        DIESES Warenkorbs angelegt wurde und exakt passt (Name, E-Mail,
        Telefon, Anschrift). Die Datenschutzregel bleibt: bestehende Kontakte
        außerhalb des Warenkorbs werden bei Gästen nie gesucht.
        """
        partner = super()._kjr_same_booking_invoice_partner(values)
        if partner:
            return partner
        for candidate in self._kjr_cart_siblings().kjr_invoice_partner_id:
            if self._kjr_invoice_partner_matches(candidate, values):
                return candidate
        return partner

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

    kjr_seats_reserved_unpaid = fields.Integer(
        string='Reserviert (Zahlung offen)', compute='_compute_kjr_seats_reserved_unpaid',
        help='Plätze, die abgeschlossene, noch unbezahlte Bestellungen bzw. von der '
             'Warteliste Nachgerückte mit offener Zahlung freihalten. Sie zählen in Odoo '
             'nicht als belegt, werden bei der Platzvergabe aber berücksichtigt.')
    kjr_seats_overbooked = fields.Boolean(compute='_compute_kjr_seats_reserved_unpaid')

    def _compute_kjr_seats_reserved_unpaid(self):
        for event in self:
            reserved = event._kjr_unpaid_reserved_count()
            event.kjr_seats_reserved_unpaid = reserved
            limited = event.seats_limited if 'seats_limited' in event._fields else bool(event.seats_max)
            event.kjr_seats_overbooked = bool(
                limited and event.seats_max and reserved
                and event.seats_taken + reserved > event.seats_max)

    def _kjr_unpaid_reserved_count(self, exclude_order=None):
        """Unbezahlte Shop-Anmeldungen, die einen Platz freihalten.

        Sie stehen im Kern unbestätigt ('draft') und zählen dort nicht auf die
        belegten Plätze. Reserviert wird, sobald die Zahlung angefordert ist
        (``sale.order.kjr_payment_requested_date``): beim Abschluss der
        Bestellung (Status "gesendet") und beim Nachrücken von der Warteliste,
        auch wenn der Auftrag dann noch ein Warenkorb ist (Prüfbericht
        22.10.2026, sonst doppeltes Nachrücken). Abgebrochene Warenkörbe ohne
        Zahlungsanforderung reservieren nichts.
        """
        self.ensure_one()
        if not self._origin.id:
            return 0
        domain = [
            ('event_id', '=', self._origin.id),
            ('state', '=', 'draft'),
            ('kjr_is_waitlist', '=', False),
            ('kjr_consent_hold', '=', False),
            ('sale_order_id.state', 'in', ('draft', 'sent')),
            ('sale_order_id.kjr_payment_requested_date', '!=', False),
            ('sale_status', '=', 'to_pay'),
        ]
        if exclude_order:
            domain.append(('sale_order_id', 'not in', exclude_order.ids))
        return self.env['event.registration'].sudo().search_count(domain)

    def _kjr_free_seats(self, exclude_order=None):
        free = super()._kjr_free_seats()
        if free is None:
            return None
        return max(free - self._kjr_unpaid_reserved_count(exclude_order=exclude_order), 0)


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
            start._kjr_check_capacity_on_checkout()
        return res

    def _kjr_open_regs(self, event):
        """Anmeldungen dieses Auftrags zu ``event``, die einen Platz brauchen."""
        self.ensure_one()
        return self.sudo().order_line.registration_ids.filtered(
            lambda r: r.event_id == event and r.state == 'draft'
            and not r.kjr_is_waitlist and not r.kjr_consent_hold).sorted('id')

    def _kjr_move_to_waitlist(self, regs, summary, note):
        """Überzählige Anmeldungen auf die Warteliste, Notiz und Aktivität."""
        if not regs:
            return
        regs.sudo().write({'kjr_is_waitlist': True})
        for order in regs.sale_order_id:
            order.message_post(body=Markup('<p>%s</p>') % note, subtype_xmlid='mail.mt_note')
            try:
                order.sudo().activity_schedule(
                    'mail.mail_activity_data_todo', summary=summary, note=note,
                    user_id=(regs.event_id.user_id[:1] or self.env.ref('base.user_admin')).id)
            except Exception:  # noqa: BLE001 - die Aktivität ist Nebensache
                _logger.exception('KJR: Aktivität zu Auftrag %s nicht angelegt.', order.id)

    def _kjr_check_capacity_on_checkout(self):
        """Beim Abschluss der Bestellung erneut gegen die freien Plätze prüfen.

        Parallele Warenkörbe, Veranstaltungen ohne Warteliste oder von Hand
        bestätigte Sonderfälle können dazu führen, dass mehr Bestellungen
        abgeschlossen werden, als Plätze frei sind (Prüfbericht 22.10.2026).
        Überzählige Anmeldungen kommen auf die Warteliste; die
        Bestellbestätigung sagt das der bestellenden Person (statt einer
        Zahlungsaufforderung), die Geschäftsstelle bekommt eine Aktivität.
        """
        for order in self.sudo():
            for event in order._kjr_kjr_event_lines().event_id:
                free = event._kjr_free_seats(exclude_order=order)
                if free is None:
                    continue
                overflow = order._kjr_open_regs(event)[free:]
                order._kjr_move_to_waitlist(
                    overflow,
                    _('Bestellung über der Kapazität: Warteliste'),
                    _('"%(event)s" war beim Abschluss der Bestellung ausgebucht; '
                      '%(count)s Anmeldung(en) stehen jetzt auf der Warteliste. Bitte die '
                      'bestellende Person informieren (keine Zahlung anfordern).',
                      event=event.name, count=len(overflow)))

    # ------------------------------------------------------------------
    # Rechnung automatisch beim Bestätigen
    # ------------------------------------------------------------------
    def action_confirm(self):
        # Bestätigung nach Zahlungseingang darf nie an der Platzprüfung des
        # Kerns scheitern (event: _check_seats_availability). Sind mehr
        # Anmeldungen zu bestätigen, als im Kern Plätze frei sind (z. B. weil
        # die Geschäftsstelle einen Sonderfall über die Kapazität bestätigt
        # hat), kommen die überzähligen auf die Warteliste, mit Aktivität.
        for order in self.sudo().filtered(lambda o: o.state in ('draft', 'sent')):
            for event in order._kjr_kjr_event_lines().event_id:
                limited = event.seats_limited if 'seats_limited' in event._fields \
                    else bool(event.seats_max)
                if not limited or not event.seats_max:
                    continue
                available = max(event.seats_available, 0)
                overflow = order._kjr_open_regs(event)[available:]
                order._kjr_move_to_waitlist(
                    overflow,
                    _('Bezahlt, aber kein Platz frei: Warteliste'),
                    _('Beim Bestätigen von "%(event)s" war kein regulärer Platz frei; '
                      '%(count)s Anmeldung(en) stehen auf der Warteliste. Bitte über '
                      'Nachrücken oder Erstattung entscheiden.',
                      event=event.name, count=len(overflow)))
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
            lines.order_id._kjr_sync_transfer_amounts()
        return len(lines)

    def _kjr_stale_transfer_txs(self):
        """Offene Überweisungen, deren Betrag nicht mehr zum Auftrag passt.

        Nur Überweisung (payment_custom) im Status 'draft' oder 'pending', die
        genau zu diesem einen Auftrag gehört, bei offenem, unbezahltem Auftrag.
        Ausgenommen ist eine gewollte Anzahlung (Betrag = geforderte
        Vorauszahlung).
        """
        self.ensure_one()
        order = self.sudo()
        if order.state not in ('draft', 'sent') or order._kjr_is_paid():
            return self.env['payment.transaction']
        compare = order.currency_id.compare_amounts
        return order.transaction_ids.filtered(
            lambda t: t.provider_id.code == 'custom' and t.state in ('draft', 'pending')
            and t.sale_order_ids == order and t.currency_id == order.currency_id
            and compare(t.amount, order.amount_total) != 0
            and not (order.require_payment
                     and compare(t.amount, order._get_prepayment_required_amount()) == 0))

    def _kjr_sync_transfer_amounts(self):
        """Offene Überweisung auf den aktuellen Auftragsbetrag bringen.

        Prüfbericht 22.10.2026: Nach dem Wechsel der Steuer auf Teilnahmegebühren
        (19 % -> 0 %) standen offene Überweisungen noch auf dem alten
        Bruttobetrag (23,80 EUR), Auftrag, Reservierungsbestätigung und
        Zahlungserinnerung auf 20,00 EUR. Eine Überweisung (payment_custom) hat
        kein Gegenstück bei einem Zahlungsanbieter; der Datensatz hält nur die
        Zahlungsanweisung mit Referenz (Verwendungszweck) fest. Angeglichen wird
        deshalb der Betrag, Referenz und Status bleiben. So zeigt die
        Zahlungsanweisung den richtigen Betrag, und die Zahlung, die Odoo beim
        Bestätigen der Überweisung aus dem Transaktionsbetrag bucht
        (account_payment), passt zu Auftrag und Rechnung. Jede Änderung steht
        als Notiz am Auftrag. Rückgabe: angeglichene Transaktionen.
        """
        synced = self.env['payment.transaction']
        for order in self.sudo():
            txs = order._kjr_stale_transfer_txs()
            for tx in txs:
                old = tx.amount
                tx.amount = order.amount_total
                order.message_post(body=_(
                    'Offene Überweisung %(ref)s an den Auftragsbetrag angeglichen: '
                    '%(old)s -> %(new)s (Steuer auf Teilnahmegebühren geändert).',
                    ref=tx.reference,
                    old=format_amount(self.env, old, tx.currency_id),
                    new=format_amount(self.env, order.amount_total, order.currency_id)),
                    subtype_xmlid='mail.mt_note')
                synced |= tx
        if synced:
            _logger.info('KJR: Betrag offener Überweisungen angeglichen: %s', synced.ids)
        return synced

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
        if not self.partner_id.email:
            return self._kjr_payment_reminder_activity()
        if not template:
            _logger.warning('KJR Zahlungserinnerung: Auftrag %s ohne Vorlage.', self.id)
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

    def _kjr_payment_reminder_activity(self):
        """Erinnerung ohne E-Mail-Adresse: Aufgabe für die Geschäftsstelle.

        Prüfbericht 22.10.2026: Ein unbezahlter Auftrag, dessen Kunde keine
        E-Mail-Adresse hat (z. B. im Backoffice erfasst), bekam nie eine
        Erinnerung und wurde deshalb auch nie freigegeben; der Platz blieb bis
        zum Beginn reserviert. Jetzt zählt die Aufgabe an die Geschäftsstelle
        (telefonisch bzw. per Post erinnern) als Erinnerung: das Datum wird
        gesetzt, die Freigabefrist läuft wie nach einer Mail.
        """
        self.ensure_one()
        self.kjr_payment_reminder_date = fields.Datetime.now()
        events = self._kjr_kjr_event_lines().event_id
        note = _('Keine E-Mail-Adresse beim Kunden: Zahlungserinnerung bitte telefonisch '
                 'oder per Post. Ohne Zahlungseingang wird der Platz %(when)s freigegeben.',
                 when=(_('am %s', format_date(self.env, self.kjr_payment_release_date))
                       if self.kjr_payment_release_date else _('nicht automatisch')))
        self.message_post(body=Markup('<p>%s</p>') % note, subtype_xmlid='mail.mt_note')
        try:
            with self.env.cr.savepoint():
                self.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('Zahlungserinnerung ohne E-Mail'), note=note,
                    user_id=(events.user_id[:1] or self.user_id
                             or self.env.ref('base.user_admin')).id)
        except Exception:  # noqa: BLE001 - die Notiz steht, Aktivität ist Nebensache
            _logger.exception('KJR: Aktivität Zahlungserinnerung zu Auftrag %s nicht angelegt.',
                              self.id)
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
