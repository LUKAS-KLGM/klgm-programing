# -*- coding: utf-8 -*-
"""Stammdatenkorrekturen aus dem Kundentermin vom 30.07.2026 (Bora Berlinger, KJR OA).

Beleg: Terminmitschnitt „KJR Felderbesprechung" vom 30.07.2026, 00:16:19 — Bora Berlinger woertlich: „bei Jugendleiterschulung, da ist der Maximalbetrag zum Beispiel 50 und nicht 75."

WARUM DIESES SKRIPT NÖTIG IST
─────────────────────────────
Die Förderarten in ``data/kjr_grant_type_data.xml`` liegen bewusst unter
``<data noupdate="1">``. Das schützt die vom KJR im Backend gepflegten Fördersätze
davor, bei jedem Modul-Update auf die Auslieferungswerte zurückgesetzt zu werden.

Die Kehrseite: Odoo schreibt ``noupdate``-Datensätze bei einem Update NICHT mehr an.
Eine Änderung in der XML erreicht damit ausschließlich NEUE Datenbanken – jede
bereits laufende Instanz (Staging, Produktiv beim KJR) behielte die alten Werte.
Deshalb werden die beiden im Termin beschlossenen Korrekturen hier zusätzlich
nachgezogen:

1. Förderart „Investitionszuschuss (Landkreis – konfigurierbar)" wird nicht mehr
   angeboten und daher auf ``active = False`` gesetzt. Der Datensatz wird bewusst
   NICHT gelöscht – bestehende Anträge referenzieren ihn über ``grant_type_id``.
2. Förderart „Jugendleiterschulung (§ 4.4)": Höchstfördersumme von 75,00 € auf
   50,00 € korrigiert – sowohl ``max_amount`` (globale Deckelung) als auch
   ``jl_max_with_juleica`` (Juleica-Zweig), siehe TODO (Bora) weiter unten.
3. Beschreibungstexte (``description``) nachgezogen, die seit der letzten
   Auslieferung geändert wurden. Sie werden im Portal und auf der öffentlichen
   Hilfeseite ausgegeben – in bestehenden DBs stünde sonst weiter der alte Text.

Alle Änderungen sind idempotent und respektieren manuelle Pflege durch den KJR:
Wurde ein Wert bereits verändert (Investitionszuschuss schon deaktiviert, § 4.4
schon auf einen anderen Betrag gesetzt, Beschreibung im Backend umformuliert),
wird er nicht überschrieben, sondern die Änderung mit Begründung übersprungen und
protokolliert.

TODO (Bora) – BITTE BESTÄTIGEN, betrifft ausgezahlte Beträge:
Aus dem Termin ist überliefert „Höchstbetrag der Jugendleiterschulung = 50 €".
Offen blieb, ob die 50 € auch für Teilnehmende MIT Juleica gelten, die bisher bis
75 € erhalten konnten. Dieses Skript setzt Variante A um (konservative, niedrigere
Auslegung):
  • Variante A (aktiv): 50 € ist die Obergrenze für ALLE Fälle. ``max_amount`` = 50 €
    und ``jl_max_with_juleica`` = 50 €; die Quoten bleiben unverändert (ohne Juleica
    50 %, mit Juleica 75 %). Ergebnis: max. 50 € ohne wie mit Juleica.
  • Variante B (Alternative, falls die 50 € nur den Fall OHNE Juleica meinten):
    ``max_amount`` bleibt 75 €, ``jl_max_with_juleica`` bleibt 75 €, nur
    ``jl_max_no_juleica`` gilt mit 50 €. Ergebnis: max. 50 € ohne, max. 75 € mit Juleica.
Hintergrund: ``max_amount`` wirkt in ``_calculate_grant`` als globale Deckelung über
ALLE Berechnungszweige. Bliebe ``jl_max_with_juleica`` bei 75 €, während
``max_amount`` 50 € ist, würden die 75 € nie ausgezahlt – der Antragstellende läse
75 € und bekäme 50 €. Bei Entscheidung für Variante B sind XML, Beschreibungstext
und dieses Skript gemeinsam zurückzudrehen.

Bewusst über die Environment (ORM) statt über rohes SQL, damit Constraints,
Compute-Felder und das Mail-Tracking greifen.
"""

import logging

from odoo import SUPERUSER_ID, api
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)

# ── Zu korrigierende Stammdaten (External ID -> erwarteter Altwert) ──────────
XMLID_INVEST = 'kjr_grant.grant_type_invest'
XMLID_JL_SCHULUNG = 'kjr_grant.grant_type_4_4'
XMLID_FREIZEIT_MEHRTAEGIG = 'kjr_grant.grant_type_4_1b'

