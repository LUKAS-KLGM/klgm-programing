# -*- coding: utf-8 -*-
"""B52: Lagerorte des Verleihs (Spielewagen, normaler Verleih, Reserveverleih).

In der Besprechung zum Verleih wurde festgehalten, dass zurückgegebene Teile
aus drei Beständen kommen: Spielewagen, normaler Verleih und Reserveverleih.
Damit jeder Gegenstand einem dieser Bestände zugeordnet werden kann, legt das
Skript die drei Lagerorte als normale, frei pflegbare Datensätze von
kjr.rental.location an.

Regeln:
- Angelegt wird nur, wenn es noch KEINEN gleichnamigen Lagerort gibt.
  Gleichnamig heißt: gleiche Bezeichnung ohne Rücksicht auf Groß-/Klein-
  schreibung und mehrfache Leerzeichen; archivierte Lagerorte zählen mit.
- Bestehende Lagerorte werden weder umbenannt noch zusammengeführt noch
  gelöscht. Das gilt ausdrücklich auch für bereits doppelt vorhandene
  Lagerorte: das Aufräumen entscheidet die Geschäftsstelle.
- Keine XML-ID: die Sätze sind Instanzdaten und werden beim nächsten Upgrade
  nicht angefasst. Bewusst nicht in data/kjr_rental_data.xml, weil ein
  noupdate-Satz mit neuer XML-ID beim Upgrade VOR jeder Prüfung angelegt würde
  und so eine Dublette zu einem bereits gepflegten Lagerort entstünde. Neu-
  installationen bekommen die Namen nicht (White Label, siehe
  tests/test_seed_data.py).
- Idempotent; ein zweiter Lauf legt nichts an.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# (Reihenfolge, Bezeichnung). Die Reihenfolge hängt die drei Orte hinter die
# Platzhalter-Lagerorte (10, 20, 30) aus den Stammdaten.
LAGERORTE = [
    (40, 'Spielewagen'),
    (50, 'Normaler Verleih'),
    (60, 'Reserveverleih'),
]


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    created = env['kjr.rental.location']._ensure_named(LAGERORTE)
    _logger.info(
        'kjr_rental 19.0.5.7.0: %d Lagerort(e) angelegt, %d bereits vorhanden.',
        len(created), len(LAGERORTE) - len(created))
