# -*- coding: utf-8 -*-
"""Verleihartikel mit Bestand, Lager und Tarifen."""
import re
from datetime import date as date_cls

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

# Preismodelle des Verleihs. Als Modulkonstante, damit Artikel und Auswertungen
# dieselbe Auswahl verwenden; die Ausleihposition spiegelt das Feld ueber ein
# related-Feld und braucht die Liste deshalb nicht erneut.
PRICING_MODEL_SELECTION = [
    ('per_day', 'Pro Tag'),
    ('per_night', 'Pro Nacht'),
    ('per_unit', 'Pro Stück / Pauschale'),
    ('per_km', 'Grundgebühr + Kilometerpreis'),
    ('tiered', 'Mengenstaffel'),
]


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

    # --- Preismodell -----------------------------------------------------------
    # Die echte Preisliste des KJR kennt mehr als den Tagespreis: Fahrzeuge werden
    # nach gefahrenen Kilometern abgerechnet, Kisten und Sätze als Stückpreis ohne
    # Zeitbezug, Zelte je Nacht, Mobiliar in Mengenstaffeln. Umsetzung bewusst
    # zweigeteilt:
    #   * Die zeitbezogenen und pauschalen Modelle kommen mit Feldern AM ARTIKEL aus
    #     (Grundpreis, Kilometerpreis, Zeitbezug) — jeder Artikel hat davon genau
    #     einen Wert, ein eigenes Modell wäre eine Tabelle mit einer Zeile je Artikel.
    #   * Die Mengenstaffel ist von Natur aus 1:n ("ab 10 Stück gilt Preis Y") und
    #     bekommt deshalb das Kindmodell kjr.rental.price.tier (siehe unten).
    # Der Default 'per_day' ist die BESTANDSSICHERUNG: Odoo füllt die neue Spalte
    # beim Upgrade mit dem Feld-Default, bestehende Artikel rechnen also unverändert
    # Grundpreis × Menge × Tage. Zusätzlich behandelt _pricing_model() einen leeren
    # Wert wie 'per_day', falls eine Zeile den Default doch nicht abbekommen hat.
    pricing_model = fields.Selection(
        PRICING_MODEL_SELECTION, string='Preismodell', default='per_day', required=True,
        help='Bestimmt, wie die Gebühr aus Grundpreis, Menge und Zeitraum gebildet wird:\n'
             '• Pro Tag: Grundpreis × Menge × angefangene Tage (bisheriges Verhalten).\n'
             '• Pro Nacht: Grundpreis × Menge × Nächte (Tage − 1).\n'
             '• Pro Stück / Pauschale: Grundpreis × Menge, ohne Zeitbezug.\n'
             '• Grundgebühr + Kilometerpreis: Grundpreis × Menge (Zeitbezug siehe '
             '"Zeitbezug des Grundpreises") zuzüglich Kilometerpreis × gefahrene '
             'Kilometer der Ausleihposition.\n'
             '• Mengenstaffel: ab der in der Staffel hinterlegten Menge tritt der '
             'Staffelpreis an die Stelle des Grundpreises.',
    )
    price_time_basis = fields.Selection([
        ('flat', 'Pauschal (ohne Zeitbezug)'),
        ('day', 'Je Tag'),
        ('night', 'Je Nacht'),
    ], string='Zeitbezug des Grundpreises', default='flat', required=True,
        help='Gilt nur für die Preismodelle "Grundgebühr + Kilometerpreis" und '
             '"Mengenstaffel": ob der Grund- bzw. Staffelpreis einmalig je Ausleihe, '
             'je Tag oder je Nacht anfällt. Voreingestellt ist "pauschal" — die '
             'zurückhaltende Variante, weil eine unbeabsichtigte Multiplikation mit '
             'dem Zeitraum die Rechnung erhöhen würde. '
             'TODO(KJR): je Artikelgruppe mit der echten Preisliste abgleichen.',
    )
    unit_label = fields.Char(
        string='Bezeichnung der Einheit',
        help='Wie heißt EINE Einheit dieses Artikels in der Preisliste (z. B. "Kiste", '
             '"Satz", "Garnitur")? Der Text erscheint in Preisangaben und auf der '
             'Rechnung anstelle von "Stück". Leer lassen = "Stück".',
    )
    price_per_day = fields.Float(
        string='Grundpreis Standard (€)', digits=(8, 2),
        help='Grundpreis für Nicht-Mitglieder. Die Bezugsgröße hängt am Preismodell: '
             'je Tag, je Nacht, je Stück/Pauschale oder Grundgebühr neben dem '
             'Kilometerpreis. Der Feldname bleibt aus Bestandsgründen price_per_day.',
    )
    has_member_price = fields.Boolean(
        string='Eigener Mitgliedstarif', default=True,
        help='Wenn aktiv, gilt für Mitglieder der Mitgliedstarif (auch 0 € = gratis). '
             'Wenn inaktiv, gilt für alle der Standardtarif. Wirkt auf Grundpreis, '
             'Kilometerpreis und Mengenstaffel gleichermaßen.',
    )
    price_member_per_day = fields.Float(
        string='Grundpreis Mitglied (€)', digits=(8, 2),
        help='Grundpreis für KJR-Mitglieder, gleiche Bezugsgröße wie der Standardpreis.',
    )
    # TODO(KJR): Kilometersätze der echten Preisliste eintragen — Startwert bewusst 0,00 €,
    # damit kein erfundener Satz in Angebot oder Rechnung landet.
    price_per_km = fields.Float(
        string='Kilometerpreis Standard (€/km)', digits=(8, 2),
        help='Nur beim Preismodell "Grundgebühr + Kilometerpreis": Satz je gefahrenem '
             'Kilometer für Nicht-Mitglieder. Startwert 0,00 € — die echte Preisliste '
             'pflegt die Geschäftsstelle.',
    )
    price_member_per_km = fields.Float(
        string='Kilometerpreis Mitglied (€/km)', digits=(8, 2),
        help='Kilometersatz für KJR-Mitglieder (nur bei aktivem Mitgliedstarif). '
             'Startwert 0,00 € — TODO(KJR): echte Preisliste eintragen.',
    )
    min_billable_units = fields.Integer(
        string='Mindestberechnete Einheiten', default=0,
        help='Mindestzahl berechneter Tage bzw. Nächte (0 = keine Mindestberechnung, '
             'bisheriges Verhalten). Relevant vor allem bei "Pro Nacht": eine Ausleihe '
             'ohne Übernachtung ergibt 0 Nächte und damit 0 €. '
             'TODO(KJR): Ist eine Mindestberechnung gewünscht und mit welchem Wert?',
    )
    tier_ids = fields.One2many(
        'kjr.rental.price.tier', 'item_id', string='Mengenstaffel', copy=True,
        help='Staffelpreise dieses Artikels. Wirken nur beim Preismodell '
             '"Mengenstaffel": Es greift die Zeile mit der höchsten "Ab Menge", die '
             'die bestellte Menge nicht überschreitet; der Staffelpreis gilt dann für '
             'ALLE Stück der Position.',
    )
    price_unit_label = fields.Char(
        string='Preiseinheit', compute='_compute_price_unit_label', store=False,
        help='Klartext der Preiseinheit zum gewählten Preismodell (z. B. "pro Tag", '
             '"pro Kiste (pauschal)"). Gedacht für Backend-Hinweis, Website und Report, '
             'damit dort nicht pauschal "pro Tag" steht.\n'
             'ACHTUNG: Beim Preismodell "Grundgebühr + Kilometerpreis" beschreibt dieser '
             'Text das GESAMTE Modell (zwei Beträge) und ist deshalb KEINE Einheit für '
             'einen einzelnen Betrag. Wer genau einen Betrag beschriftet, muss '
             '"Einheit des Grundpreises" bzw. "Einheit des Kilometerpreises" verwenden.',
    )
    # Einheit je EINZELBETRAG. Ohne diese beiden Felder blieb nur price_unit_label,
    # und das beschreibt beim Kilometermodell zwei Beträge auf einmal ("Grundgebühr
    # pauschal je Ausleihe zuzüglich Kilometerpreis"). Damit beschriftet, wäre jede
    # einzelne Zahl der Website falsch ausgezeichnet — genau der Befund der Abnahme.
    price_base_unit_label = fields.Char(
        string='Einheit des Grundpreises', compute='_compute_price_unit_label', store=False,
        help='Einheit, die AUSSCHLIESSLICH zum Grundpreis (price_per_day) gehört — '
             'z. B. "pro Tag" oder beim Kilometermodell "Grundgebühr pauschal je '
             'Ausleihe". Für Preisangaben, die genau einen Betrag ausweisen.',
    )
    price_km_unit_label = fields.Char(
        string='Einheit des Kilometerpreises', compute='_compute_price_unit_label',
        store=False,
        help='Einheit des Kilometersatzes; nur beim Preismodell "Grundgebühr + '
             'Kilometerpreis" gefüllt, sonst leer.',
    )
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

    # --- Preisbildung ----------------------------------------------------------
    def _pricing_model(self):
        """Preismodell mit Rückfall auf 'per_day'.

        Bewusst nicht direkt self.pricing_model lesen: ein leerer Wert (Altdaten,
        die den Feld-Default beim Upgrade nicht abbekommen haben, oder ein per RPC
        auf False gesetztes Feld) muss sich exakt wie bisher verhalten — Grundpreis
        × Menge × Tage.
        """
        self.ensure_one()
        return self.pricing_model or 'per_day'

    def price_for(self, is_member):
        """Grundpreis je nach Mitgliedsstatus. Ein konfigurierter Mitgliedstarif gilt
        auch bei 0 € (gratis), sofern 'Eigener Mitgliedstarif' aktiv ist.

        Die Bezugsgröße des zurückgegebenen Betrags hängt am Preismodell (je Tag,
        je Nacht, je Stück, Grundgebühr neben dem Kilometerpreis). Die Mengenstaffel
        ist hier NICHT berücksichtigt — dafür gibt es unit_price_for(), weil der
        Staffelpreis von der bestellten Menge abhängt.
        """
        self.ensure_one()
        if is_member and self.has_member_price:
            return self.price_member_per_day
        return self.price_per_day

    def price_km_for(self, is_member):
        """Kilometersatz je nach Mitgliedsstatus (gleiche Logik wie price_for)."""
        self.ensure_one()
        if is_member and self.has_member_price:
            return self.price_member_per_km
        return self.price_per_km

    def matching_tier(self, quantity):
        """Greifende Staffelzeile für eine Menge (leeres Recordset, wenn keine greift).

        Es gewinnt die Zeile mit der höchsten "Ab Menge", die die bestellte Menge
        nicht überschreitet.
        """
        self.ensure_one()
        qty = int(quantity or 0)
        matching = self.tier_ids.filtered(lambda t: t.min_quantity <= qty)
        if not matching:
            return self.env['kjr.rental.price.tier']
        return max(matching, key=lambda t: t.min_quantity)

    def unit_price_for(self, quantity, is_member):
        """Effektiver Preis JE EINHEIT inklusive Mengenstaffel.

        Bei allen Modellen außer 'tiered' identisch zu price_for(); bei 'tiered'
        ersetzt der Staffelpreis den Grundpreis für alle Stück der Position.
        """
        self.ensure_one()
        base = self.price_for(is_member)
        if self._pricing_model() != 'tiered':
            return base
        tier = self.matching_tier(quantity)
        return tier.price_for(is_member) if tier else base

    def billable_units(self, rental_days):
        """Zahl der berechneten Zeiteinheiten für einen Zeitraum.

        'per_day' liefert unverändert die angefangenen Tage — damit rechnen alle
        Bestandsartikel exakt wie bisher. 'per_night' zählt die Nächte (Tage − 1),
        'per_unit' ist zeitlos (1). Bei 'per_km' und 'tiered' entscheidet der am
        Artikel gepflegte Zeitbezug; Voreinstellung 'flat' (= 1) multipliziert den
        Grundpreis NICHT mit dem Zeitraum.
        """
        self.ensure_one()
        days = int(rental_days or 0)
        model = self._pricing_model()
        if model == 'per_day':
            units = days
        elif model == 'per_night':
            units = max(days - 1, 0)
        elif model == 'per_unit':
            units = 1
        else:
            basis = self.price_time_basis or 'flat'
            if basis == 'day':
                units = days
            elif basis == 'night':
                units = max(days - 1, 0)
            else:
                units = 1
        minimum = self.min_billable_units or 0
        if minimum > 0:
            # Default 0 => keine Mindestberechnung => Bestandsverhalten unverändert.
            units = max(units, minimum)
        return units

    @api.depends('pricing_model', 'price_time_basis', 'unit_label')
    def _compute_price_unit_label(self):
        """Klartext der Preiseinheiten — Grundlage für Website, Report und Backend.

        Ohne diesen Text stünde in der Oberfläche weiter pauschal "pro Tag", was bei
        Stück-, Kilometer- und Staffelpreisen schlicht falsch wäre.

        Drei Felder, weil das Kilometermodell ZWEI Beträge hat:
          * price_unit_label      — beschreibt das gesamte Preismodell (Überschrift).
          * price_base_unit_label — Einheit NUR des Grundpreises.
          * price_km_unit_label   — Einheit NUR des Kilometersatzes (sonst leer).
        Bei allen Modellen mit genau einem Betrag ist price_base_unit_label mit
        price_unit_label identisch; Aufrufer, die eine einzelne Zahl beschriften,
        können deshalb immer price_base_unit_label verwenden.
        """
        basis_text = {
            'day': _('je Tag'),
            'night': _('je Nacht'),
            'flat': _('pauschal je Ausleihe'),
        }
        for rec in self:
            unit = (rec.unit_label or '').strip() or _('Stück')
            model = rec.pricing_model or 'per_day'
            basis = basis_text.get(rec.price_time_basis or 'flat')
            # Vorbelegung für jeden Datensatz: das Kilometermodell überschreibt sie,
            # alle anderen behalten sie (stored/unstored Compute-Regel: jedem Record
            # im Loop einen Wert zuweisen).
            rec.price_km_unit_label = False
            if model == 'per_day':
                rec.price_unit_label = _('pro Tag')
            elif model == 'per_night':
                rec.price_unit_label = _('pro Nacht')
            elif model == 'per_unit':
                rec.price_unit_label = _('pro %s (pauschal, ohne Zeitbezug)') % unit
            elif model == 'per_km':
                rec.price_unit_label = _('Grundgebühr %(basis)s zuzüglich Kilometerpreis') % {
                    'basis': basis}
                rec.price_base_unit_label = _('Grundgebühr %(basis)s') % {'basis': basis}
                rec.price_km_unit_label = _('je gefahrenem Kilometer')
                continue
            else:
                rec.price_unit_label = _('pro %(unit)s %(basis)s (Mengenstaffel)') % {
                    'unit': unit, 'basis': basis}
            rec.price_base_unit_label = rec.price_unit_label

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


