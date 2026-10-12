# -*- coding: utf-8 -*-
"""Verleihartikel mit Bestand, Lager und Tarifen."""
import re
from datetime import date as date_cls
from urllib.parse import quote, unquote, urlencode

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import format_date

# B51: Pfad, den der QR-Code des Inventaretiketts trägt. Die normale
# Handykamera (ohne Odoo-App) öffnet damit direkt den Artikel; der Scanner
# im Backend erkennt denselben Pfad und liest den Barcode daraus.
SCAN_URL_PATH = '/kjr_rental/scan/'
# B52: Farbe eines Lagerorts als HTML-Hexwert (#RRGGBB), wie ihn das
# Odoo-Farbfeld (widget="color") liefert. Geprüft, weil der Wert ungefiltert
# in Inline-Styles von Etikett und Scanansicht landet.
HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')

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
    icon = fields.Char(
        string='FontAwesome-Icon',
        help='FontAwesome-4-Klasse, z. B. fa-bus oder fa-music. Odoo 19 liefert '
             'FontAwesome 4.7.0 aus; die neueren FA-5/6-Namen (fa-futbol, fa-utensils) '
             'gibt es dort nicht und sie rendern als leerer Kasten.',
    )
    item_count = fields.Integer(string='Artikel', compute='_compute_item_count')

    def _compute_item_count(self):
        data = self.env['kjr.rental.item']._read_group(
            [('category_id', 'in', self.ids)], groupby=['category_id'], aggregates=['__count'])
        mapped = {c.id: n for c, n in data}
        for rec in self:
            rec.item_count = mapped.get(rec.id, 0)


