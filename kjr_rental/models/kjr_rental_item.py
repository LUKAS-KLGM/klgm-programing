# -*- coding: utf-8 -*-
"""Verleihartikel mit Bestand, Lager und Tarifen."""
import re
from datetime import date as date_cls

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class KjrRentalCategory(models.Model):
    """Frei pflegbare Verleih-Kategorien (statt hartkodierter Auswahl) — damit die App
    an beliebige Jugendringe verkaufbar ist und jeder seine eigenen Kategorien anlegen kann."""
    _name = 'kjr.rental.category'
    _description = 'Verleih-Kategorie'
    _order = 'sequence, name'

    name = fields.Char(string='Bezeichnung', required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    icon = fields.Char(string='FontAwesome-Icon', help='z. B. fa-bus, fa-music')
    item_count = fields.Integer(string='Artikel', compute='_compute_item_count')

    def _compute_item_count(self):
        data = self.env['kjr.rental.item']._read_group(
            [('category_id', 'in', self.ids)], groupby=['category_id'], aggregates=['__count'])
        mapped = {c.id: n for c, n in data}
        for rec in self:
            rec.item_count = mapped.get(rec.id, 0)


class KjrRentalLocation(models.Model):
    """Frei pflegbare Lagerorte (statt hartkodierter Auswahl)."""
    _name = 'kjr.rental.location'
    _description = 'Verleih-Lager'
    _order = 'sequence, name'

    name = fields.Char(string='Bezeichnung', required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)


class KjrRentalItem(models.Model):
    _name = 'kjr.rental.item'
    _description = 'Verleihartikel'
    _order = 'category_id, name'

    name = fields.Char(string='Bezeichnung', required=True)
    code = fields.Char(
        string='Inventarnummer', copy=False,
        help='Interne Inventarnummer. Muss eindeutig sein, damit bei der Rücknahme '
             'kein Artikel verwechselt wird.',
    )
    barcode = fields.Char(
        string='Barcode / Inventaretikett', copy=False, index=True,
        help='Aufgeklebtes Etikett des Artikels. Grundlage für Ausgabe, Rücknahme und '
             'Inventur per Scan. Leer lassen und über "Barcode erzeugen" ableiten, '
             'wenn noch kein Etikett vergeben ist.',
    )
    active = fields.Boolean(default=True)
    category_id = fields.Many2one(
        'kjr.rental.category', string='Kategorie', required=True, ondelete='restrict')
    location_id = fields.Many2one(
        'kjr.rental.location', string='Lager', ondelete='set null')
    quantity_total = fields.Integer(string='Bestand gesamt', default=1)
    price_per_day = fields.Float(string='Tagespreis Standard (€)', digits=(8, 2))
    has_member_price = fields.Boolean(
        string='Eigener Mitgliedstarif', default=True,
        help='Wenn aktiv, gilt für Mitglieder der Mitgliedstarif (auch 0 € = gratis). '
             'Wenn inaktiv, gilt für alle der Standardtarif.',
    )
    price_member_per_day = fields.Float(string='Tagespreis Mitglied (€)', digits=(8, 2))
    deposit = fields.Float(string='Kaution (€)', digits=(8, 2))
    image_1920 = fields.Image(string='Bild', max_width=1920, max_height=1920)
    description = fields.Text(string='Beschreibung')
    usage_warning = fields.Html(
        string='Nutzungshinweise', sanitize=True,
        help='Verbindliche Nutzungsregeln für genau diesen Artikel (z. B. Führerschein-'
             'klasse, Aufbau nur durch eingewiesene Personen, Reinigung vor Rückgabe). '
             'Der Text wird dem Entleiher auf der Website vor dem Absenden der Anfrage '
             'angezeigt und muss von ihm bestätigt werden.',
    )
    website_published = fields.Boolean(string='Auf Website', default=True)
    icon = fields.Char(string='FontAwesome-Icon', help='z. B. fa-bus')

    # --- Eindeutigkeit von Inventarnummer und Barcode -------------------------
    # Partieller UNIQUE-Index statt einfacher UNIQUE-Constraint: PostgreSQL lässt
    # zwar beliebig viele NULL-Werte zu, ABER nur einen einzigen Leerstring ''.
    # Ohne die WHERE-Klausel könnte also nur ein einziger Artikel ohne Barcode
    # existieren. Die Klausel nimmt leere Werte komplett aus dem Index heraus.
    # Bewusst OHNE 'AND active IS TRUE': eine Nummer eines archivierten Artikels
    # darf nicht erneut vergeben werden, sonst ist die Historie nicht mehr
    # eindeutig zuzuordnen.
    _barcode_unique = models.UniqueIndex(
        "(barcode) WHERE barcode IS NOT NULL AND barcode != ''",
        'Dieser Barcode ist bereits an einen anderen Verleihartikel vergeben.',
    )
    _code_unique = models.UniqueIndex(
        "(code) WHERE code IS NOT NULL AND code != ''",
        'Diese Inventarnummer ist bereits an einen anderen Verleihartikel vergeben.',
    )

    @api.constrains('code', 'barcode')
    def _check_code_barcode_unique(self):
        """Zusätzliche ORM-Prüfung zu den UNIQUE-Indizes oben.

        Notwendig, weil Odoo einen UNIQUE-Index bei bereits vorhandenen Dubletten
        NICHT anlegt (der Fehler wird nur ins Log geschrieben, das Update läuft
        durch). Ohne diese Prüfung wäre die Eindeutigkeit auf einer Altdatenbank
        still wirkungslos. Nennt zudem den kollidierenden Artikel beim Namen.
        """
        for rec in self:
            for fname, label in (('code', _('Inventarnummer')),
                                 ('barcode', _('Barcode'))):
                value = rec[fname]
                if not value:
                    continue
                # active_test=False: auch archivierte Artikel belegen ihre Nummer.
                other = rec.with_context(active_test=False).search(
                    [(fname, '=', value), ('id', '!=', rec.id)], limit=1)
                if other:
                    raise ValidationError(_(
                        '%(label)s "%(value)s" ist bereits an den Artikel "%(other)s" '
                        'vergeben. Nummern und Barcodes müssen eindeutig sein, damit '
                        'bei Ausgabe und Rücknahme nichts verwechselt wird.',
                        label=label, value=value, other=other.display_name,
                    ))

    # --- Barcode: Normalisierung und Erzeugung --------------------------------
    @api.model
    def _normalize_scan_value(self, value):
        """Leerzeichen abschneiden und Leerstrings zu False machen.

        Notwendig, damit der partielle UNIQUE-Index greift: '   ' und '' sind für
        PostgreSQL unterschiedliche, nicht-leere Werte und würden sonst als
        vergebene Nummern gelten bzw. beim zweiten Datensatz kollidieren.
        """
        if value is False or value is None:
            return value
        value = (value or '').strip()
        return value or False

    def _normalize_scan_vals(self, vals):
        """Kopie von vals mit normalisierter Inventarnummer/Barcode.
        Kopie, damit der Aufrufer-Dict (z. B. aus einem Controller) unangetastet bleibt."""
        if not any(f in vals for f in ('code', 'barcode')):
            return vals
        vals = dict(vals)
        for fname in ('code', 'barcode'):
            if fname in vals:
                vals[fname] = self._normalize_scan_value(vals[fname])
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._normalize_scan_vals(vals) for vals in vals_list])

    def write(self, vals):
        return super().write(self._normalize_scan_vals(vals))

    def _barcode_prefix(self):
        """Stabiles Präfix aller erzeugten Barcodes (systemweit konfigurierbar)."""
        param = self.env['ir.config_parameter'].sudo().get_param(
            'kjr_rental.barcode_prefix', default='KJR')
        prefix = re.sub(r'[^A-Z0-9]', '', (param or 'KJR').upper())
        return prefix or 'KJR'

    def _build_barcode(self):
        """Barcode-Vorschlag für DIESEN Artikel: Präfix + Inventarnummer, ersatzweise
        Präfix + ID. Bewusst nur Großbuchstaben, Ziffern und '-', damit der Wert
        ohne Sonderzeichen als Code128 druck- und scanbar bleibt."""
        self.ensure_one()
        prefix = self._barcode_prefix()
        raw = (self.code or '').strip()
        if raw:
            suffix = re.sub(r'[^A-Z0-9]+', '-', raw.upper()).strip('-')
        else:
            suffix = ''
        if not suffix:
            # ID ist erst nach dem Anlegen bekannt – deshalb wird hier NICHT bei
            # create() erzeugt, sondern nur über die Aktion (siehe unten).
            suffix = '%06d' % (self.id if isinstance(self.id, int) else 0)
        return '%s-%s' % (prefix, suffix)

    def action_generate_barcode(self):
        """Fehlende Barcodes erzeugen (Aktion, KEIN Automatismus bei create()).

        Bewusst nicht in create() gehängt: die Geschäftsstelle klebt oft bereits
        vorhandene Etiketten auf, ein automatisch vergebener Wert wäre dann falsch.
        Ein anderer Agent bindet die Methode als Button in die Views ein; sie ist
        mehrfachauswahl-fähig (Listenansicht) und überschreibt bestehende
        Barcodes nicht.
        """
        for rec in self:
            if self._normalize_scan_value(rec.barcode):
                continue
            if not isinstance(rec.id, int):
                # Ungespeicherter Datensatz (NewId): ohne echte ID lässt sich kein
                # stabiler Barcode ableiten.
                raise UserError(_(
                    'Bitte den Verleihartikel zuerst speichern, dann den Barcode erzeugen.'))
            candidate = rec._build_barcode()
            # Kollisionen (z. B. gleiche Inventarnummer-Basis) auflösen.
            # active_test=False: auch archivierte Artikel belegen ihren Barcode.
            base, counter = candidate, 1
            while rec.with_context(active_test=False).search_count(
                    [('barcode', '=', candidate), ('id', '!=', rec.id)]):
                counter += 1
                candidate = '%s-%d' % (base, counter)
            rec.barcode = candidate
        return True

    # --- R3: Abschreibung (lineare Eigenberechnung, KEIN Enterprise account_asset) ---
    purchase_value = fields.Float(string='Anschaffungswert (€)', digits=(10, 2))
    purchase_date = fields.Date(string='Anschaffungsdatum')
    useful_life_years = fields.Integer(string='Nutzungsdauer (Jahre)')
    salvage_value = fields.Float(string='Restwert (€)', digits=(10, 2))
    # today()-abhängig => NICHT store=True (siehe Odoo-19-Regeln)
    book_value = fields.Float(
        string='Buchwert heute (€)', digits=(10, 2),
        compute='_compute_book_value', store=False,
    )

    @api.depends('purchase_value', 'purchase_date', 'useful_life_years', 'salvage_value')
    def _compute_book_value(self):
        today = date_cls.today()
        for rec in self:
            base = rec.purchase_value or 0.0
            salvage = rec.salvage_value or 0.0
            if not rec.purchase_date or not rec.useful_life_years or base <= 0:
                rec.book_value = base
                continue
            elapsed_days = (today - rec.purchase_date).days
            if elapsed_days < 0:
                rec.book_value = base
                continue
            elapsed_years = elapsed_days / 365.25
            depreciable = base - salvage
            annual = depreciable / rec.useful_life_years if rec.useful_life_years else 0.0
            value = base - annual * elapsed_years
            # nie unter Restwert
            rec.book_value = max(value, salvage)

    def price_for(self, is_member):
        """Tagespreis je nach Mitgliedsstatus. Ein konfigurierter Mitgliedstarif gilt
        auch bei 0 € (gratis), sofern 'Eigener Mitgliedstarif' aktiv ist."""
        self.ensure_one()
        if is_member and self.has_member_price:
            return self.price_member_per_day
        return self.price_per_day

    def quantity_available(self, date_from, date_to, exclude_order=None, include_draft=None):
        """Im Zeitraum verfügbare Menge (Bestand minus überlappende Reservierungen/Ausgaben).

        include_draft: Wenn True, werden auch Anfragen (state='draft') als Soft-Reserve
        mitgezählt, um das Verfügbarkeits-Race bei gleichzeitigen Warenkorb-Bestellungen
        zu entschärfen. Standard wird aus dem Systemparameter
        'kjr_rental.reserve_draft' gelesen (konfigurierbar).
        """
        self.ensure_one()
        if not (date_from and date_to):
            return self.quantity_total
        if include_draft is None:
            param = self.env['ir.config_parameter'].sudo().get_param(
                'kjr_rental.reserve_draft', default='False')
            include_draft = str(param).lower() in ('1', 'true', 'yes')
        states = ['reserved', 'issued']
        if include_draft:
            states.append('draft')
        line_domain = [
            ('item_id', '=', self.id),
            ('order_id.state', 'in', states),
            ('order_id.date_from', '<=', date_to),
            ('order_id.date_to', '>=', date_from),
        ]
        if exclude_order:
            line_domain.append(('order_id', '!=', exclude_order.id))
        # sudo(): Artikel sind eine firmenübergreifend GETEILTE Ressource (kein company_id).
        # Die Verfügbarkeit muss daher alle überlappenden Reservierungen ALLER Gesellschaften
        # zählen – sonst umgeht die Company-Record-Rule die Belegung (Doppelbuchung).
        lines = self.env['kjr.rental.order.line'].sudo().search(line_domain)
        reserved = sum(lines.mapped('quantity'))
        return self.quantity_total - reserved
