# -*- coding: utf-8 -*-
"""Test-Aufträge der KLGM-Tests in der echten Veranstaltung 56 auflisten und
optional stornieren (Prüfbericht 22.10.2026).

Befund: Die Aufträge S00001, S00004, S00005 und S00006 stammen aus KLGM-Tests
(Bestellungen mit Überweisung, Status "gesendet", offene Überweisung). Ihre
Anmeldungen in der veröffentlichten Veranstaltung 56 "Selbstbehauptung für
Mädchen und Jungen" (Beginn 03.11.2026) halten als unbezahlte Reservierung
5 von 10 Plätzen frei. Wird der Cron für Zahlungserinnerung/Platzfreigabe
eingeschaltet, bekämen sie zudem eine Erinnerung.

Autor:   KLGM UG (haftungsbeschraenkt), https://www.klgm-consulting.de
Lizenz:  OPL-1
Stand:   2026-10-22
Anleitung: tools/ferienprogramm_t1013/README.md (vor JEDER Ausfuehrung lesen).

AUSFUEHREN DARF DAS SKRIPT NUR EINE BERECHTIGTE PERSON auf dem Server bzw.
einer Server-Kopie, nach einem Snapshot und nach Freigabe durch den KJR.
Nicht durch den Assistenten.

Betriebsarten (Umgebungsvariablen):
    (keine)               Probelauf: listet Aufträge, Überweisungen und
                          Anmeldungen, schreibt nichts (Rollback).
    KJR_FIX_WRITE=1       schreibt zuerst ein Backup (JSON), storniert dann die
                          Aufträge (Anmeldungen werden dabei abgesagt), setzt
                          offene Überweisungen auf "abgebrochen" und committet.
    KJR_ORDERS=<namen>    Auftragsnummern, Komma-getrennt
                          (Vorgabe S00001,S00004,S00005,S00006).
    KJR_EVENT_ID=<id>     Veranstaltung (Vorgabe 56).
    KJR_FIX_OUT=<ordner>  Ablage des Backups (Vorgabe: aktuelles Verzeichnis).
                          Datei: testauftraege_backup_<zeit>.json

Aufruf (auf dem Server, NICHT lokal):
    odoo shell -d <db> --no-http < testauftraege.py                   # Probelauf
    KJR_FIX_WRITE=1 odoo shell -d <db> --no-http < testauftraege.py   # schreibt

Sicherungen:
- Nur Aufträge, die eine Zeile zur Veranstaltung KJR_EVENT_ID haben, noch
  offen sind (Warenkorb/gesendet) und KEINE erledigte Zahlung haben. Alles
  andere wird gemeldet und übersprungen.
- Storniert wird über das ORM (sale.order._action_cancel, ohne Mail an den
  Kunden), Überweisungen über payment.transaction._set_canceled. event_sale
  sagt die Anmeldungen mit dem Auftrag ab; danach wird nachgelesen.
- Ausgabe: IDs, Auftragsnummern, Beträge, Status und die Namen der
  Teilnehmenden (zur Zuordnung durch die Geschäftsstelle; keine weiteren
  personenbezogenen Angaben). Das Backup enthält zusätzlich Kontakt-ID und
  E-Mail der Anmeldungen und liegt nur auf dem Server.
"""
import json
import os
import time

WRITE = os.environ.get('KJR_FIX_WRITE') == '1'
ORDER_NAMES = [n.strip() for n in os.environ.get(
    'KJR_ORDERS', 'S00001,S00004,S00005,S00006').split(',') if n.strip()]
EVENT_ID = int(os.environ.get('KJR_EVENT_ID', '56'))
OUT = os.environ.get('KJR_FIX_OUT') or os.getcwd()


def _order_info(order):
    return {
        'id': order.id, 'name': order.name, 'state': order.state,
        'amount_total': order.amount_total, 'partner_id': order.partner_id.id,
        'partner_invoice_id': order.partner_invoice_id.id,
        'kjr_payment_requested_date': str(order.kjr_payment_requested_date or ''),
        'kjr_payment_reminder_date': str(order.kjr_payment_reminder_date or ''),
        'transactions': [{
            'id': tx.id, 'reference': tx.reference, 'amount': tx.amount,
            'state': tx.state, 'provider': tx.provider_id.code,
        } for tx in order.transaction_ids],
        'registrations': [{
            'id': reg.id, 'name': reg.name, 'email': reg.email, 'state': reg.state,
            'event_id': reg.event_id.id, 'partner_id': reg.partner_id.id,
            'kjr_is_waitlist': reg.kjr_is_waitlist,
        } for reg in order.order_line.registration_ids],
    }


