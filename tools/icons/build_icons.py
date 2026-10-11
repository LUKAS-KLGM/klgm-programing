#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generator fuer die Modul-Icons der sechs KJR-Module.

ZWECK
    Jedes Odoo-Modul zeigt in der Apps-Uebersicht die Datei
    ``<modul>/static/description/icon.png`` (fest verdrahtet in
    ``odoo/modules/module.py``, ``get_module_icon``: ohne Manifest-Key ``icon``
    sucht Odoo genau diesen Pfad). Diese Datei ist das Erste, was ein Kunde von
    den Modulen sieht. Dieses Skript zeichnet die sechs Icons aus Code, damit sie
    als Familie zusammenpassen und jederzeit identisch reproduzierbar sind:
    gleicher Aufbau, gleiche Farben, gleiche Kantenlaenge, je Modul ein eigenes
    Motiv.

EINZIGE ICON-QUELLE
    Dieses Skript ist die einzige Quelle der sechs Icons. Es darf daneben KEINE
    zweite Icon-Quelle geben, also auch keine gepflegte ``icon.svg`` neben dem
    PNG: zwei Quellen laufen auseinander, und der naechste Bearbeiter pflegt
    verlaesslich die falsche. Die drei fruehen ``static/description/icon.svg``
    (kjr_grant, kjr_event, kjr_facility) sind aus genau diesem Grund entfallen;
    Odoo hat sie ohne Manifest-Key ``icon`` ohnehin nie herangezogen.
    Wer ein Icon aendern will, aendert dieses Skript, laesst es laufen und legt
    Skript und PNGs gemeinsam ab. Die PNGs nicht von Hand bearbeiten: der
    naechste Lauf ueberschreibt das wieder, und ``--check`` meldet es vorher.

HINWEIS ZUM VERSIONIEREN
    Die sechs PNG-Dateien sind das Ergebnis dieses Skripts und werden trotzdem
    mitversioniert, weil Odoo sie zur Laufzeit braucht und beim Build niemand
    Pillow aufruft.
    Zusaetzlich gilt: Der App-Menue-Icon der Module mit eigenem Wurzelmenue
    (kjr_grant, kjr_facility, kjr_rental, kjr_kommja) steckt im GESPEICHERTEN
    Feld ``ir.ui.menu.web_icon_data``. Odoo liest es nur in ``create()`` und
    ``write()`` neu aus der Datei (``odoo/addons/base/models/ir_ui_menu.py``).
    Ein neues PNG allein erreicht die App-Leiste einer Bestandsinstanz deshalb
    NICHT: dazu muss das Modul aktualisiert werden, also die Manifestversion
    angehoben sein. In der Apps-Liste (``ir.module.module.icon_image``, nicht
    gespeichert) erscheint das neue Bild dagegen sofort. Ohne Versionsanhebung
    entsteht also ein Mischzustand aus altem und neuem Icon. Wer hier ein Icon
    aendert, hebt die Version der betroffenen Module mit an.

AUFRUF
    python3 tools/icons/build_icons.py
        Schreibt die sechs PNGs an ihren Platz und prueft sie anschliessend.
    python3 tools/icons/build_icons.py --preview /pfad/zum/ordner
        Schreibt zusaetzlich je Icon eine 32x32-Kontrolldatei in den Ordner.
        Damit laesst sich pruefen, ob das Motiv auch klein noch erkennbar ist.
        Der Ordner liegt bewusst ausserhalb des Repos, die Kontrolldateien
        gehoeren nicht in die Versionierung.
    python3 tools/icons/build_icons.py --check
        Prueft nur und schreibt keine Modul-PNGs. ``--preview`` laesst sich damit
        kombinieren: dann entstehen die Kontrolldateien, ohne dass die sechs
        Dateien im Repo angefasst werden.

    Geprueft wird dabei: Vorhandensein, Modus RGBA, Kantenlaenge, paarweise
    Verschiedenheit, die Kontrastwerte der Palette UND dass jede abgelegte Datei
    noch pixelgleich zu dem ist, was dieses Skript heute zeichnet. Der letzte
    Punkt ist der eigentliche Zweck von ``--check``: er findet die Drift zwischen
    Skript und mitversioniertem Artefakt, also eine vergessene Neuerzeugung oder
    eine Handbearbeitung am PNG.

