# -*- coding: utf-8 -*-
"""Tarife je Nutzergruppe inkl. konfigurierbarer Umsatzsteuer."""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class KjrFacilityTariff(models.Model):
    _name = 'kjr.facility.tariff'
    _description = 'KJR Einrichtungstarif'
    _order = 'sequence, name'

    name = fields.Char(string='Bezeichnung', required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    facility_id = fields.Many2one(
        'kjr.facility', string='Einrichtung',
        help='Leer = gilt für alle Einrichtungen.',
    )
    tariff_type = fields.Selection([
        ('kjr_member', 'KJR-Mitgliedsverband'),
        ('partner', 'Partnerorganisation'),
        ('standard', 'Standard (gemeinnützig)'),
        ('commercial', 'Kommerziell'),
    ], string='Tarifgruppe', required=True, default='standard')
    price_per_person_night = fields.Float(string='Preis pro Person/Nacht (€)', digits=(8, 2))
    price_flat_per_night = fields.Float(
        string='Pauschale pro Nacht (€)', digits=(8, 2),
        help='Optionale fixe Pauschale je Nacht zusätzlich zum Personenpreis.',
    )
    meal_breakfast = fields.Float(string='Frühstück p. P./Tag (€)', digits=(8, 2))
    meal_half = fields.Float(string='Halbpension p. P./Tag (€)', digits=(8, 2))
    meal_full = fields.Float(string='Vollpension p. P./Tag (€)', digits=(8, 2))
    # F-Verpflegung: Reine Sichtbarkeitshilfe für die Formularansicht. Ein
    # invisible-Ausdruck kann nur Felder auswerten, die im Arch vorhanden sind —
    # 'facility_id.offers_catering' ist im View nicht auswertbar, deshalb dieses
    # Feld. Bewusst KEIN related: Ein Tarif ohne Einrichtung gilt für ALLE
    # Einrichtungen; ein related lieferte dort immer False und ein Jugendring mit
    # Verpflegung, der nur globale Tarife pflegt, könnte seine Verpflegungssätze
    # gar nicht mehr erfassen. Das Feld ist nicht gespeichert und geht in keine
    # Berechnung ein — an bestehenden Tarifen und Buchungen ändert sich nichts.
    show_meal_prices = fields.Boolean(
        string='Verpflegungspreise anzeigen', compute='_compute_show_meal_prices',
        help='Technisches Hilfsfeld: steuert nur, ob die Verpflegungssätze in der '
             'Tarifmaske sichtbar sind. Es zeigt sie, wenn die zugeordnete '
             'Einrichtung "Verpflegung anbieten" aktiviert hat. Bei einem Tarif '
             'ohne Einrichtung (gilt für alle) zeigt es sie, wenn mindestens eine '
             'Einrichtung verpflegt.')
    # F1: Zusatzpositionen (Kurbeitrag, Endreinigung) und Wochentagstarif.
    # Die Berechnung selbst liegt in kjr.facility.booking._compute_amounts.
    #
    # BENENNUNG: Kundensichtbar heisst die Position ueberall "Kurbeitrag"
    # (Entscheidung vom 11.10.2026). Sachlich ist es ein kommunaler Gaestebeitrag;
    # ein Fremdenverkehrsbeitrag waere eine Abgabe der BETRIEBE, nicht der Gaeste,
    # und war deshalb die falsche Bezeichnung. Der technische Feldname bleibt
    # bewusst visitor_tax_*, weil eine Umbenennung eine Spaltenmigration und ein
    # Nachziehen aller Verweise in @api.depends, Views, Report und Controller
    # erzwaenge, ohne fachlich etwas zu aendern. Umgestellt sind nur
    # Beschriftungen und Texte.
    #
    # TODO(Kunde): Der SATZ ist nicht belegt. Der Preisblock nennt keinen Betrag,
    # die Vertragsbedingungen einen davon abweichenden. Der Satz ist bei der
    # Standortgemeinde bzw. der Geschaeftsstelle zu erfragen und erst danach hier
    # einzutragen; bis dahin bleibt das Feld bewusst auf 0. Offen ist ebenso,
    # welche Befreiungen die Satzung der Standortgemeinde tatsaechlich vorsieht.
    visitor_tax_per_person_night = fields.Float(
        string='Kurbeitrag p. P./Nacht (€)', digits=(8, 2),
        help='Kurbeitrag: kommunaler Gästebeitrag je Person und Übernachtung, je '
             'Einrichtung zu pflegen. '
             'ACHTUNG zur Berechnung: Der Beitrag fällt NICHT pauschal für '
             'alle Gäste an. Berechnet wird er nur auf die Teilnehmenden. '
             'Betreuende und Begleitpersonen sind als solche befreit und gehen gar '
             'nicht erst in die Grundmenge ein. Im Buchungsfeld "Zusätzlich vom '
             'Kurbeitrag befreit" werden ausschließlich die WEITEREN Befreiungen '
             'unter den Teilnehmenden erfasst (nach bisheriger Praxis z. B. '
             'Einwohnerinnen und Einwohner der Standortgemeinde, kleine Kinder, '
             'Schwerbehinderte); Betreuende dort NICHT mitzählen, sonst werden sie '
             'doppelt abgezogen. '
             '0 = es wird kein Kurbeitrag berechnet.')
    final_cleaning_fee = fields.Float(
        string='Endreinigung (einmalig, €)', digits=(8, 2),
        help='Pauschale für die Endreinigung. Sie wird EINMALIG je Buchung berechnet, '
             'NICHT pro Nacht und NICHT pro Person. Bisher wurde die Endreinigung über '
             'die Ausstattung (Preis/Tag) abgebildet und dadurch pro Nacht vervielfacht; '
             'genau dafür gibt es dieses eigene Feld. 0 = keine Endreinigungspauschale.')
    weekday_price_per_person_night = fields.Float(
        string='Preis p. P./Nacht Mo-Fr (€)', digits=(8, 2),
        help='Reduzierter Personenpreis für Aufenthalte, die vollständig von Montag bis '
             'Freitag liegen (Wochentagsbelegung außerhalb der Wochenend-Nachfrage). '
             'Gilt erst ab der unter "Mindestnächte für Mo-Fr-Preis" hinterlegten Dauer. '
             '0 = kein Wochentagstarif, es gilt immer der reguläre Personenpreis.')
    weekday_min_nights = fields.Integer(
        string='Mindestnächte für Mo-Fr-Preis', default=0,
        help='Ab wie vielen Nächten der reduzierte Mo-Fr-Preis greift. '
             '0 = kein Wochentagstarif.')
    # TODO(Kunde): Die umsatzsteuerliche Einordnung der Beherbergung ist noch
    # ungeklaert und kann sich je Tarifgruppe unterscheiden (Befreiung, ermaessigter
    # Satz oder Regelsatz). Sie ist mit der Steuerberatung des Betreibers zu klaeren;
    # der bestaetigte Steuersatz wird anschliessend hier je Tarifgruppe hinterlegt.
    # Bewusst als Kommentar und nicht im Hilfetext: eine interne Arbeitsnotiz gehoert
    # nicht in den Tooltip, den jede Geschaeftsstelle sieht.
    tax_id = fields.Many2one(
        'account.tax', string='Umsatzsteuer',
        domain="[('type_tax_use', '=', 'sale')]",
        help='Umsatzsteuer dieser Tarifgruppe. Solange das Feld leer ist, greift die '
             'Vorgabesteuer der Gesellschaft.',
    )

    @api.depends('facility_id', 'facility_id.offers_catering')
    def _compute_show_meal_prices(self):
        """Verpflegungssätze nur anzeigen, wenn überhaupt verpflegt wird.

        Nur Sichtbarkeit — hinterlegte Sätze bleiben unangetastet und werden bei
        bereits erfassten Buchungen weiterhin genauso verrechnet wie bisher.
        """
        any_catering = None
        for rec in self:
            if rec.facility_id:
                rec.show_meal_prices = rec.facility_id.offers_catering
                continue
            # Tarif ohne Einrichtung = gilt für alle: konservativ einblenden,
            # sobald irgendeine Einrichtung verpflegt. sudo(), weil das eine reine
            # Anzeigefrage ist und auch für Leser ohne Einrichtungsrechte gilt.
            if any_catering is None:
                any_catering = bool(self.env['kjr.facility'].sudo().search_count(
                    [('offers_catering', '=', True)], limit=1))
            rec.show_meal_prices = any_catering

    @api.constrains(
        'price_per_person_night', 'price_flat_per_night',
        'meal_breakfast', 'meal_half', 'meal_full',
        'visitor_tax_per_person_night', 'final_cleaning_fee',
        'weekday_price_per_person_night',
    )
    def _check_positive_amounts(self):
        """Negative Beträge sind in einem Tarif immer ein Erfassungsfehler."""
        amount_fields = (
            'price_per_person_night', 'price_flat_per_night',
            'meal_breakfast', 'meal_half', 'meal_full',
            'visitor_tax_per_person_night', 'final_cleaning_fee',
            'weekday_price_per_person_night',
        )
        for rec in self:
            for fname in amount_fields:
                if rec[fname] < 0:
                    raise ValidationError(_(
                        'Der Betrag "%(field)s" darf im Tarif "%(name)s" nicht '
                        'negativ sein.',
                        field=rec._fields[fname].string, name=rec.name or ''))

    @api.constrains('weekday_price_per_person_night', 'weekday_min_nights')
    def _check_weekday_tariff(self):
        """Wochentagstarif nur vollständig oder gar nicht.

        Ein Preis ohne Mindestnächte (oder umgekehrt) greift nie und fällt im
        Betrieb niemandem auf — deshalb hier hart abfangen.
        """
        for rec in self:
            if rec.weekday_min_nights < 0:
                raise ValidationError(_(
                    'Die Mindestnächte für den Mo-Fr-Preis dürfen nicht negativ sein '
                    '(0 = kein Wochentagstarif).'))
            has_price = bool(rec.weekday_price_per_person_night)
            has_nights = rec.weekday_min_nights > 0
            if has_price and not has_nights:
                raise ValidationError(_(
                    'Tarif "%(name)s": Es ist ein Mo-Fr-Preis hinterlegt, aber keine '
                    'Mindestzahl an Nächten. Der reduzierte Preis würde nie greifen. '
                    'Bitte "Mindestnächte für Mo-Fr-Preis" setzen oder den Mo-Fr-Preis '
                    'auf 0 zurücksetzen.', name=rec.name or ''))
            if has_nights and not has_price:
                raise ValidationError(_(
                    'Tarif "%(name)s": Es sind Mindestnächte für den Mo-Fr-Preis '
                    'hinterlegt, aber kein Mo-Fr-Preis. Bitte den Preis erfassen oder '
                    'die Mindestnächte auf 0 zurücksetzen.', name=rec.name or ''))