class KjrRentalPriceTier(models.Model):
    """Mengenstaffel eines Verleihartikels ("ab Menge X gilt Preis Y").

    Eigenes Kindmodell statt weiterer Felder am Artikel, weil die Staffel als
    einziges Preismodell echt 1:n ist: Zahl und Grenzen der Stufen sind je Artikel
    verschieden und sollen von der Geschäftsstelle frei gepflegt werden können.
    Preise starten bei 0,00 € — die echte Preisliste trägt der KJR ein.
    """
    _name = 'kjr.rental.price.tier'
    _description = 'Verleih-Mengenstaffel'
    _order = 'item_id, min_quantity'

    item_id = fields.Many2one(
        'kjr.rental.item', string='Artikel', required=True, ondelete='cascade', index=True)
    min_quantity = fields.Integer(
        string='Ab Menge', required=True, default=1,
        help='Ab dieser Menge gilt der hinterlegte Staffelpreis — und zwar für ALLE '
             'Stück der Position, nicht nur für die darüber liegenden.')
    price = fields.Float(
        string='Staffelpreis Standard (€)', digits=(8, 2),
        help='Preis je Einheit ab der angegebenen Menge für Nicht-Mitglieder. '
             'TODO(KJR): echte Staffelpreise eintragen, Startwert ist bewusst 0,00 €.')
    price_member = fields.Float(
        string='Staffelpreis Mitglied (€)', digits=(8, 2),
        help='Preis je Einheit ab der angegebenen Menge für KJR-Mitglieder. Wird nur '
             'verwendet, wenn am Artikel "Eigener Mitgliedstarif" aktiv ist. '
             'TODO(KJR): echte Staffelpreise eintragen.')

    _min_quantity_unique = models.Constraint(
        'UNIQUE(item_id, min_quantity)',
        'Je Artikel darf jede Mengengrenze der Staffel nur einmal vorkommen.',
    )

    @api.constrains('min_quantity')
    def _check_min_quantity(self):
        for rec in self:
            if rec.min_quantity < 1:
                raise ValidationError(_(
                    'Die Mengengrenze einer Staffel muss mindestens 1 betragen.'))

    def price_for(self, is_member):
        """Staffelpreis je nach Mitgliedsstatus — gleiche Regel wie am Artikel:
        der Mitgliedspreis greift nur, wenn der Mitgliedstarif am Artikel aktiv ist
        (dann auch bei 0 € = gratis)."""
        self.ensure_one()
        if is_member and self.item_id.has_member_price:
            return self.price_member
        return self.price

    @api.depends('min_quantity', 'price')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = _('ab %(qty)d Stück') % {'qty': rec.min_quantity or 0}