TECHNIK
    Gezeichnet wird mit Pillow auf einer vierfach vergroesserten Flaeche
    (1024x1024) und erst zum Schluss mit ``Image.LANCZOS`` auf 256x256
    verkleinert. Das ergibt weiche Kanten ohne Treppchen, ohne dass irgendwo von
    Hand geglaettet werden muss. Alle Koordinaten sind Anteile der Kantenlaenge
    (0.0 bis 1.0), damit die Zeichenflaeche jederzeit vergroessert werden kann.
    Keine Schriftart, kein Text, kein externes Bild: das Skript laeuft mit
    Pillow allein.

FARBEN
    Grund    #1B3A6B   Navy
    Motiv    #FFFFFF   Weiss
    Akzent   #E8952E   Orange

    Diese drei Werte sind nicht frei gewaehlt, sondern die Toene, die die Module
    dem Kunden heute schon im Frontend zeigen: ``kjr_facility/static/src/css/
    facility.css`` faerbt Kartentitel und Primaerknopf mit #1B3A6B und den Hover
    mit #E8952E, ``kjr_rental/static/src/css/rental.css`` nutzt #1B3A6B als
    Rueckfallwert hinter ``--bs-primary``, ``kjr_rental/static/src/img/
    verleih.svg`` zeichnet in #E8952E, und die Slogan-Zeile aller sechs
    ``index.html`` steht in #1a4f8a. Das Icon neben einer navyblauen Portalseite
    muss dieselbe Farbe tragen, sonst behaupten zwei Dateien gleichzeitig, die
    Marke zu sein.
    KEIN Absolutheitsanspruch: ein anderer Betreiber tauscht die drei Konstanten
    und laesst das Skript neu laufen. Ein PNG kann die Theme-Farbe der Instanz
    nicht lesen, anders als das CSS; eine feste Farbe ist hier unvermeidlich.
    Offen geblieben ist die Palette der vier Portalsymbole unter
    ``static/src/img/`` (#45B49F, #6599CD, #f2a900) - die gehoeren nicht zu
    diesem Werkzeug und sind eigenes Arbeitspaket.

GESTALTUNGSREGELN (fuer alle sechs gleich, damit sie als Familie lesbar sind)
    - Abgerundetes Quadrat als Flaeche, bei allen sechs in der Grundfarbe.
      Keine Farbvariation zwischen den Modulen: unterschieden werden die Icons
      allein durch das Motiv.
    - Darauf ein einziges, kraeftiges Motiv in Weiss. Nebenformen werden als
      Ausschnitt in der Grundfarbe gezeichnet, nicht in einem dritten hellen Ton.
    - Hoechstens EIN Akzent in Orange je Icon.
    - Rand von etwa zehn Prozent, dicke Striche, keine Haarlinien.
    - Keine Verlaeufe, keine Schlagschatten, kein Text, kein Logo.
    - Harte Pruefung: das Motiv muss auf 32 Pixel noch als Gegenstand erkennbar
      sein. Dafuer traegt die Silhouette, nicht das Detail.

KONTRAST (WCAG-Verhaeltnisse, von ``pruefen()`` nachgerechnet)
    Weiss auf Navy    11,3:1   traegt die Form
    Orange auf Navy    4,7:1   ueber den 3:1 fuer bedeutungstragende Grafik
    Orange auf Weiss   2,4:1   zu wenig

    Daraus die Regel: Orange liegt entweder auf der Grundfarbe oder wird von ihr
    umschlossen. Wo Orange an Weiss grenzen muesste, liegt dazwischen eine
    Trennung in der Grundfarbe von mindestens 0.03 der Kantenlaenge (bei 256
    Pixeln knapp acht Pixel). Dass diese Trennung im 32er-Format verschwimmt,
    ist bewusst in Kauf genommen: dort traegt die Silhouette in Weiss, der
    Akzent ist eine Zugabe fuer die grossen Formate.
"""

import argparse
import hashlib
import math
import os
import sys

from PIL import Image, ImageDraw

# --- Palette ----------------------------------------------------------------
GRUND = (0x1B, 0x3A, 0x6B, 0xFF)    # Navy, Flaeche aller sechs Icons
MOTIV = (0xFF, 0xFF, 0xFF, 0xFF)    # Weiss, traegt die Form
AKZENT = (0xE8, 0x95, 0x2E, 0xFF)   # Orange, hoechstens ein Detail je Icon

# Mindestkontraste, die pruefen() nachrechnet. 3:1 ist die Schwelle aus
# WCAG 1.4.11 fuer bedeutungstragende Grafikelemente.
KONTRAST_MINDEST = (
    ("Weiss auf Grund", MOTIV, GRUND, 4.5),
    ("Akzent auf Grund", AKZENT, GRUND, 3.0),
)

# --- Zeichenflaeche ---------------------------------------------------------
KANTE = 256          # Kantenlaenge der fertigen Datei
UEBERZEICHNUNG = 4   # vierfach zeichnen, dann verkleinern
S = KANTE * UEBERZEICHNUNG

PLATTE_RAND = 0.025  # schmaler freier Saum, damit die Rundung sauber ausblendet
PLATTE_RUNDUNG = 0.22

# Verzeichnis des Repos (zwei Ebenen ueber tools/icons/)
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Zeichenhilfen. Alle Masse sind Anteile der Kantenlaenge.
# ---------------------------------------------------------------------------
def rrect(d, x0, y0, x1, y1, r, fill):
    """Abgerundetes Rechteck."""
    d.rounded_rectangle([x0 * S, y0 * S, x1 * S, y1 * S], radius=r * S, fill=fill)


def rect(d, x0, y0, x1, y1, fill):
    """Rechteck mit scharfen Ecken, z. B. um eine Rundung wieder abzuschneiden."""
    d.rectangle([x0 * S, y0 * S, x1 * S, y1 * S], fill=fill)


def poly(d, punkte, fill):
    """Vieleck aus einer Liste von (x, y)-Paaren."""
    d.polygon([(x * S, y * S) for x, y in punkte], fill=fill)


def kreis(d, cx, cy, r, fill):
    """Kreis um (cx, cy)."""
    d.ellipse([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], fill=fill)


def strich(d, punkte, breite, fill):
    """Dicker Linienzug mit runden Ecken und runden Enden.

    Pillow rundet mit ``joint='curve'`` nur die Knicke, nicht die Enden. Die
    Enden setzen wir deshalb als Kreise nach, sonst stehen dort harte Stummel.
    """
    d.line([(x * S, y * S) for x, y in punkte], fill=fill, width=int(breite * S), joint="curve")
    for x, y in punkte:
        kreis(d, x, y, breite / 2.0, fill)


def halbbogen(cx, cy, r, schritte=24):
    """Punkte eines nach oben offenen Halbkreises, zum Fuettern von strich().

    Bewusst als Punktzug und nicht mit ``ImageDraw.arc``: dessen ``width``
    waechst von der Umschliessenden nach innen, die Mittellinie des Strichs
    waere also nicht r, und runde Enden liefert es nicht.
    """
    return [(cx + r * math.cos(math.radians(w)), cy - r * math.sin(math.radians(w)))
            for w in (180.0 * i / schritte for i in range(schritte + 1))]


def platte():
    """Leeres Icon: abgerundetes Quadrat in der Grundfarbe.

    Der Hintergrund ist vollstaendig durchsichtig (0, 0, 0, 0). Ein
    Grundfarbton mit Alpha 0 waere hier wirkungslos: Pillow rechnet beim
    Verkleinern mit vormultipliziertem Alpha, der Farbwert im durchsichtigen
    Bereich geht also nicht in die Mischung ein. Nachgeprueft mit Pillow 11.3.0:
    alle sechs Motive sind mit (grund, 0) und mit (0, 0, 0, 0) pixelgleich, und
    das Eckpixel der fertigen Datei ist in beiden Faellen (0, 0, 0, 0). Einen
    dunklen Saum an der Rundung gibt es damit nicht; wer einmal doch einen
    sieht, muss ihn woanders suchen.
    """
    bild = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(bild)
    rrect(d, PLATTE_RAND, PLATTE_RAND, 1 - PLATTE_RAND, 1 - PLATTE_RAND,
          PLATTE_RUNDUNG, GRUND)
    return bild, d


# ---------------------------------------------------------------------------
# Die sechs Motive. Je Modul genau ein Gegenstand, keine Collage.
# ---------------------------------------------------------------------------
def motiv_grant(d):
    """Zuschussverwaltung: Dokument mit Siegel und Haken."""
    # Blatt
    rrect(d, 0.20, 0.15, 0.665, 0.785, 0.035, MOTIV)
    # Drei Zeilen als angedeuteter Text, ausgeschnitten in der Grundfarbe:
    # 11,3:1 gegen das Blatt. In einem dritten hellen Ton waeren sie bei
    # 32 Pixeln nicht mehr von einem Schmutzfleck zu unterscheiden.
    for y in (0.265, 0.385, 0.505):
        rrect(d, 0.275, y, 0.585, y + 0.052, 0.026, GRUND)
    # Siegel: erst ein Loch in der Grundfarbe, damit der Akzent nirgends an
    # Weiss grenzt, dann die orange Scheibe, dann der Haken als Ausschnitt.
    kreis(d, 0.695, 0.695, 0.205, GRUND)
    kreis(d, 0.695, 0.695, 0.165, AKZENT)
    strich(d, [(0.620, 0.700), (0.675, 0.755), (0.775, 0.635)], 0.040, GRUND)


def motiv_event(d):
    """Ferienprogramm und Schulungen: Kalenderblatt."""
    # Zwei Aufhaenger oben, ragen ueber das Blatt hinaus
    rrect(d, 0.295, 0.125, 0.375, 0.265, 0.040, MOTIV)
    rrect(d, 0.625, 0.125, 0.705, 0.265, 0.040, MOTIV)
    # Blatt
    rrect(d, 0.145, 0.205, 0.855, 0.855, 0.060, MOTIV)
    # Kopfleiste im Akzent: Rundung oben erhalten, unten gerade abschneiden
    rrect(d, 0.145, 0.205, 0.855, 0.390, 0.060, AKZENT)
    rect(d, 0.145, 0.330, 0.855, 0.390, AKZENT)
    # Trennlinie in der Grundfarbe. Sie haelt den Akzent von der weissen
    # Blattflaeche fern (Orange auf Weiss waere nur 2,4:1) und liest sich
    # gleichzeitig als Falzkante des Kalenderblatts.
    rect(d, 0.145, 0.390, 0.855, 0.425, GRUND)
    # Tagesraster, 3 x 2 kraeftige Felder
    for sx in (0.230, 0.440, 0.650):
        for sy in (0.490, 0.665):
            rrect(d, sx, sy, sx + 0.120, sy + 0.120, 0.025, GRUND)


def motiv_facility(d):
    """Einrichtungsbuchung: Haus mit Bett."""
    # Dach
    poly(d, [(0.500, 0.125), (0.885, 0.450), (0.115, 0.450)], MOTIV)
    # Baukoerper
    rrect(d, 0.185, 0.420, 0.815, 0.855, 0.040, MOTIV)
    # Bett als Ausschnitt in der Grundfarbe: Kopfteil links, Liegeflaeche quer.
    # Dieses L traegt die Lesart "Bett" allein, auch bei 32 Pixeln.
    rrect(d, 0.250, 0.505, 0.350, 0.760, 0.028, GRUND)
    rrect(d, 0.250, 0.620, 0.745, 0.760, 0.028, GRUND)
    # Kissen: liegt vollstaendig IM Ausschnitt und stoesst an das Kopfteil, hat
    # also 4,7:1 gegen seinen Grund und keinen hellen Spalt ringsherum. Es ist
    # ein Detail fuer 64 Pixel und mehr; bei 32 Pixeln bleibt davon ein Hauch
    # von Farbe, und das ist in Ordnung, weil das L die Form schon traegt.
    rrect(d, 0.350, 0.648, 0.495, 0.732, 0.022, AKZENT)


def motiv_rental(d):
    """Materialverleih: Anhaenger mit Zugdeichsel.

    Dasselbe Motiv wie das Portalsymbol ``static/src/img/verleih.svg``
    (Kasten mit Deckelkante, Deichsel mit Kupplung, zwei Raeder), damit
    Apps-Kachel und Portalkachel dieselbe Formensprache sprechen.
    """
    # Kasten
    rrect(d, 0.280, 0.215, 0.900, 0.600, 0.050, MOTIV)
    # Deckelband im Akzent: oben mit der Kastenrundung, unten gerade
    rrect(d, 0.280, 0.215, 0.900, 0.350, 0.050, AKZENT)
    rect(d, 0.280, 0.300, 0.900, 0.350, AKZENT)
    # Fuge in der Grundfarbe. Sie haelt den Akzent von der weissen Kastenflaeche
    # fern (Orange auf Weiss waere nur 2,4:1) und liest sich als Deckelkante.
    rect(d, 0.280, 0.350, 0.900, 0.385, GRUND)
    # Deichsel mit Kupplung. Die Kupplung bleibt eine volle Scheibe: ein Loch
    # darin faellt bei 32 Pixeln zu einem Schmutzpunkt zusammen.
    strich(d, [(0.310, 0.560), (0.165, 0.660)], 0.058, MOTIV)
    kreis(d, 0.165, 0.660, 0.052, MOTIV)
    # Zwei Raeder mit Nabe, sie ragen unter dem Kasten hervor
    for cx in (0.430, 0.760):
        kreis(d, cx, 0.700, 0.098, MOTIV)
        kreis(d, cx, 0.700, 0.038, GRUND)


def motiv_facility_grant(d):
    """Bruecke zwischen Einrichtung und Zuschuss: Haus und Dokument verbunden."""
    # Verbindender Balken zuerst, damit Haus und Dokument darueber liegen und
    # ihn an ihrer Kante sauber beschneiden. Er liegt doppelt: aussen in der
    # Grundfarbe, innen im Akzent. Die aeussere Lage ist auf der Platte
    # unsichtbar (gleiche Farbe) und wird genau dort sichtbar, wo der Balken
    # unter das weisse Haus bzw. Dokument laeuft - dann als schmale Fuge, die
    # den Akzent von Weiss trennt.
    # Die Steigung ist so gewaehlt, dass die untere Flanke des Akzents an der
    # rechten Hauskante (x = 0.455) bei y = 0.507 liegt, also oberhalb der
    # geraden Unterkante des Hauses (y = 0.550 minus Rundung 0.030). Mit der
    # frueheren Lage trat dort ein Keil unter der Hausecke hervor.
    weg = [(0.390, 0.430), (0.620, 0.520)]
    strich(d, weg, 0.140, GRUND)
    strich(d, weg, 0.096, AKZENT)
    # Haus oben links, verkleinertes Motiv aus kjr_facility
    poly(d, [(0.300, 0.135), (0.500, 0.325), (0.100, 0.325)], MOTIV)
    rrect(d, 0.145, 0.305, 0.455, 0.550, 0.030, MOTIV)
    rrect(d, 0.255, 0.400, 0.345, 0.550, 0.025, GRUND)
    # Dokument unten rechts, verkleinertes Motiv aus kjr_grant
    rrect(d, 0.535, 0.460, 0.880, 0.865, 0.030, MOTIV)
    for y in (0.545, 0.650, 0.755):
        rrect(d, 0.590, y, 0.825, y + 0.050, 0.025, GRUND)


def motiv_kommja(d):
    """Verzeichnis offener Jugendeinrichtungen: Landkarten-Stecknadel.

    Das einzige Motiv ohne Akzentfarbe. Der Nadelkopf IST das Motiv; ein
    zweiter Ton darin waere entweder zu klein (Orange braucht eine Fassung in
    der Grundfarbe) oder kontrastarm (Orange auf Weiss 2,4:1). Das Loch in der
    Grundfarbe hat 11,3:1 und ist die uebliche Form einer Kartennadel.
    """
    # Tropfenform aus Kreis und Dreieck
    kreis(d, 0.500, 0.400, 0.265, MOTIV)
    poly(d, [(0.500, 0.870), (0.282, 0.552), (0.718, 0.552)], MOTIV)
    # Loch
    kreis(d, 0.500, 0.400, 0.108, GRUND)


# Reihenfolge und Zuordnung. Alle sechs tragen dieselbe Grundfarbe; die
# frueheren zwei Toene (#714B67 / #5E3F56) hatten 1,25:1 zueinander und waren
# am Icon nicht auseinanderzuhalten. Unterschieden werden die Kacheln durch das
# Motiv.
ICONS = (
    ("kjr_grant", motiv_grant),
    ("kjr_event", motiv_event),
    ("kjr_facility", motiv_facility),
    ("kjr_rental", motiv_rental),
    ("kjr_facility_grant", motiv_facility_grant),
    ("kjr_kommja", motiv_kommja),
)


def zeichne(motiv):
    """Ein Icon zeichnen und auf die Zielgroesse verkleinern."""
    bild, d = platte()
    motiv(d)
    return bild.resize((KANTE, KANTE), Image.LANCZOS)


def ziel(modul):
    return os.path.join(REPO, modul, "static", "description", "icon.png")


def vorschau_schreiben(ordner, modul, bild):
    """Je Icon eine 32er-Kontrolldatei und eine vergroesserte Lupenfassung."""
    os.makedirs(ordner, exist_ok=True)
    klein = bild.resize((32, 32), Image.LANCZOS)
    klein.save(os.path.join(ordner, "%s_32.png" % modul), "PNG")
    # zusaetzlich stark vergroessert, damit das 32er-Ergebnis am Bildschirm
    # ohne Lupe beurteilt werden kann
    klein.resize((256, 256), Image.NEAREST).save(
        os.path.join(ordner, "%s_32_lupe.png" % modul), "PNG")


def bauen(schreiben=True, vorschau=None):
    """Die sechs Icons zeichnen. Gibt die Liste der geschriebenen Pfade zurueck.

    ``schreiben=False`` laesst die Dateien im Repo unangetastet. Die Vorschau
    haengt bewusst nicht am Schreiben: ``--check --preview`` soll die
    Sichtpruefung wiederholen koennen, ohne die sechs Repo-Dateien anzufassen.
    """
    pfade = []
    for modul, motiv in ICONS:
        bild = zeichne(motiv)
        if schreiben:
            pfad = ziel(modul)
            os.makedirs(os.path.dirname(pfad), exist_ok=True)
            bild.save(pfad, "PNG", optimize=True)
            pfade.append(pfad)
        if vorschau:
            vorschau_schreiben(vorschau, modul, bild)
    return pfade


# ---------------------------------------------------------------------------
# Pruefung
# ---------------------------------------------------------------------------
def _helligkeit(farbe):
    """Relative Leuchtdichte nach WCAG 2.1 (Alpha bleibt unberuecksichtigt)."""
    werte = []
    for anteil in farbe[:3]:
        c = anteil / 255.0
        werte.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * werte[0] + 0.7152 * werte[1] + 0.0722 * werte[2]


def kontrast(a, b):
    """Kontrastverhaeltnis zweier Farben nach WCAG 2.1."""
    la, lb = _helligkeit(a), _helligkeit(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def pruefen():
    """Die sechs Dateien gegen Skript und Palette pruefen.

    Geprueft wird in dieser Reihenfolge:
    1. die Kontrastwerte der Palette gegen KONTRAST_MINDEST,
    2. Vorhandensein, Modus RGBA und Kantenlaenge je Datei,
    3. paarweise Verschiedenheit der sechs Dateien,
    4. ob jede Datei noch pixelgleich zu dem ist, was dieses Skript zeichnet.

    Punkt 4 ist der Grund, warum es diese Funktion gibt. Format, Groesse und
    Eindeutigkeit allein wuerden eine vergessene Neuerzeugung oder eine
    Handbearbeitung am PNG stillschweigend durchlassen.
    """
    fehler = []

    for name, vorn, hinten, mindestens in KONTRAST_MINDEST:
        wert = kontrast(vorn, hinten)
        print("%-18s %5.2f:1  (mindestens %.1f:1)" % (name, wert, mindestens))
        if wert < mindestens:
            fehler.append("Palette: %s nur %.2f:1, gefordert %.1f:1"
                          % (name, wert, mindestens))
    print()

    hashes = {}
    print("%-20s %7s  %-6s %-9s %-16s %s"
          % ("Modul", "Bytes", "Format", "Groesse", "Pixel-Hash", "Skript"))
    for modul, motiv in ICONS:
        pfad = ziel(modul)
        if not os.path.exists(pfad):
            fehler.append("%s: Datei fehlt" % modul)
            continue
        groesse = os.path.getsize(pfad)
        with Image.open(pfad) as bild:
            modus, (b, h) = bild.mode, bild.size
            digest = hashlib.sha256(bild.tobytes()).hexdigest()
        # Frisch nachzeichnen und vergleichen: Drift zwischen Skript und
        # abgelegtem Artefakt ist der Fehler, den diese Pruefung finden soll.
        soll = hashlib.sha256(zeichne(motiv).tobytes()).hexdigest()
        print("%-20s %7d  %-6s %4dx%-4d %-16s %s"
              % (modul, groesse, modus, b, h, digest[:16],
                 "passt" if soll == digest else "ABWEICHUNG"))
        if modus != "RGBA":
            fehler.append("%s: Modus %s, erwartet RGBA" % (modul, modus))
        if (b, h) != (KANTE, KANTE):
            fehler.append("%s: %dx%d, erwartet %dx%d" % (modul, b, h, KANTE, KANTE))
        if digest in hashes:
            fehler.append("%s: pixelgleich mit %s" % (modul, hashes[digest]))
        if soll != digest:
            fehler.append("%s: Datei passt nicht zum Skript, bitte ohne --check "
                          "laufen lassen (Skript %s..., Datei %s...)"
                          % (modul, soll[:16], digest[:16]))
        hashes[digest] = modul
    print("\n%d von %d Dateien paarweise verschieden." % (len(hashes), len(ICONS)))
    for zeile in fehler:
        print("FEHLER: %s" % zeile)
    return not fehler


def main(argv=None):
    p = argparse.ArgumentParser(description="Modul-Icons der sechs KJR-Module erzeugen.")
    p.add_argument("--preview", metavar="ORDNER",
                   help="zusaetzlich 32x32-Kontrolldateien in diesen Ordner schreiben; "
                        "mit --check kombinierbar")
    p.add_argument("--check", action="store_true",
                   help="die vorhandenen Dateien pruefen, keine Modul-PNGs schreiben")
    args = p.parse_args(argv)
    pfade = bauen(schreiben=not args.check, vorschau=args.preview)
    for pfad in pfade:
        print("geschrieben: %s" % pfad)
    if args.preview:
        print("Kontrolldateien: %s" % args.preview)
    if pfade or args.preview:
        print()
    return 0 if pruefen() else 1


if __name__ == "__main__":
    sys.exit(main())
