# -*- coding: utf-8 -*-
"""Zimmeraufteilung Diepolz: Platzhalter durch die echte Aufteilung ersetzen.

Ausgangslage: Der Seed lieferte für das Jugendtagungshaus Diepolz drei
Platzhalterzimmer („Zimmer 1", „Zimmer 2", „Schlafsaal") mit zusammen 24 Betten,
während der Beschreibungstext von 42 Betten in 12 Zimmern sprach. Marvin
Gutknecht hat das am 17.08.2026 auf der Kundeninstanz von Hand korrigiert
(Quelle: „KJR Website - Ist-Zustand 2026-08-17", Abschnitt 10); der Seed im Repo
zieht jetzt nach.

Warum dieses Skript nötig ist: Die Stammdaten liegen unter <data noupdate="1">.
Bestehende Datensätze werden dadurch beim Upgrade zwar nicht überschrieben — NEUE
Records aus derselben Datei werden aber sehr wohl angelegt. Auf einer Instanz, auf
der die echten Zimmer bereits von Hand gepflegt wurden, entstünden dadurch
Doppelungen: die zwölf Seed-Zimmer zusätzlich zu den zwölf gepflegten. Das Skript
räumt genau das auf.

Es ist idempotent und fasst nichts an, was in Buchungen verwendet wird.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# Platzhalter des alten Seeds: (External ID, erwarteter Name, erwartete Kapazität).
# Nur wenn Name UND Kapazität noch exakt passen, gilt der Datensatz als unberührter
# Platzhalter — hat jemand ihn gepflegt, bleibt er stehen.
LEGACY_ROOMS = [
    ('kjr_facility.room_diepolz_1', 'Zimmer 1 (6 Betten)', 6),
    ('kjr_facility.room_diepolz_2', 'Zimmer 2 (6 Betten)', 6),
    ('kjr_facility.room_diepolz_3', 'Schlafsaal (12 Betten)', 12),
]


def _room_key(room):
    """Vergleichsschlüssel: führende Zimmernummer, sonst der normalisierte Name.

    Marvin hat die Zimmer als „Zimmer 11" o. ä. angelegt, der Seed als
    „Zimmer 11 (1. OG)". Über die Nummer greifen beide Schreibweisen ineinander.
    """
    name = (room.name or '').strip().lower()
    for token in name.replace('(', ' ').replace(')', ' ').split():
        if token.isdigit():
            return token
    return name


def migrate(cr, version):
    if not version:
        return  # Neuinstallation: der Seed ist bereits korrekt.
    env = api.Environment(cr, SUPERUSER_ID, {})

    facility = env.ref('kjr_facility.facility_diepolz', raise_if_not_found=False)
    if not facility:
        _logger.info('Diepolz nicht gefunden — Zimmerbereinigung übersprungen.')
        return

    # 1. Unberührte Platzhalter des alten Seeds archivieren (nicht löschen: sie
    #    könnten in Altbuchungen referenziert sein).
    for xmlid, name, capacity in LEGACY_ROOMS:
        room = env.ref(xmlid, raise_if_not_found=False)
        if not room or not room.active:
            continue
        if room.name == name and room.capacity == capacity:
            room.active = False
            _logger.info('Diepolz: Platzhalterzimmer "%s" archiviert.', name)
        else:
            _logger.info(
                'Diepolz: "%s" wurde gepflegt (jetzt "%s", %d Betten) — unverändert gelassen.',
                name, room.name, room.capacity)

    # 2. Doppelte Zimmer zusammenführen. Behalten wird der ältere Datensatz (die
    #    von Hand gepflegte Fassung), das neu angelegte Seed-Duplikat wird
    #    archiviert. Zimmer mit Buchungsbezug werden nie angefasst.
    rooms = env['kjr.facility.room'].search([
        ('facility_id', '=', facility.id), ('active', '=', True),
    ], order='id')
    seen, archived = {}, 0
    for room in rooms:
        key = _room_key(room)
        if key not in seen:
            seen[key] = room
            continue
        duplicate = room
        # Buchungen referenzieren Räume über kjr.facility.booking.room_ids (Many2many),
        # am Raum selbst gibt es keine Gegenrichtung — deshalb hier die Suche.
        if env['kjr.facility.booking'].search_count([('room_ids', 'in', duplicate.id)]):
            _logger.info('Diepolz: "%s" ist doppelt, hat aber Buchungen — bleibt.',
                         duplicate.name)
            continue
        duplicate.active = False
        archived += 1
        _logger.info('Diepolz: doppeltes Zimmer "%s" archiviert (Original: "%s").',
                     duplicate.name, seen[key].name)

    total = sum(env['kjr.facility.room'].search([
        ('facility_id', '=', facility.id), ('active', '=', True),
    ]).mapped('capacity'))
    _logger.info('Diepolz: %d Duplikate archiviert, jetzt %d Betten in %d aktiven Zimmern.',
                 archived, total, len(seen))
    if total != 42:
        _logger.warning(
            'Diepolz: %d Betten statt der erwarteten 42 — bitte die Zimmerliste '
            'im Backend prüfen (Zimmer 25 hat laut Zimmerplan 3, laut Fließtext 4 Betten).',
            total)