class KjrRentalLocation(models.Model):
    """Frei pflegbare Lagerorte (statt hartkodierter Auswahl).

    B52: Ein Lagerort ist der Bestand, zu dem ein Gegenstand gehört
    (z. B. Spielewagen, normaler Verleih, Reserveverleih). Farbe und Hinweis
    beantworten beim Zurückräumen die Frage "wohin gehört das Teil?".
    """
    _name = 'kjr.rental.location'
    _description = 'Verleih-Lager'
    _order = 'sequence, name'

    name = fields.Char(string='Bezeichnung', required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    color = fields.Char(
        string='Farbe',
        help='Erkennungsfarbe des Lagerorts, z. B. die Farbe des Klebebands oder '
             'der Kisten im Regal. Erscheint als Farbstreifen auf dem '
             'Inventaretikett, in der Artikelliste und in der Scanansicht, damit '
             'beim Zurückräumen auf einen Blick klar ist, wohin ein Teil gehört.',
    )
    note = fields.Text(
        string='Hinweis zum Zurückräumen',
        help='Wo genau liegt dieser Lagerort, z. B. "Keller, Raum 2, linkes Regal". '
             'Wird in der Scanansicht unter dem Lagerort angezeigt.',
    )
    item_count = fields.Integer(string='Artikel', compute='_compute_item_count')

    def _compute_item_count(self):
        data = self.env['kjr.rental.item']._read_group(
            [('location_id', 'in', self.ids)], groupby=['location_id'],
            aggregates=['__count'])
        mapped = {loc.id: n for loc, n in data}
        for rec in self:
            rec.item_count = mapped.get(rec.id, 0)

    @api.model
    def _normalize_color(self, value):
        """Leerwerte zu False, sonst Leerzeichen abschneiden und klein schreiben."""
        if not value:
            return False
        return value.strip().lower() or False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'color' in vals:
                vals['color'] = self._normalize_color(vals['color'])
        return super().create(vals_list)

    def write(self, vals):
        if 'color' in vals:
            vals = dict(vals, color=self._normalize_color(vals['color']))
        return super().write(vals)

    @api.constrains('color')
    def _check_color(self):
        for rec in self:
            if rec.color and not HEX_COLOR_RE.match(rec.color):
                raise ValidationError(_(
                    'Die Farbe des Lagerorts "%(name)s" muss ein Farbwert im Format '
                    '#RRGGBB sein (z. B. #1f77b4). Bitte die Farbe über das '
                    'Farbfeld auswählen.', name=rec.name))

    @api.model
    def _name_key(self, name):
        """Vergleichsschlüssel für "gleichnamig": Groß-/Kleinschreibung und
        mehrfache Leerzeichen spielen keine Rolle."""
        return ' '.join((name or '').split()).casefold()

    @api.model
    def _ensure_named(self, entries):
        """Lagerorte anlegen, zu denen es noch KEINEN gleichnamigen Datensatz gibt.

        entries: Liste von (Reihenfolge, Bezeichnung). Archivierte Lagerorte zählen
        mit (active_test=False): wer einen Lagerort bewusst archiviert hat, bekommt
        ihn nicht als Dublette zurück. Vorhandene Datensätze (auch bereits doppelt
        vorhandene) werden weder geändert noch zusammengeführt noch gelöscht.
        Gibt die neu angelegten Lagerorte zurück; ein zweiter Aufruf legt nichts an.
        """
        known = {
            self._name_key(name)
            for name in self.with_context(active_test=False).search([]).mapped('name')
        }
        created = self.browse()
        for sequence, name in entries:
            key = self._name_key(name)
            if not key or key in known:
                continue
            created |= self.create({'name': name, 'sequence': sequence})
            known.add(key)
        return created


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
        'kjr.rental.location', string='Lager', ondelete='set null',
        help='Bestand bzw. Lagerort, zu dem der Gegenstand gehört (z. B. Spielewagen, '
             'normaler Verleih, Reserveverleih). Steht auf dem Etikett und wird beim '
             'Scannen und in der Rücknahme angezeigt.')
    quantity_total = fields.Integer(string='Bestand gesamt', default=1)

    # --- B52: Wohin gehört das Teil beim Zurückräumen? -------------------------
    storage_bin = fields.Char(
        string='Lagerplatz',
        help='Genauer Platz innerhalb des Lagerorts, z. B. "Regal 3, Fach B" oder '
             '"Kiste rot". Steht auf dem Etikett, in der Rücknahme und in der '
             'Scanansicht.')
    location_color = fields.Char(
        related='location_id.color', string='Farbe Lagerort')
    return_location_label = fields.Char(
        string='Gehört zurück nach', compute='_compute_return_location_label',
        help='Lagerort und Lagerplatz in einer Zeile, so wie sie auf dem Etikett '
             'stehen.')

    # --- B51: QR-Code und Scan -------------------------------------------------
    label_qr_value = fields.Char(
        string='Inhalt des QR-Codes', compute='_compute_label_qr',
        help='Adresse, die der QR-Code auf dem Inventaretikett trägt. Die Kamera '
             'eines Handys öffnet damit nach der Anmeldung direkt diesen Artikel; '
             'der Scanner im Verleih erkennt die Adresse ebenfalls. Leer, solange '
             'kein Barcode vergeben ist.')
    label_qr_src = fields.Char(
        string='QR-Code-Bild', compute='_compute_label_qr',
        help='Bildadresse des QR-Codes für das Etikett (Odoo-Route /report/barcode).')
    open_order_count = fields.Integer(
        string='Offene Ausleihen', compute='_compute_open_order_count',
        help='Reservierte und ausgegebene Ausleihen mit diesem Artikel.')
    issued_order_count = fields.Integer(
        string='Ausgegebene Ausleihen', compute='_compute_open_order_count',
        help='Ausgegebene Ausleihen mit diesem Artikel. Nur ihnen kann eine Rückgabe '
             'per Scan zugeordnet werden (Button "Rückgabe zuordnen").')

    # --- Preismodell -----------------------------------------------------------
    # Die echte Preisliste des Betreibers kennt mehr als den Tagespreis: Fahrzeuge werden
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
             'je Tag oder je Nacht anfällt. Voreingestellt ist "pauschal", die '
             'zurückhaltende Variante, weil eine unbeabsichtigte Multiplikation mit '
             'dem Zeitraum die Rechnung erhöhen würde.',
    )
    # TODO Betreiber: Zeitbezug je Artikelgruppe mit der echten Preisliste abgleichen.
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
        help='Grundpreis für Mitglieder, gleiche Bezugsgröße wie der Standardpreis.',
    )
    # TODO Betreiber: Kilometersätze der echten Preisliste eintragen. Startwert ist
    # bewusst 0,00 €, damit kein erfundener Satz in Angebot oder Rechnung landet.
    price_per_km = fields.Float(
        string='Kilometerpreis Standard (€/km)', digits=(8, 2),
        help='Nur beim Preismodell "Grundgebühr + Kilometerpreis": Satz je gefahrenem '
             'Kilometer für Nicht-Mitglieder. Startwert 0,00 €, die echte Preisliste '
             'pflegt die Geschäftsstelle.',
    )
    price_member_per_km = fields.Float(
        string='Kilometerpreis Mitglied (€/km)', digits=(8, 2),
        help='Kilometersatz für Mitglieder (nur bei aktivem Mitgliedstarif). '
             'Startwert 0,00 €, die Preisliste pflegt die Geschäftsstelle.',
    )
    # TODO Betreiber: echte Kilometersätze für den Mitgliedstarif eintragen.
    min_billable_units = fields.Integer(
        string='Mindestberechnete Einheiten', default=0,
        help='Mindestzahl berechneter Tage bzw. Nächte (0 = keine Mindestberechnung, '
             'bisheriges Verhalten). Relevant vor allem bei "Pro Nacht": eine Ausleihe '
             'ohne Übernachtung ergibt 0 Nächte und damit 0 €.',
    )
    # TODO Betreiber: Ist eine Mindestberechnung gewünscht und mit welchem Wert?
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
        help='Einheit, die AUSSCHLIESSLICH zum Grundpreis (price_per_day) gehört, '
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
    icon = fields.Char(
        string='FontAwesome-Icon',
        help='FontAwesome-4-Klasse, z. B. fa-bus. Odoo 19 liefert FontAwesome 4.7.0 '
             'aus; die neueren FA-5/6-Namen (fa-futbol, fa-utensils) gibt es dort '
             'nicht und sie rendern als leerer Kasten.',
    )

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

    # --- B52: Lagerort/Lagerplatz -------------------------------------------------
    @api.depends('location_id.name', 'storage_bin')
    def _compute_return_location_label(self):
        for rec in self:
            parts = [p for p in (rec.location_id.name, (rec.storage_bin or '').strip()) if p]
            rec.return_location_label = ' · '.join(parts) if parts else _(
                'Kein Lagerort hinterlegt')

    # --- B51: QR-Code auf dem Etikett ----------------------------------------------
    @api.depends('barcode')
    def _compute_label_qr(self):
        """QR-Code-Inhalt und Bildadresse.

        Der QR-Code trägt eine Adresse statt des nackten Barcodes: die Kamera-App
        jedes Handys erkennt QR-Codes und öffnet die Adresse; der Controller
        /kjr_rental/scan/<code> leitet nach der Anmeldung auf den Artikel weiter.
        Der Code128 bleibt zusätzlich auf dem Etikett (Handscanner, Klartext).
        Das Bild kommt aus der Kern-Route /report/barcode des Moduls web, die den
        Typ 'QR' unterstützt (ir.actions.report.barcode); kein stock_barcode.
        """
        for rec in self:
            barcode = self._normalize_scan_value(rec.barcode)
            if not barcode:
                rec.label_qr_value = False
                rec.label_qr_src = False
                continue
            base = (rec.get_base_url() or '').rstrip('/')
            value = '%s%s%s' % (base, SCAN_URL_PATH, quote(barcode, safe=''))
            rec.label_qr_value = value
            # Abfrageparameter statt Pfadsegment: die Adresse im QR-Code enthält
            # selbst "//" und "/", die im Pfad nicht unverändert ankämen.
            # barLevel M verkraftet ca. 15 % Beschädigung (Etiketten im Lager).
            rec.label_qr_src = '/report/barcode/?%s' % urlencode({
                'barcode_type': 'QR',
                'value': value,
                'width': 300,
                'height': 300,
                'barLevel': 'M',
            })

    def _compute_open_order_count(self):
        # Eine Gruppierung je Artikel und Status: jede Ausleihe hat genau einen
        # Status, die Summe über die Status ist also die Zahl der Ausleihen.
        data = self.env['kjr.rental.order.line']._read_group(
            [('item_id', 'in', self.ids),
             ('order_id.state', 'in', ('reserved', 'issued'))],
            groupby=['item_id', 'order_id.state'], aggregates=['order_id:count_distinct'])
        open_counts = {}
        issued_counts = {}
        for item, state, count in data:
            open_counts[item.id] = open_counts.get(item.id, 0) + count
            if state == 'issued':
                issued_counts[item.id] = issued_counts.get(item.id, 0) + count
        for rec in self:
            rec.open_order_count = open_counts.get(rec.id, 0)
            rec.issued_order_count = issued_counts.get(rec.id, 0)

    def action_view_open_orders(self):
        """Smart-Button: reservierte und ausgegebene Ausleihen dieses Artikels."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ausleihen: %s', self.name),
            'res_model': 'kjr.rental.order',
            'view_mode': 'list,form',
            'domain': [('line_ids.item_id', '=', self.id),
                       ('state', 'in', ('reserved', 'issued'))],
        }

    # --- B51: Scannen (Kamera, Handscanner, Eingabe) --------------------------------
    @api.model
    def _scan_extract_code(self, raw):
        """Gelesenen Wert auf den Barcode bzw. die Inventarnummer zurückführen.

        Der QR-Code des Etiketts enthält eine Adresse (…/kjr_rental/scan/<code>);
        Code128 und Handeingabe liefern den Code direkt.
        """
        value = (raw or '').strip()
        if SCAN_URL_PATH in value:
            value = value.split(SCAN_URL_PATH, 1)[1]
            value = value.split('?', 1)[0].split('#', 1)[0].strip('/')
            value = unquote(value).strip()
        return value

    @api.model
    def _find_by_scan(self, raw):
        """Artikel zu einem gescannten Wert: zuerst Barcode, dann Inventarnummer,
        jeweils exakt und danach ohne Rücksicht auf Groß-/Kleinschreibung.
        Ein leeres Recordset, wenn nichts passt oder der Wert nicht eindeutig ist."""
        code = self._scan_extract_code(raw)
        if not code:
            return self.browse()
        escaped = code.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        for fname in ('barcode', 'code'):
            for operator, value in (('=', code), ('=ilike', escaped)):
                found = self.search([(fname, operator, value)], limit=2)
                if len(found) == 1:
                    return found
        return self.browse()

    def _scan_order_data(self, order_id=None):
        """Offene Ausleihen dieses Artikels für die Scanansicht."""
        self.ensure_one()
        domain = [('item_id', '=', self.id),
                  ('order_id.state', 'in', ('reserved', 'issued'))]
        if order_id:
            domain.append(('order_id', '=', order_id))
        lines = self.env['kjr.rental.order.line'].search(domain)
        state_labels = dict(self.env['kjr.rental.order']._fields['state']
                            ._description_selection(self.env))
        result = []
        for order in lines.order_id.sorted(lambda o: (o.state != 'issued', o.date_to or o.date_from)):
            order_lines = lines.filtered(lambda l, o=order: l.order_id == o)
            quantity = sum(order_lines.mapped('quantity'))
            scanned = sum(order_lines.mapped('return_scanned_qty'))
            result.append({
                'id': order.id,
                'name': order.name,
                'partner': order.partner_id.display_name,
                'date_from': format_date(self.env, order.date_from),
                'date_to': format_date(self.env, order.date_to),
                'state': order.state,
                'state_label': state_labels.get(order.state, order.state),
                'quantity': quantity,
                'scanned': scanned,
                'can_return': order.state == 'issued' and scanned < quantity,
                'order_scan_summary': order.return_scan_summary or '',
                'order_scan_complete': order.return_scan_complete,
            })
        return result

    def _scan_item_data(self):
        """Artikelangaben für die Scanansicht (Name, Nummern, wohin zurückräumen)."""
        self.ensure_one()
        color = self.location_id.color
        return {
            'id': self.id,
            'name': self.name,
            'code': self.code or '',
            'barcode': self.barcode or '',
            'category': self.category_id.display_name or '',
            'location': self.location_id.name or '',
            'location_color': color if color and HEX_COLOR_RE.match(color) else '',
            'location_note': self.location_id.note or '',
            'storage_bin': self.storage_bin or '',
            'return_location_label': self.return_location_label or '',
            'quantity_total': self.quantity_total,
        }

    @api.model
    def kjr_scan_lookup(self, raw=None, item_id=None, order_id=None):
        """Einstieg der Client-Aktion "Scannen".

        raw: gelesener Wert (QR-Adresse, Barcode, Inventarnummer);
        item_id: alternativ ein bereits bekannter Artikel (Button am Artikel);
        order_id: optional auf eine Ausleihe beschränken (Rücknahme aus dem Vorgang).
        Gibt ein Wörterbuch für die Anzeige zurück; nichts wird geändert.
        """
        if item_id:
            item = self.browse(int(item_id)).exists()
        else:
            item = self._find_by_scan(raw)
        code = self._scan_extract_code(raw) if raw else ''
        if not item:
            return {
                'found': False,
                'code': code,
                'message': _('Zum Code "%s" wurde kein Verleihartikel gefunden. Ist '
                             'der Barcode am Artikel hinterlegt?', code) if code else
                           _('Bitte einen Code scannen oder eingeben.'),
            }
        item.check_access('read')
        order_id = int(order_id) if order_id else None
        return {
            'found': True,
            'code': code,
            'item': item._scan_item_data(),
            'orders': item._scan_order_data(order_id=order_id),
        }

    def action_open_scan(self):
        """Button am Artikel: Scanansicht mit diesem Artikel im Modus Rückgabe öffnen.
        Der Artikel wird dort nur angezeigt; zugeordnet wird er erst per Scan oder per
        Klick auf "Rückgabe zuordnen" bei der Ausleihe (kein automatisches Zählen beim
        Öffnen, sonst zählte jeder Neuaufbau der Ansicht ein weiteres Stück)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'kjr_rental_scan',
            'name': _('Scannen'),
            'context': {'kjr_scan_item_id': self.id, 'kjr_scan_mode': 'return'},
        }

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
    Preise starten bei 0,00 €; die echte Preisliste trägt der Betreiber ein.
    """
    _name = 'kjr.rental.price.tier'
    _description = 'Verleih-Mengenstaffel'
    _order = 'item_id, min_quantity'

    item_id = fields.Many2one(
        'kjr.rental.item', string='Artikel', required=True, ondelete='cascade', index=True)
    min_quantity = fields.Integer(
        string='Ab Menge', required=True, default=1,
        help='Ab dieser Menge gilt der hinterlegte Staffelpreis, und zwar für ALLE '
             'Stück der Position, nicht nur für die darüber liegenden.')
    price = fields.Float(
        string='Staffelpreis Standard (€)', digits=(8, 2),
        help='Preis je Einheit ab der angegebenen Menge für Nicht-Mitglieder. '
             'Startwert ist bewusst 0,00 €; die Preise pflegt die Geschäftsstelle.')
    price_member = fields.Float(
        string='Staffelpreis Mitglied (€)', digits=(8, 2),
        help='Preis je Einheit ab der angegebenen Menge für Mitglieder. Wird nur '
             'verwendet, wenn am Artikel "Eigener Mitgliedstarif" aktiv ist. '
             'Startwert ist bewusst 0,00 €; die Preise pflegt die Geschäftsstelle.')
    # TODO Betreiber: echte Staffelpreise für Standard- und Mitgliedstarif eintragen.

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
