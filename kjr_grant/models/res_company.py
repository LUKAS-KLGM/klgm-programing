# -*- coding: utf-8 -*-
"""res.company-Erweiterung: konfigurierbare Rechtsform für White-Label-Dokumente.

Damit die Apps an beliebige Jugendringe verkaufbar sind, kommen Name/Anschrift/
Kontakt in allen Dokumenten aus der Odoo-Firma (res.company). Die Rechtsform ist
ein eigenes, pflegbares Feld (z. B. „Körperschaft des öffentlichen Rechts" für einen
KJR, oder „e. V." für einen anders organisierten Träger)."""
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    kjr_legal_form = fields.Char(
        string='Rechtsform (für Bescheide/Dokumente)',
        default='Körperschaft des öffentlichen Rechts',
        help='Wird im Briefkopf der erzeugten Dokumente (z. B. Zuschussbescheid) '
             'unter dem Namen angezeigt. Leer lassen, wenn keine Rechtsform-Zeile '
             'gewünscht ist.',
    )
