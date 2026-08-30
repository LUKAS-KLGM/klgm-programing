# -*- coding: utf-8 -*-
"""Mitgliedskennzeichen am Kontakt für die Einrichtungsbuchung.

WARUM wird `is_kjr_member` hier ein DRITTES Mal definiert (es existiert bereits in
kjr_grant/models/res_partner.py und kjr_rental/models/res_partner.py)?

kjr_facility ist wie kjr_rental bewusst eigenständig und hängt NICHT von kjr_grant
ab — die Einrichtungsbuchung soll auch bei Jugendringen laufen, die das
Zuschusswesen nicht einsetzen. Ohne eigene Definition wäre die Tarifgruppe im
öffentlichen Anfrageformular nicht ableitbar (siehe
KjrFacilityWebsite._website_tariff).

Odoo legt pro Feldname genau eine Spalte an: bei gemeinsamer Installation teilen
sich alle drei Module dieselbe Spalte `res_partner.is_kjr_member` — es gibt keine
doppelte Datenhaltung und kein Abgleichproblem. Wird nur eines der Module
installiert, bleibt es für sich allein lauffähig.

WICHTIG für künftige Änderungen: Typ (Boolean), Name und Default müssen zu den
Definitionen in kjr_grant und kjr_rental passen. Zusatzattribute (z. B. tracking)
NICHT hier setzen, sonst hängt das Verhalten von der Ladereihenfolge der Module ab.
"""
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_kjr_member = fields.Boolean(
        string='KJR-Mitgliedsverband', default=False,
        help='Kontakte mit diesem Kennzeichen erhalten bei der Einrichtungsbuchung '
             'den Mitgliedstarif, sofern für die Einrichtung ein Tarif der Gruppe '
             '"KJR-Mitgliedsverband" gepflegt ist. Die Feinunterscheidung '
             'Partnerorganisation/kommerziell setzt die Geschäftsstelle im Backend.',
    )
