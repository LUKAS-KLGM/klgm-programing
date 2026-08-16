# -*- coding: utf-8 -*-
"""Digitale Belegliste zum Zuschussantrag (Alternative zum Datei-Upload).

Bildet die Papier-Belegliste des KJR Oberallgäu 1:1 ab: je Zeile ein Beleg mit
Datum, Beleg-Nr., Empfänger/Einzahler (ANBest-P-Pflichtspalte), Bezeichnung,
Art (Einnahme/Ausgabe), Position und Betrag. Die Positionen spiegeln die
Kostenaufstellung des Antrags, damit Belege und Summen zusammenpassen.
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class KjrGrantReceipt(models.Model):
    _name = 'kjr.grant.receipt'
    _description = 'Beleg (Belegliste Zuschussantrag)'
    _order = 'date, sequence, id'
    # Kein 'name'-Feld: die Bezeichnung dient als Anzeigename (Breadcrumb, M2O).
    _rec_name = 'description'

    # Einnahme-Positionen als Klassenkonstante, damit Controller, Views und
    # Folgemodule dieselbe Zuordnung Position ⇄ Richtung verwenden.
    INCOME_CATEGORIES = ('tn_fees', 'municipality', 'association', 'bjr', 'income_other')

    # ── Zuordnung ────────────────────────────────────────────────────────────
    application_id = fields.Many2one(
        'kjr.grant.application', string='Antrag',
        required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(string='Nr.', default=10)

    # ── Belegdaten ───────────────────────────────────────────────────────────
    date = fields.Date(string='Datum', required=True)
    receipt_no = fields.Char(string='Beleg-Nr.')
    # ANBest-P verlangt den Zahlungsempfänger bzw. Einzahler je Beleg — Pflichtspalte.
    partner_name = fields.Char(string='Empfänger / Einzahler', required=True)
    description = fields.Char(string='Bezeichnung', required=True)

    # ── Art, Position und Betrag ─────────────────────────────────────────────
    direction = fields.Selection(
        [('income', 'Einnahme'), ('expense', 'Ausgabe')],
        string='Art', required=True, default='expense',
    )
    category = fields.Selection(
        [
            ('tn_fees', 'Einnahme: Teilnehmerbeiträge'),
            ('municipality', 'Einnahme: Zuschuss Gemeinde'),
            ('association', 'Einnahme: Zuschuss Verband'),
            ('bjr', 'Einnahme: Zuschuss BJR/BezJR'),
            ('income_other', 'Einnahme: Sonstige Zuschüsse'),
            ('accommodation', 'Ausgabe: Unterkunft, Verpflegung, Miete'),
            ('transport', 'Ausgabe: Fahrtkosten'),
            ('referees', 'Ausgabe: Honorare Referenten'),
            ('allowances', 'Ausgabe: Aufwandsentschädigungen'),
            ('materials', 'Ausgabe: Arbeits- und Hilfsmittel'),
            ('jl_fees', 'Ausgabe: Kursgebühren JL-Schulung'),
            ('cost_other', 'Ausgabe: Sonstige Ausgaben'),
        ],
        string='Position', required=True,
    )
    # Immer positiv erfassen — das Vorzeichen steckt in 'direction'.
    amount = fields.Float(string='Betrag (€)', required=True, digits=(12, 2))
    note = fields.Char(string='Bemerkung')

    # ── Prüfungen ────────────────────────────────────────────────────────────
    @api.constrains('amount')
    def _check_amount_positive(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_(
                    'Der Betrag eines Belegs muss größer als 0,00 € sein '
                    '(Beleg „%(desc)s"). Ob es sich um eine Einnahme oder eine '
                    'Ausgabe handelt, wird über das Feld „Art" gesteuert — bitte '
                    'keine negativen Beträge erfassen.',
                    desc=rec.description or _('ohne Bezeichnung'),
                ))

    @api.constrains('direction', 'category')
    def _check_category_matches_direction(self):
        """Position und Art müssen zusammenpassen, sonst laufen die Belegsummen
        gegen die falsche Seite der Kostenaufstellung."""
        labels = dict(self._fields['category'].selection)
        for rec in self:
            if not rec.direction or not rec.category:
                continue
            is_income_category = rec.category in self.INCOME_CATEGORIES
            expected = 'income' if is_income_category else 'expense'
            if rec.direction != expected:
                raise ValidationError(_(
                    'Beleg „%(desc)s": Die Position „%(cat)s" ist eine '
                    '%(expected)s-Position, die Art ist aber auf „%(actual)s" '
                    'gesetzt. Bitte entweder die Art auf „%(expected)s" ändern '
                    'oder eine passende Position auswählen.',
                    desc=rec.description or _('ohne Bezeichnung'),
                    cat=labels.get(rec.category, rec.category),
                    expected=_('Einnahme') if is_income_category else _('Ausgabe'),
                    actual=_('Einnahme') if rec.direction == 'income' else _('Ausgabe'),
                ))
