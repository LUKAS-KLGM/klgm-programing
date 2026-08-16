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
    # F1: Zusatzpositionen (Fremdenverkehrsbeitrag, Endreinigung) und Wochentagstarif.
    # Die Berechnung selbst liegt in kjr.facility.booking._compute_amounts.
    visitor_tax_per_person_night = fields.Float(
        string='Fremdenverkehrsbeitrag p. P./Nacht (€)', digits=(8, 2),
        help='Kommunaler Fremdenverkehrsbeitrag je Person und Übernachtung '
             '(Immenstadt: 1,10 €). ACHTUNG: Der Beitrag fällt NICHT pauschal für '
             'alle Gäste an. Berechnet wird er nur auf die Teilnehmenden — '
             'Betreuende/Begleitpersonen sind als solche befreit und gehen gar nicht '
             'erst in die Grundmenge ein. Im Buchungsfeld "Von Fremdenverkehrsbeitrag '
             'befreit" werden ausschließlich die WEITEREN Befreiungen unter den '
             'Teilnehmenden erfasst (Einwohner der Standortgemeinde, Kinder unter '
             '7 Jahren, Schwerbehinderte); Betreuende dort NICHT mitzählen, sonst '
             'werden sie doppelt abgezogen. '
             '0 = die Einrichtung erhebt keinen Fremdenverkehrsbeitrag.')
    final_cleaning_fee = fields.Float(
        string='Endreinigung (einmalig, €)', digits=(8, 2),
        help='Pauschale für die Endreinigung. Sie wird EINMALIG je Buchung berechnet — '
             'NICHT pro Nacht und NICHT pro Person. Bisher wurde die Endreinigung über '
             'die Ausstattung (Preis/Tag) abgebildet und dadurch pro Nacht vervielfacht; '
             'genau dafür gibt es dieses eigene Feld. 0 = keine Endreinigungspauschale.')
    weekday_price_per_person_night = fields.Float(
        string='Preis p. P./Nacht Mo–Fr (€)', digits=(8, 2),
        help='Reduzierter Personenpreis für Aufenthalte, die vollständig von Montag bis '
             'Freitag liegen (Wochentagsbelegung außerhalb der Wochenend-Nachfrage). '
             'Gilt erst ab der unter "Mindestnächte für Mo–Fr-Preis" hinterlegten Dauer. '
             '0 = kein Wochentagstarif, es gilt immer der reguläre Personenpreis.')
    weekday_min_nights = fields.Integer(
        string='Mindestnächte für Mo–Fr-Preis', default=0,
        help='Ab wie vielen Nächten der reduzierte Mo–Fr-Preis greift. '
             '0 = kein Wochentagstarif.')
    tax_id = fields.Many2one(
        'account.tax', string='Umsatzsteuer',
        domain="[('type_tax_use', '=', 'sale')]",
        help='STEUERLICH FINAL ZU PRÜFEN: Bei Jugendgruppen kommt regelmäßig die '
             'USt-Befreiung nach § 4 Nr. 23 UStG bzw. der ermäßigte Satz (7 %, '
             'Zweckbetrieb § 68 Nr. 8 AO) in Betracht; bei kommerzieller Nutzung 19 %. '
             'Der passende Steuersatz ist hier je Tarifgruppe zu hinterlegen.',
    )

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
                    'Die Mindestnächte für den Mo–Fr-Preis dürfen nicht negativ sein '
                    '(0 = kein Wochentagstarif).'))
            has_price = bool(rec.weekday_price_per_person_night)
            has_nights = rec.weekday_min_nights > 0
            if has_price and not has_nights:
                raise ValidationError(_(
                    'Tarif "%(name)s": Es ist ein Mo–Fr-Preis hinterlegt, aber keine '
                    'Mindestzahl an Nächten. Der reduzierte Preis würde nie greifen. '
                    'Bitte "Mindestnächte für Mo–Fr-Preis" setzen oder den Mo–Fr-Preis '
                    'auf 0 zurücksetzen.', name=rec.name or ''))
            if has_nights and not has_price:
                raise ValidationError(_(
                    'Tarif "%(name)s": Es sind Mindestnächte für den Mo–Fr-Preis '
                    'hinterlegt, aber kein Mo–Fr-Preis. Bitte den Preis erfassen oder '
                    'die Mindestnächte auf 0 zurücksetzen.', name=rec.name or ''))
