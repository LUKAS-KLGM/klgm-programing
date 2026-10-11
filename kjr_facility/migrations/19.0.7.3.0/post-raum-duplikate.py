# -*- coding: utf-8 -*-
"""Doppelte Schlafräume je Einrichtung erkennen und melden, ohne Datenänderung.

BEFUND, DER DAZU GEFÜHRT HAT
────────────────────────────
Am 01.09.2026 standen die zwölf Schlafräume einer Einrichtung doppelt in der
Datenbank: ein von Hand gepflegter Satz mit den realen Zimmernummern und ein
zweiter Satz aus einem Modul-Update. ``bed_total`` summiert alle aktiven Räume und
zeigte dadurch 84 statt 42 Betten.

URSACHE IST NICHT EIN FEHLENDES ``noupdate``
────────────────────────────────────────────
Die Seed-Räume HABEN stabile XML-IDs, und ``data/kjr_facility_data.xml`` liegt
seit jeher vollständig unter ``<data noupdate="1">``. ``odoo/tools/convert.py``
zeigt, warum das nicht reicht: im Update-Modus bricht Odoo bei ``noupdate`` nur
dann ab, wenn ``ir.model.data._load_xmlid(xid)`` den Datensatz FINDET. Kennt die
Instanz die XML-ID noch nicht, greift anschließend ``elif not nodeattr2bool(rec,
'forcecreate', True)`` — und weil ``forcecreate`` standardmäßig True ist, wird der
Datensatz normal ANGELEGT. Genau so entstanden die Dubletten: die von Hand
gepflegten Zimmer trugen keine XML-ID, das Update legte die Seed-Zimmer daneben.

WARUM HIER NICHTS AUTOMATISCH AUFGERÄUMT WIRD
─────────────────────────────────────────────
Welcher Satz der echte ist, kann das Modul nicht wissen: die Handdaten tragen die
realen Zimmernummern, die Seed-Daten die aus den Unterlagen abgeleiteten. Ein
automatisches Archivieren würde im schlechteren Fall die gepflegten Daten
verdecken. Entschieden wird das in der Geschäftsstelle, dieses Skript liefert ihr
die Liste dazu.

DIESES SKRIPT IST NUR DER LAUF ZUM UMSTIEGSZEITPUNKT
────────────────────────────────────────────────────
``odoo/modules/migration.py`` führt ein Skript nur aus, wenn die installierte
Version KLEINER ist als die Ordnerversion und diese kleiner/gleich der neuen
Manifestversion ist. Nach dem Upgrade steht 19.0.7.3.0 in der Datenbank, womit
dieses Skript bei JEDEM späteren Upgrade übersprungen wird. Ein Migrationsordner
ist damit der falsche Ort für eine Dauerprüfung.

Die eigentliche Prüfung liegt deshalb am Modell und wird wiederholbar vom Cron
``kjr_facility.cron_kjr_room_duplicates`` aufgerufen
(``models/kjr_facility.py``: ``_find_duplicate_rooms`` /
``report_duplicate_rooms`` / ``_cron_room_duplicates``). Dieses Skript ruft
dieselbe Methode EINMALIG beim Umstieg auf, damit die Geschäftsstelle den Befund
sofort im Upgrade-Log sieht und nicht erst beim ersten Cron-Lauf.

Abgrenzung: ``migrations/19.0.3.1.0/post-migration.py`` hat für den damaligen
Einzelfall sehr wohl automatisch archiviert und ist auf allen Instanzen längst
gelaufen. Dieses Skript ERSETZT es nicht. Weil jener Lauf die Platzhalter nur
ARCHIVIERT hat (``active = False``), zählt ``report_duplicate_rooms`` archivierte
Räume bewusst nicht als Dublettenmitglied, sondern nur als Hinweis — sonst
meldete jede Bestandsinstanz dauerhaft eine Dublette, die längst bereinigt ist.

Idempotent: reiner Lesevorgang, kein ``write``, kein ``unlink``.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

MODULE = 'kjr_facility'
VERSION = '19.0.7.3.0'


def migrate(cr, version):
    if not version:
        return  # Neuinstallation: es gibt nichts, was doppelt sein könnte.

    env = api.Environment(cr, SUPERUSER_ID, {})
    env['kjr.facility'].search([]).report_duplicate_rooms(
        herkunft='Migration %s %s' % (MODULE, VERSION))
