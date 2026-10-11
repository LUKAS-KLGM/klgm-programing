# -*- coding: utf-8 -*-
"""Seed-Korrekturen in Bestandsinstanzen nachziehen (White Label und Icons).

Die betroffenen Sätze stehen in data/kjr_rental_data.xml unter
<data noupdate="1">. Beim Upgrade werden sie deshalb NICHT überschrieben; ohne
dieses Skript behielten Bestandsinstanzen die Ortsnamen des Erstkunden und die
alten Kategorie-Icons, und der Test `test_seed_kategorien_haben_icon` liefe
dort rot, weil die Kategorie "Sonstiges" bis 19.0.5.4.1 gar kein Icon hatte.

Angefasst wird nur, was noch EXAKT den alten Auslieferungswert trägt: hat die
Geschäftsstelle den Datensatz gepflegt, bleibt er unberührt. Jede Änderung wird
protokolliert. Das Skript ist idempotent.

Verweise brechen nicht: kjr.rental.item.location_id zeigt auf die Datensatz-ID,
nicht auf den Namen. Die XML-IDs selbst (loc_sonthofen usw.) bleiben bewusst
unverändert, ein Umbenennen würde beim nächsten Upgrade Dubletten erzeugen.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# (External ID, alter Auslieferungswert, neuer Wert)
LAGERORTE = [
    ('kjr_rental.loc_sonthofen', 'Lager Sonthofen', 'Hauptlager'),
    ('kjr_rental.loc_immenstadt', 'Lager Immenstadt', 'Nebenlager'),
    ('kjr_rental.loc_oberstdorf', 'Lager Oberstdorf', 'Außenlager'),
]

# (External ID, alter Auslieferungswert oder False, neuer Wert)
# fa-bed/fa-sliders statt fa-home/fa-volume-up: fachlich treffender.
# fa-cube bei cat_other: die Kategorie hatte bisher überhaupt kein Icon.
# Alle drei Klassen sind gegen die von Odoo 19 ausgelieferte FontAwesome-4.7.0
# geprüft; FA-5/6-Namen würden als leerer Kasten rendern.
ICONS = [
    ('kjr_rental.cat_tent', 'fa-home', 'fa-bed'),
    ('kjr_rental.cat_tech', 'fa-volume-up', 'fa-sliders'),
    ('kjr_rental.cat_other', False, 'fa-cube'),
    ('kjr_rental.item_tent', 'fa-home', 'fa-bed'),
]


def _setze(env, xmlid, feld, alt, neu):
    """Feld nur dann setzen, wenn es noch den alten Auslieferungswert trägt."""
    rec = env.ref(xmlid, raise_if_not_found=False)
    if not rec:
        _logger.info('%s nicht vorhanden, übersprungen.', xmlid)
        return
    jetzt = rec[feld] or False
    if jetzt == neu:
        return  # bereits erledigt (idempotent)
    if jetzt != (alt or False):
        _logger.info('%s: %s wurde gepflegt (%r), unverändert gelassen.',
                     xmlid, feld, jetzt)
        return
    rec[feld] = neu
    _logger.info('%s: %s von %r auf %r gesetzt.', xmlid, feld, jetzt, neu)


def migrate(cr, version):
    if not version:
        return  # Neuinstallation: der Seed ist bereits korrekt.
    env = api.Environment(cr, SUPERUSER_ID, {})
    # active_test=False: auch archivierte Stammdaten mitnehmen, sonst bliebe ein
    # archivierter Lagerort mit Ortsnamen stehen und taucht beim Reaktivieren
    # wieder auf.
    env = env(context=dict(env.context, active_test=False))

    for xmlid, alt, neu in LAGERORTE:
        _setze(env, xmlid, 'name', alt, neu)
    for xmlid, alt, neu in ICONS:
        _setze(env, xmlid, 'icon', alt, neu)