# Nur wenn der Betrag noch exakt diesem Auslieferungswert entspricht, wird
# korrigiert. Alles andere ist bewusste Pflege durch den KJR.
JL_SCHULUNG_ALT = 75.0
JL_SCHULUNG_NEU = 50.0

# ``max_amount``/``jl_max_with_juleica`` sind digits=(8, 2) – Vergleich daher auf
# 2 Nachkommastellen.
BETRAG_PRECISION = 2

# ── Nachzuziehende Beschreibungstexte ────────────────────────────────────────
# ``description`` wird im Portal und auf der öffentlichen Hilfeseite ausgegeben.
# Geändert wird nur, wenn der Text noch WÖRTLICH dem zuletzt ausgelieferten
# Original entspricht – hat der KJR im Backend umformuliert, bleibt sein Text.
# Format: (External ID, Altext (Auslieferung bis 19.0.9), Neutext (19.0.10.0.0))
BESCHREIBUNGEN = (
    (
        # § 4.4: Text an die tatsächlich ausgezahlten Beträge angeglichen –
        # er versprach „mit Juleica: 75 % (max. 75 €)", ausgezahlt werden aber
        # wegen der 50-€-Deckelung höchstens 50 € (siehe TODO (Bora) oben).
        XMLID_JL_SCHULUNG,
        '50 % der Selbstkosten (max. 50 €), mit Juleica: 75 % (max. 75 €). '
        'Kein Jahreslimit. Auszahlung auf Privatkonto möglich.',
        'Zuschuss zu den Selbstkosten (Fahrtkosten + Kursgebühren): ohne Juleica '
        '50 % der Selbstkosten, mit Juleica 75 % der Selbstkosten. In beiden Fällen '
        'höchstens 50 € je Schulung. Kein Jahreslimit. Auszahlung auf ein Privatkonto '
        'möglich.',
    ),
    (
        # § 4.1b: reine Wording-Umstellung „Jugendleiter" -> „Gruppenleitungen",
        # einheitlich zur Bezeichnung in Formular, Backend und Bescheid.
        XMLID_FREIZEIT_MEHRTAEGIG,
        'Mehrtägige Fahrten und Lager. Min. eine Übernachtung. Zuschuss: 8 € pro '
        'TN/Tag, max. 600 €. Jugendleiter mit Juleica erhalten +50 % Bonus. '
        'Max. 4 Maßnahmen/Jahr.',
        'Mehrtägige Fahrten und Lager. Min. eine Übernachtung. Zuschuss: 8 € pro '
        'TN/Tag, max. 600 €. Gruppenleitungen mit Juleica erhalten +50 % Bonus. '
        'Max. 4 Maßnahmen/Jahr.',
    ),
)


def _get_record(env, xmlid):
    """Löst eine External ID auf und gibt den Datensatz zurück (oder ein leeres
    Recordset, wenn ir_model_data den Eintrag nicht kennt oder der Datensatz in
    der Zwischenzeit gelöscht wurde)."""
    record = env.ref(xmlid, raise_if_not_found=False)
    if not record:
        return None
    # Dangling ir_model_data-Zeile (Datensatz gelöscht, Verweis übrig) abfangen.
    return record.exists() or None


def _deaktiviere_investitionszuschuss(env):
    """Förderart „Investitionszuschuss" abschalten (Entscheidung Bora, 30.07.2026)."""
    grant_type = _get_record(env, XMLID_INVEST)
    if grant_type is None:
        _logger.info(
            "kjr_grant 19.0.10.0.0: Förderart %s nicht gefunden – "
            "übersprungen (bereits gelöscht oder nie installiert).",
            XMLID_INVEST,
        )
        return

    if not grant_type.active:
        _logger.info(
            "kjr_grant 19.0.10.0.0: Förderart „%s“ (ID %s) ist bereits inaktiv – "
            "keine Änderung nötig.",
            grant_type.name, grant_type.id,
        )
        return

    grant_type.write({'active': False})
    _logger.info(
        "kjr_grant 19.0.10.0.0: Förderart „%s“ (ID %s) auf active=False gesetzt – "
        "wird laut Entscheidung Bora (KJR OA) vom 30.07.2026 nicht mehr angeboten. "
        "Der Datensatz bleibt erhalten, damit bestehende Anträge ihre Förderart "
        "weiterhin referenzieren können.",
        grant_type.name, grant_type.id,
    )


