# -*- coding: utf-8 -*-
"""Datenschutzangaben der öffentlichen Formulare konfigurierbar machen.

Die sieben öffentlichen Formulare dieser Modulfamilie (Zuschussantrag,
Verbandsportal, Einrichtungsbuchung, Materialverleih, Veranstaltungen) zeigen
einen Datenschutzblock nach Art. 13 DSGVO. Sechs Angaben darin kann nur der
Träger selbst liefern; sie werden seit 19.0.15.6.0 aus Systemparametern gelesen
und NICHT mehr in die Vorlagen geschrieben.

Bis hierher fehlte dazu jede Oberfläche: kein Modul legte die Schlüssel an, und
der Administrator musste die exakten Namen raten. Auf einer frischen Instanz
steht deshalb auf jedem Formular sechsmal das gelbe Etikett „Angabe folgt".
Diese Erweiterung schliesst die Lücke.

WARUM ``config_parameter`` UND KEIN SEED
────────────────────────────────────────
``ir.config_parameter.value`` ist ``required=True`` und der Schlüssel ist
``UNIQUE`` (``odoo/addons/base/models/ir_config_parameter.py``). Leere Werte
liessen sich also gar nicht ausliefern, und vier Module dürften dieselben sechs
Schlüssel nicht je einzeln seeden - der zweite Install bräche am UNIQUE-Index.
``config_parameter`` am Feld löst beides: Odoo liest und schreibt den Parameter
beim Öffnen bzw. Speichern der Einstellungen und legt bei der Installation
nichts an (``odoo/addons/base/models/res_config.py``: ``get_values`` liest mit
``get_param``, ``set_values`` schreibt mit ``set_param``).

Ein geleertes Feld löscht den Parameter wieder: ``set_values`` macht aus einem
leeren Char-Wert ``False``, und ``set_param(key, False)`` entfernt den Datensatz.
Genau das ist gewollt - dann steht auf den Formularen wieder der Warnhinweis
statt einer stillen Leerstelle.

Die Schlüssel heissen bewusst ``kjr.privacy.*`` und nicht ``kjr_grant.*``: sie
werden auch von kjr_event, kjr_facility und kjr_rental gelesen, die nicht von
diesem Modul abhängen. Gepflegt werden sie hier, weil kjr_grant das
Anwendungsmodul ist, das die Familie fachlich klammert.

REICHWEITE - WAS DAMIT NOCH NICHT ERLEDIGT IST
──────────────────────────────────────────────
Genau WEIL die drei Geschwistermodule nicht von kjr_grant abhängen, schliesst
diese Maske die Lücke nur für Datenbanken, in denen kjr_grant installiert ist.
Ist in einer Datenbank nur kjr_facility (oder kjr_rental, oder kjr_event)
installiert, gibt es für die sechs Angaben weiterhin keine Eingabemaske, und auf
dem Buchungs- bzw. Veranstaltungsformular steht sechsmal der Platzhalter. Der
Audit-Punkt ist damit NICHT modulfamilienweit geschlossen.

Zwei Wege stehen offen, beide greifen in fremde Manifeste ein und gehören
deshalb in ein eigenes Arbeitspaket:

* denselben ``_inherit = 'res.config.settings'``-Block in jedes der drei Module
  legen - Odoo führt mehrfach geerbte TransientModel-Felder zusammen, solange
  Feldname und ``config_parameter`` übereinstimmen; oder
* ein gemeinsames Basismodul ``kjr_base`` anlegen, das die sechs Felder (und nur
  die) trägt, und alle vier Module davon abhängen lassen. Sauberer, aber eine
  Abhängigkeitsänderung an vier Manifesten und damit ein Migrationsthema.

Bis dahin steht der Punkt in der CHANGELOG-Rubrik "Offen".
"""
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    kjr_privacy_operator = fields.Char(
        string='Technischer Betrieb / Auftragsverarbeiter',
        config_parameter='kjr.privacy.operator',
        help='Wer die Website technisch betreibt (Hosting, Auftragsverarbeitung). '
             'Erscheint im Datenschutzblock aller öffentlichen Formulare. '
             'Leer lassen zeigt dort weiterhin den Warnhinweis.',
    )
    kjr_privacy_controller = fields.Char(
        string='Verantwortlicher',
        config_parameter='kjr.privacy.controller',
        help='Name, Anschrift und Kontakt der verantwortlichen Stelle '
             'nach Art. 4 Nr. 7 DSGVO.',
    )
    kjr_privacy_dpo = fields.Char(
        string='Datenschutzbeauftragte/r',
        config_parameter='kjr.privacy.dpo',
        help='Kontakt der/des Datenschutzbeauftragten für Fragen der Betroffenen.',
    )
    kjr_privacy_legal_basis = fields.Char(
        string='Rechtsgrundlage',
        config_parameter='kjr.privacy.legal_basis',
        help='Rechtsgrundlage der Verarbeitung. Legt der Träger gemeinsam mit '
             'der/dem Datenschutzbeauftragten fest (Audit-Befund K1, offen).',
    )
    kjr_privacy_retention = fields.Char(
        string='Aufbewahrungs-/Löschfrist',
        config_parameter='kjr.privacy.retention',
        help='Wie lange die Angaben aufbewahrt werden. Unabhängig davon '
             'anonymisiert das System Teilnahmelisten nach der Frist aus dem '
             'Systemparameter kjr_grant.participant_retention_years.',
    )
    kjr_privacy_authority = fields.Char(
        string='Zuständige Aufsichtsbehörde',
        config_parameter='kjr.privacy.authority',
        help='Zuständige Datenschutz-Aufsichtsbehörde, an die sich Betroffene '
             'wenden können.',
    )