def main():
    SaleOrder = env['sale.order'].sudo()
    event = env['event.event'].sudo().browse(EVENT_ID).exists()
    if not event:
        print('Veranstaltung %s nicht gefunden, Abbruch.' % EVENT_ID)
        env.cr.rollback()
        return
    print('Veranstaltung %s "%s", Beginn %s, Plätze %s, belegt %s, reserviert (Zahlung offen) %s'
          % (event.id, event.name, event.date_begin, event.seats_max, event.seats_taken,
             event.kjr_seats_reserved_unpaid if 'kjr_seats_reserved_unpaid' in event._fields
             else '-'))
    orders = SaleOrder.search([('name', 'in', ORDER_NAMES)], order='name')
    missing = sorted(set(ORDER_NAMES) - set(orders.mapped('name')))
    if missing:
        print('Nicht gefunden: %s' % ', '.join(missing))
    todo = SaleOrder.browse()
    for order in orders:
        regs = order.order_line.registration_ids
        print('\n%s (id %s): Status %s, Betrag %.2f, Anforderung %s, Erinnerung %s' % (
            order.name, order.id, order.state, order.amount_total,
            order.kjr_payment_requested_date or '-', order.kjr_payment_reminder_date or '-'))
        for tx in order.transaction_ids:
            print('    Zahlung %s (id %s): %.2f, %s, %s' % (
                tx.reference, tx.id, tx.amount, tx.state, tx.provider_id.code))
        for reg in regs:
            print('    Anmeldung %s: "%s", Veranstaltung %s, Status %s%s' % (
                reg.id, reg.name, reg.event_id.id, reg.state,
                ', Warteliste' if reg.kjr_is_waitlist else ''))
        reasons = []
        if event not in order.order_line.event_id:
            reasons.append('keine Zeile zur Veranstaltung %s' % EVENT_ID)
        if order.state not in ('draft', 'sent'):
            reasons.append('Status %s' % order.state)
        if order.transaction_ids.filtered(lambda t: t.state == 'done'):
            reasons.append('erledigte Zahlung vorhanden')
        if reasons:
            print('    -> übersprungen: %s' % '; '.join(reasons))
        else:
            print('    -> wird %s' % ('storniert' if WRITE else 'im Schreiblauf storniert'))
            todo |= order
    others = env['event.registration'].sudo().search([
        ('event_id', '=', EVENT_ID), ('state', '!=', 'cancel'),
        ('sale_order_id', 'not in', orders.ids)])
    if others:
        print('\nWeitere nicht abgesagte Anmeldungen der Veranstaltung %s (nur Info, '
              'werden NICHT geändert):' % EVENT_ID)
        for reg in others:
            print('    Anmeldung %s: "%s", Status %s, Auftrag %s' % (
                reg.id, reg.name, reg.state, reg.sale_order_id.name or '-'))

    print('\nZu stornieren: %s Auftrag/Aufträge (%s)' % (
        len(todo), ', '.join(todo.mapped('name')) or '-'))
    if not WRITE:
        print('Probelauf, nichts geändert. Schreiben mit KJR_FIX_WRITE=1.')
        env.cr.rollback()
        return
    if not todo:
        env.cr.rollback()
        return

    backup = os.path.join(OUT, 'testauftraege_backup_%s.json' % time.strftime('%Y%m%d-%H%M%S'))
    with open(backup, 'w', encoding='utf-8') as fh:
        json.dump([_order_info(o) for o in todo], fh, ensure_ascii=False, indent=1)
    print('Backup: %s' % backup)

    for order in todo:
        txs = order.transaction_ids.filtered(lambda t: t.state in ('draft', 'pending'))
        if txs:
            txs._set_canceled(state_message='Test-Auftrag (KLGM) storniert, Prüfbericht 22.10.2026')
        order._action_cancel()
        order.message_post(
            body='Test-Auftrag aus den KLGM-Tests storniert (Prüfbericht 22.10.2026); '
                 'Platz in der Veranstaltung freigegeben.',
            subtype_xmlid='mail.mt_note')
    env.flush_all()
    env.invalidate_all()
    still = env['event.registration'].sudo().search([
        ('sale_order_id', 'in', todo.ids), ('state', '!=', 'cancel')])
    if still:
        # event_sale sagt Anmeldungen mit dem Auftrag ab; falls nicht, hier nachziehen.
        still.action_cancel()
        print('Anmeldungen nachträglich abgesagt: %s' % still.ids)
    for order in todo:
        print('%s: Status %s, Anmeldungen %s, Zahlungen %s' % (
            order.name, order.state,
            ', '.join('%s=%s' % (r.id, r.state) for r in order.order_line.registration_ids),
            ', '.join('%s=%s' % (t.id, t.state) for t in order.transaction_ids)))
    event.invalidate_recordset()
    print('Veranstaltung %s danach: belegt %s, reserviert (Zahlung offen) %s' % (
        event.id, event.seats_taken,
        event.kjr_seats_reserved_unpaid if 'kjr_seats_reserved_unpaid' in event._fields
        else '-'))
    env.cr.commit()
    print('Commit ausgeführt.')


main()
