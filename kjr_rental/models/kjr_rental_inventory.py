# -*- coding: utf-8 -*-
"""Schlanke Inventur für Verleihartikel (kein Enterprise stock/inventory)."""
from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import format_date

# Zustände, die für sich genommen einen Ersatzbedarf begründen. 'used' (gebraucht)
# gehört bewusst NICHT dazu: gebrauchtes, aber funktionsfähiges Material wird
# weiterverliehen — sonst stünde nach jeder Inventur der halbe Bestand auf der
# Beschaffungsliste und die Liste wäre wertlos.
REPLACE_CONDITIONS = ('damaged', 'lost')


class KjrRentalInventory(models.Model):
    _name = 'kjr.rental.inventory'
    _description = 'KJR Verleih Inventur'
    _order = 'year desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string='Bezeichnung', required=True, copy=False,
        default=lambda self: _('Inventur'), tracking=True,
    )
    year = fields.Integer(
        string='Jahr', required=True, tracking=True,
        default=lambda self: fields.Date.context_today(self).year,
    )
    company_id = fields.Many2one(
        'res.company', string='Gesellschaft', required=True,
        default=lambda self: self.env.company,
    )
    state = fields.Selection([
        ('draft', 'Erfassung'),
        ('done', 'Abgeschlossen'),
    ], string='Status', default='draft', required=True, tracking=True, index=True)
    date_done = fields.Date(string='Abgeschlossen am', readonly=True)
    line_ids = fields.One2many('kjr.rental.inventory.line', 'inventory_id', string='Positionen')
    note = fields.Text(string='Anmerkungen')

    # --- Beschaffungs-Vorschlagsliste (Auswertung, KEIN Beschaffungsprozess) ---
    # Bewusst NICHT store=True: die Bewertung hängt über Alter und Buchwert am
    # heutigen Datum (siehe kjr.rental.item._compute_book_value). Ein gespeicherter
    # Wert wäre am Tag nach der Berechnung bereits falsch und würde die Liste
    # unbelastbar machen.
    replacement_count = fields.Integer(
        string='Artikel mit Ersatzbedarf', compute='_compute_replacement',
        help='Anzahl der Inventurpositionen, für die sich aus Zustand, Fehlbestand, '
             'Alter oder Buchwert ein Ersatzbedarf ergibt.',
    )
    replacement_qty = fields.Integer(
        string='Ersatzbedarf gesamt (Stück)', compute='_compute_replacement')
    replacement_summary = fields.Text(
        string='Beschaffungsvorschlag', compute='_compute_replacement',
        help='Vorschlagsliste mit Begründung je Artikel (Zustand, Alter, Buchwert). '
             'Reine Auswertung als Entscheidungsgrundlage für die Geschäftsstelle — '
             'es wird nichts bestellt und nichts am Bestand verändert.',
    )

    def action_open(self):
        """'Inventur eröffnen': kopiert aktive Artikel als Zähl-Positionen."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Nur Inventuren in Erfassung können (neu) eröffnet werden.'))
            rec.line_ids.unlink()
            items = self.env['kjr.rental.item'].search([('active', '=', True)])
            rec.line_ids = [(0, 0, {
                'item_id': item.id,
                'qty_expected': item.quantity_total,
                'qty_counted': item.quantity_total,
            }) for item in items]
            rec.message_post(
                body=_('Inventur eröffnet: %d Artikel erfasst.') % len(items),
                subtype_xmlid='mail.mt_note')

    def action_done(self):
        """'abschließen': schreibt Ausschuss (scrap) auf Artikel zurück.

        Bei scrap=True wird die gezählte Differenz (qty_expected - qty_counted, min. 1)
        vom Gesamtbestand abgezogen; sinkt der Bestand auf 0, wird der Artikel
        deaktiviert (active=False).
        """
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Diese Inventur ist bereits abgeschlossen.'))
            for line in rec.line_ids:
                if not line.scrap or not line.item_id:
                    continue
                diff = line.qty_expected - line.qty_counted
                scrap_qty = diff if diff > 0 else 1
                new_total = max(line.item_id.quantity_total - scrap_qty, 0)
                vals = {'quantity_total': new_total}
                if new_total <= 0:
                    vals['active'] = False
                line.item_id.write(vals)
            rec.state = 'done'
            rec.date_done = fields.Date.context_today(rec)
            rec.message_post(body=_('Inventur abgeschlossen.'), subtype_xmlid='mail.mt_note')

    def action_reset_draft(self):
        for rec in self:
            if rec.state == 'done':
                raise UserError(_(
                    'Eine abgeschlossene Inventur kann nicht erneut geöffnet werden, da der '
                    'Ausschuss bereits auf den Bestand verbucht wurde (eine erneute Buchung '
                    'würde den Bestand doppelt reduzieren). Bitte eine neue Inventur anlegen.'))
            rec.state = 'draft'

    # ------------------------------------------------------------------
    # Beschaffungs-Vorschlagsliste
    # ------------------------------------------------------------------
    def _replacement_lines(self):
        """Positionen mit Ersatzbedarf, stabil sortiert (Kategorie, Artikel)."""
        self.ensure_one()
        lines = self.line_ids.filtered(lambda l: l.replace_suggested)
        # Bewusst OHNE l.id im Sortierschlüssel: in einem ungespeicherten Formular
        # sind die IDs NewId-Objekte und nicht vergleichbar. sorted() ist stabil,
        # gleichnamige Positionen behalten also ihre Reihenfolge.
        return lines.sorted(key=lambda l: (
            l.item_id.category_id.name or '', l.item_id.name or ''))

    @api.depends('line_ids.replace_suggested', 'line_ids.replace_qty',
                 'line_ids.replace_reason')
    def _compute_replacement(self):
        for rec in self:
            lines = rec._replacement_lines()
            rec.replacement_count = len(lines)
            rec.replacement_qty = sum(lines.mapped('replace_qty'))
            rec.replacement_summary = rec._replacement_text(lines)

    def _replacement_text(self, lines):
        """Lesbare Vorschlagsliste als Text (für Formular, Chatter und Copy&Paste)."""
        self.ensure_one()
        if not lines:
            return _('Aus dieser Inventur ergibt sich kein Ersatzbedarf.')
        rows = [_(
            'Beschaffungsvorschlag aus der Inventur %(name)s (Stand: %(date)s)\n'
            'Grundlage: erfasster Zustand, Fehlbestand, Nutzungsdauer und Buchwert.\n'
            'Die Liste ist ein Vorschlag — über Beschaffung, Menge und Zeitpunkt '
            'entscheidet die Geschäftsstelle.',
            name=self.display_name,
            date=format_date(self.env, fields.Date.context_today(self)),
        ), '']
        total_value = 0.0
        for line in lines:
            item = line.item_id
            total_value += (item.purchase_value or 0.0) * line.replace_qty
            rows.append(_(
                '- %(item)s (%(category)s, Lager: %(location)s): Ersatzbedarf '
                '%(qty)d Stück von %(counted)d gezählten.\n'
                '  Zustand: %(condition)s | Alter: %(age).1f Jahre | '
                'Buchwert: %(book).2f € | Anschaffungswert lt. Stammdaten: %(purchase).2f €\n'
                '  Begründung: %(reason)s',
                item=item.display_name,
                category=item.category_id.display_name or _('ohne Kategorie'),
                location=item.location_id.display_name or _('ohne Lager'),
                qty=line.replace_qty,
                counted=line.qty_counted or 0,
                condition=line._condition_label(),
                age=line.item_age_years,
                book=line.item_book_value,
                purchase=item.purchase_value or 0.0,
                reason=line.replace_reason or '',
            ))
        rows.append('')
        rows.append(_(
            'Summe der Anschaffungswerte laut Stammdaten: %(total).2f €.\n'
            'ACHTUNG: Das ist KEIN Angebot und kein Budgetwert, sondern die Summe der '
            'im Artikelstamm hinterlegten historischen Anschaffungswerte (Artikel ohne '
            'gepflegten Anschaffungswert gehen mit 0,00 € ein). Aktuelle Preise sind '
            'vor der Beschaffung einzuholen.',
            total=total_value))
        return '\n'.join(rows)

    def action_open_replacement_list(self):
        """Vorschlagsliste als Listenansicht öffnen.

        Die Auswahl wird in Python ermittelt und über [('id','in',...)] übergeben:
        replace_suggested ist ein NICHT gespeichertes Compute-Feld (heute-abhängig)
        und lässt sich deshalb nicht in einer Domain filtern.
        """
        self.ensure_one()
        lines = self._replacement_lines()
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Beschaffungsvorschlag – %s') % self.display_name,
            'res_model': 'kjr.rental.inventory.line',
            'view_mode': 'list',
            'domain': [('id', 'in', lines.ids)],
            'context': {'create': False, 'delete': False},
            'target': 'current',
        }
        view = self.env.ref(
            'kjr_rental.view_kjr_rental_inventory_line_replacement_list',
            raise_if_not_found=False)
        if view:
            action['views'] = [(view.id, 'list')]
        return action

    def action_log_replacement_proposal(self):
        """Vorschlagsliste im Chatter festhalten (Nachweis des Standes)."""
        for rec in self:
            lines = rec._replacement_lines()
            rec.message_post(
                # Markup: message_post interpretiert den Body als HTML — der reine
                # Text muss deshalb escaped und in <pre> gesetzt werden, sonst gehen
                # Zeilenumbrüche verloren und '&' bricht die Darstellung.
                body=Markup('<pre style="white-space:pre-wrap">%s</pre>') % (
                    rec._replacement_text(lines)),
                subtype_xmlid='mail.mt_note')
        return True


class KjrRentalInventoryLine(models.Model):
    _name = 'kjr.rental.inventory.line'
    _description = 'KJR Inventurposition'
    _order = 'inventory_id, id'

    inventory_id = fields.Many2one(
        'kjr.rental.inventory', string='Inventur', required=True,
        ondelete='cascade', index=True)
    item_id = fields.Many2one('kjr.rental.item', string='Artikel', required=True)
    qty_expected = fields.Integer(string='Soll-Bestand')
    qty_counted = fields.Integer(string='Gezählt')
    qty_diff = fields.Integer(string='Differenz', compute='_compute_qty_diff', store=True)
    condition = fields.Selection([
        ('good', 'Gut'),
        ('used', 'Gebraucht'),
        ('damaged', 'Beschädigt'),
        ('lost', 'Verloren'),
    ], string='Zustand', default='good')
    scrap = fields.Boolean(string='Ausschuss / abschreiben')
    note = fields.Char(string='Notiz')

    # --- Beschaffungs-Vorschlag je Position -------------------------------
    # Alle vier Felder kommen aus EINEM Compute und sind bewusst NICHT
    # gespeichert: Alter und Buchwert hängen am heutigen Datum (item.book_value
    # ist selbst ein nicht gespeichertes Compute), ein gespeicherter Wert wäre
    # sonst am Folgetag falsch.
    item_purchase_date = fields.Date(
        related='item_id.purchase_date', string='Anschaffung', readonly=True)
    item_age_years = fields.Float(
        string='Alter (Jahre)', digits=(6, 1), compute='_compute_replacement')
    item_book_value = fields.Float(
        string='Buchwert (€)', digits=(10, 2), compute='_compute_replacement')
    replace_suggested = fields.Boolean(
        string='Ersatz vorschlagen', compute='_compute_replacement',
        help='Aus Zustand, Fehlbestand, Nutzungsdauer oder Buchwert ergibt sich ein '
             'Ersatzbedarf. Reiner Vorschlag — die Entscheidung trifft die '
             'Geschäftsstelle.',
    )
    replace_qty = fields.Integer(
        string='Ersatzbedarf (Stück)', compute='_compute_replacement')
    replace_reason = fields.Char(
        string='Begründung', compute='_compute_replacement')

    @api.depends('qty_expected', 'qty_counted')
    def _compute_qty_diff(self):
        for rec in self:
            rec.qty_diff = (rec.qty_counted or 0) - (rec.qty_expected or 0)

    def _condition_label(self):
        """Deutsche Beschriftung des erfassten Zustands (für Textausgaben)."""
        self.ensure_one()
        return dict(self._fields['condition']._description_selection(self.env)).get(
            self.condition, self.condition or '')

    @api.depends('condition', 'scrap', 'qty_expected', 'qty_counted', 'item_id',
                 'item_id.purchase_date', 'item_id.purchase_value',
                 'item_id.useful_life_years', 'item_id.salvage_value')
    def _compute_replacement(self):
        """Ersatzbedarf je Position mit nachvollziehbarer Begründung.

        Die Kriterien sind bewusst rein strukturell (Zustand, Fehlbestand,
        Nutzungsdauer, Abschreibung) — es gibt KEINE erfundenen Wert- oder
        Altersgrenzen. Alle Schwellen stammen aus Daten, die die Geschäftsstelle
        selbst pflegt (Zustand in der Inventur, Nutzungsdauer und Restwert im
        Artikelstamm). Fehlen diese Stammdaten, greift das jeweilige Kriterium
        einfach nicht; der Artikel taucht dann nur über Zustand/Fehlbestand auf.
        """
        today = fields.Date.context_today(self)
        for rec in self:
            item = rec.item_id
            reasons = []
            age = 0.0
            book = 0.0
            if item:
                book = item.book_value
                if item.purchase_date:
                    age = max((today - item.purchase_date).days, 0) / 365.25

            missing = max((rec.qty_expected or 0) - (rec.qty_counted or 0), 0)
            defect = False

            if rec.condition in REPLACE_CONDITIONS:
                defect = True
                reasons.append(_('Zustand „%s"') % rec._condition_label())
            if rec.scrap:
                defect = True
                reasons.append(_('in dieser Inventur als Ausschuss abgeschrieben'))
            if missing:
                defect = True
                reasons.append(_('Fehlbestand: %(qty)d von %(exp)d Stück nicht auffindbar',
                                 qty=missing, exp=rec.qty_expected or 0))

            aged = False
            if item and item.purchase_date and item.useful_life_years \
                    and age >= item.useful_life_years:
                aged = True
                reasons.append(_(
                    'Nutzungsdauer erreicht: %(age).1f von %(life)d Jahren',
                    age=age, life=item.useful_life_years))
            elif item and item.useful_life_years and (item.purchase_value or 0.0) > 0 \
                    and book <= (item.salvage_value or 0.0):
                aged = True
                reasons.append(_(
                    'vollständig abgeschrieben: Buchwert %(book).2f € entspricht dem '
                    'Restwert %(salvage).2f €', book=book, salvage=item.salvage_value or 0.0))

            rec.item_age_years = age
            rec.item_book_value = book
            rec.replace_suggested = bool(reasons)
            rec.replace_reason = '; '.join(reasons)
            if not reasons:
                rec.replace_qty = 0
            elif defect:
                # Defekt/Verlust betrifft konkrete Stücke: fehlende Menge, mindestens
                # eines (ein als beschädigt gemeldeter Artikel wurde ja mitgezählt).
                rec.replace_qty = missing or 1
            elif aged:
                # Nur Alter/Abschreibung: betroffen ist der gesamte gezählte Bestand
                # dieses Artikels. Das ist die Obergrenze des Bedarfs —
                # TODO(KJR): ob wirklich der komplette Bestand ersetzt wird oder nur
                # ein Teil, entscheidet die Geschäftsstelle bei der Beschaffung.
                rec.replace_qty = max(rec.qty_counted or 0, 0)
            else:
                rec.replace_qty = 0
