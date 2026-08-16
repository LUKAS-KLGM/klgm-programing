# -*- coding: utf-8 -*-
"""Mitgliedskennzeichen am Kontakt für den Materialverleih.

WARUM wird `is_kjr_member` hier ein ZWEITES Mal definiert (es existiert bereits in
kjr_grant/models/res_partner.py)?

kjr_rental ist laut Architekturentscheidung ADR-1 bewusst eigenständig und hängt
NICHT von kjr_grant ab — der Verleih soll auch bei Jugendringen laufen, die das
Zuschusswesen nicht einsetzen. Ohne eigene Definition wäre der Mitgliedstarif
(kjr.rental.item.price_for) hier nicht ableitbar.

Beide Module definieren das Feld deshalb absichtlich NAMENSGLEICH auf res.partner.
Odoo legt pro Feldname genau eine Spalte an: bei gemeinsamer Installation teilen
sich kjr_grant und kjr_rental dieselbe Spalte `res_partner.is_kjr_member` — es
gibt keine doppelte Datenhaltung und kein Abgleichproblem. Wird nur eines der
beiden Module installiert, bleibt es für sich allein lauffähig.

WICHTIG für künftige Änderungen: Typ (Boolean), Name und Default müssen zu der
Definition in kjr_grant passen. Zusatzattribute (z. B. tracking) NICHT hier
setzen, sonst hängt das Verhalten von der Ladereihenfolge der Module ab.
"""
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_kjr_member = fields.Boolean(
        string='KJR-Mitgliedsverband', default=False,
        help='Kontakte mit diesem Kennzeichen erhalten im Materialverleih den '
             'Mitgliedstarif (sofern am Artikel ein eigener Mitgliedstarif gepflegt '
             'ist, auch 0 € = gratis). Das Kennzeichen wird beim Anlegen eines '
             'Verleihvorgangs automatisch übernommen und kann dort im Einzelfall '
             'übersteuert werden.',
    )