def _korrigiere_betrag(grant_type, fname, alt, neu):
    """Setzt ``fname`` auf ``neu`` – aber nur, wenn dort noch exakt der
    Auslieferungswert ``alt`` steht. Gibt True zurück, wenn geschrieben wurde."""
    aktuell = grant_type[fname]
    if float_compare(aktuell, alt, precision_digits=BETRAG_PRECISION) != 0:
        # Entweder schon migriert oder vom KJR bewusst anders gepflegt – in beiden
        # Fällen darf hier nichts überschrieben werden.
        _logger.info(
            "kjr_grant 19.0.10.0.0: Förderart „%s“ (ID %s) hat %s = %.2f € "
            "und nicht den Auslieferungswert %.2f € – übersprungen, um manuelle "
            "Pflege des KJR bzw. eine bereits erfolgte Migration nicht zu "
            "überschreiben.",
            grant_type.name, grant_type.id, fname, aktuell, alt,
        )
        return False

    grant_type.write({fname: neu})
    _logger.info(
        "kjr_grant 19.0.10.0.0: Förderart „%s“ (ID %s): %s von %.2f € auf "
        "%.2f € korrigiert (Entscheidung Bora, KJR OA, vom 30.07.2026).",
        grant_type.name, grant_type.id, fname, alt, neu,
    )
    return True


def _korrigiere_hoechstbetrag_jl_schulung(env):
    """§ 4.4 Jugendleiterschulung: Höchstfördersumme 75,00 € -> 50,00 €.

    Betrifft ZWEI Felder, die zusammengehören (siehe TODO (Bora) im Modulkopf):
      • ``max_amount`` – globale Deckelung über alle Berechnungszweige,
      • ``jl_max_with_juleica`` – Höchstbetrag im Juleica-Zweig. Bliebe der bei
        75 €, würde die globale Deckelung ihn ohnehin auf 50 € kappen; der
        Antragstellende läse aber 75 € im Formular. Deshalb wird er mitgezogen.
    Beide Felder werden unabhängig voneinander geprüft: hat der KJR nur eines
    davon von Hand gepflegt, bleibt genau dieses unangetastet.
    """
    grant_type = _get_record(env, XMLID_JL_SCHULUNG)
    if grant_type is None:
        _logger.info(
            "kjr_grant 19.0.10.0.0: Förderart %s nicht gefunden – "
            "übersprungen (bereits gelöscht oder nie installiert).",
            XMLID_JL_SCHULUNG,
        )
        return

    _korrigiere_betrag(grant_type, 'max_amount', JL_SCHULUNG_ALT, JL_SCHULUNG_NEU)
    _korrigiere_betrag(
        grant_type, 'jl_max_with_juleica', JL_SCHULUNG_ALT, JL_SCHULUNG_NEU,
    )


def _ziehe_beschreibungen_nach(env):
    """Geänderte ``description``-Texte in bestehende DBs nachziehen.

    Die Texte erscheinen im Portal und auf der öffentlichen Hilfeseite. Wegen
    ``noupdate="1"`` erreicht eine Änderung in der XML sonst nur Neuinstallationen.
    Überschrieben wird ausschließlich der wörtlich unveränderte Auslieferungstext –
    hat der KJR im Backend umformuliert, bleibt seine Fassung stehen.
    """
    for xmlid, alt, neu in BESCHREIBUNGEN:
        grant_type = _get_record(env, xmlid)
        if grant_type is None:
            _logger.info(
                "kjr_grant 19.0.10.0.0: Förderart %s nicht gefunden – "
                "Beschreibung übersprungen (bereits gelöscht oder nie installiert).",
                xmlid,
            )
            continue

        aktuell = (grant_type.description or '').strip()
        if aktuell == neu.strip():
            _logger.info(
                "kjr_grant 19.0.10.0.0: Förderart „%s“ (ID %s) hat bereits den neuen "
                "Beschreibungstext – keine Änderung nötig.",
                grant_type.name, grant_type.id,
            )
            continue
        if aktuell != alt.strip():
            _logger.info(
                "kjr_grant 19.0.10.0.0: Förderart „%s“ (ID %s) hat einen vom "
                "Auslieferungsstand abweichenden Beschreibungstext – übersprungen, "
                "um manuelle Pflege des KJR nicht zu überschreiben. "
                "Vorgefunden: %r",
                grant_type.name, grant_type.id, aktuell,
            )
            continue

        grant_type.write({'description': neu})
        _logger.info(
            "kjr_grant 19.0.10.0.0: Förderart „%s“ (ID %s): Beschreibungstext auf "
            "den Stand 19.0.10.0.0 aktualisiert. Neu: %r",
            grant_type.name, grant_type.id, neu,
        )


def migrate(cr, version):
    # Bei einer Neuinstallation ist ``version`` leer. Dann liefert die XML bereits
    # die korrigierten Werte aus und es gibt nichts nachzuziehen.
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})

    _deaktiviere_investitionszuschuss(env)
    _korrigiere_hoechstbetrag_jl_schulung(env)
    _ziehe_beschreibungen_nach(env)

    # Schreibvorgänge vor dem Commit des Migrationsrunners in die DB durchreichen.
    env.flush_all()
