# -*- coding: utf-8 -*-
"""19.0.5.11.0 (Termin 13.10.2026, Theresa 15.10.): nur noch zwei Einordnungen.

Juleica-Schulung, Rettungsschwimmer-Kurs und Sonstige werden zu
"Aus- und Weiterbildungen" ('training'). Der Juleica-Bezug bleibt im Feld
is_juleica_course erhalten (bisher gespeichertes Compute-Feld, ab jetzt ein
eigener Haken; die Spalte bleibt mit ihren Werten bestehen). Zur Sicherheit wird
er für frühere Juleica-Schulungen ausdrücklich gesetzt.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        SELECT column_name FROM information_schema.columns
         WHERE table_name = 'event_event' AND column_name = 'is_juleica_course'
    """)
    if cr.fetchone():
        cr.execute("""
            UPDATE event_event SET is_juleica_course = TRUE
             WHERE kjr_event_type = 'juleica_course'
        """)
    cr.execute("""
        UPDATE event_event SET kjr_event_type = 'training'
         WHERE kjr_event_type IN ('juleica_course', 'rescue_course', 'other')
    """)
    _logger.info('kjr_event 19.0.5.11.0: %s Veranstaltung(en) auf "Aus- und '
                 'Weiterbildungen" umgeschlüsselt.', cr.rowcount)
