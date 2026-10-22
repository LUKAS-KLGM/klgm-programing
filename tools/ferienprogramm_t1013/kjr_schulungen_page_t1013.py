# -*- coding: utf-8 -*-
"""Passt die Website-Seite /service/schulungen an die neue Einordnung an
(kjr_event 19.0.5.11.0: nur noch "Ferienprogramm" und "Aus- und
Weiterbildungen").

Befund Prod (22.10.2026, lesend): Ansicht 4585 (Schlüssel
website.service-schulungen) sucht die Kurstermine mit
    ('kjr_event_type', 'in', ['juleica_course', 'rescue_course'])
Diese Werte gibt es nach dem Update nicht mehr (Migration schlüsselt auf
'training' um), die Liste wäre leer. Ersetzt wird der Filter durch
    ('kjr_event_type', '=', 'training')
Texte der Seite (Juleica, Rettungsschwimmer) bleiben unverändert.

Autor:   KLGM UG (haftungsbeschraenkt), https://www.klgm-consulting.de
Lizenz:  OPL-1
Stand:   2026-10-22

NUR durch eine berechtigte Person, NACH dem Update von kjr_event, nach Snapshot:
    odoo shell -d <db> --no-http < kjr_schulungen_page_t1013.py              # Dry-Run
    KJR_FIX_WRITE=1 odoo shell -d <db> --no-http < kjr_schulungen_page_t1013.py
"""
import os

WRITE = os.environ.get('KJR_FIX_WRITE') == '1'
OLD = "('kjr_event_type', 'in', ['juleica_course', 'rescue_course'])"
NEW = "('kjr_event_type', '=', 'training')"

env = env  # noqa: F821 - von odoo shell bereitgestellt
views = env['ir.ui.view'].with_context(active_test=False).search(
    [('key', '=', 'website.service-schulungen')])
# Die Ansicht ist nur in en_US gespeichert (arch_db = {"en_US": ...}); der
# Filter ist kein übersetzbarer Text. Geschrieben wird deshalb in en_US, die
# Übersetzungen der Texte bleiben über die Term-Zuordnung erhalten.
for view in views:
    arch = view.with_context(lang='en_US').arch_db or ''
    hit = OLD in arch
    print('Ansicht %s (Website %s): alter Filter %s' % (
        view.id, view.website_id.id, 'gefunden' if hit else 'nicht gefunden'))
    if hit and WRITE:
        view.with_context(lang='en_US', no_cow=True).arch_db = arch.replace(OLD, NEW)
        print('  de_DE danach:', NEW in (view.with_context(lang='de_DE').arch_db or ''))

if WRITE:
    env.cr.commit()
    print('Geschrieben.')
else:
    env.cr.rollback()
    print('Dry-Run, nichts geschrieben.')
