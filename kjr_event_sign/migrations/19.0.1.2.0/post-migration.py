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
"""
import logging

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
