# -*- coding: utf-8 -*-
"""19.0.1.2.0: Entscheidung im Termin 13.10.2026 - keine elektronische
Unterschrift für die Einwilligung im Ferienprogramm.

Die Brücke bleibt installiert, wird aber ausgeschaltet
(Systemparameter kjr_event_sign.enabled entfernt = Auslieferungszustand
"aus"; so zeigt auch das Einstellungsformular den Haken sicher als aus). Ohne die Einstellung liefert
event.event._kjr_consent_mode() nie 'sign'; im Anmeldeformular erscheint dann
nichts von der digitalen Unterschrift (alle Stellen hängen an
kjr_consent_mode == 'sign'). Bereits versendete Unterschriftsanfragen bleiben
unberührt. Wieder einschalten: Einstellungen → KJR Einwilligung.

Außerdem (Prüfbericht 22.10.2026): Beschriftungen der mitgelieferten
Vorlagen (noupdate, kommen per Update nicht an) auf "Teilnehmer:in" bzw.
Doppelpunkt-Gendern umstellen, nur wo noch der alte Auslieferungstext steht.
Der Text im PDF selbst ("Ihr Kind", "der/des") bleibt (Gestaltung der
Vorlage, siehe Bericht).
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        DELETE FROM ir_config_parameter WHERE key = 'kjr_event_sign.enabled'
    """)
    if cr.rowcount:
        _logger.info('kjr_event_sign 19.0.1.2.0: digitale Einwilligung ausgeschaltet '
                     '(Entscheidung 13.10.2026).')

    env = api.Environment(cr, SUPERUSER_ID, {})
    renames = {
        'kjr_event_sign.item_child_name': ('Name des Kindes', 'Name der Teilnehmer:in'),
        'kjr_event_sign.item_v2_child_name': ('Name des Kindes / Teilnehmer/in',
                                              'Name Teilnehmer:in'),
        'kjr_event_sign.item_v2_guardian_name': ('Name der/des Erziehungsberechtigten',
                                                 'Name der Erziehungsberechtigten'),
        'kjr_event_sign.sign_item_role_guardian': ('Erziehungsberechtigte/r',
                                                   'Erziehungsberechtigte'),
    }
    for xmlid, (old, new) in renames.items():
        record = env.ref(xmlid, raise_if_not_found=False)
        if record and 'name' in record._fields and record.name == old:
            record.name = new
            _logger.info('kjr_event_sign 19.0.1.2.0: %s umbenannt.', xmlid)
