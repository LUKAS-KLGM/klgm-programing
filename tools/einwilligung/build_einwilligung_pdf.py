#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Erzeugt das Einwilligungs-PDF und die Sign-Vorlage von ``kjr_event_sign``.

Autor: KLGM UG (haftungsbeschränkt), https://www.klgm-consulting.de

ZWECK
    Odoo Sign legt die Eingabefelder (sign.item) als Seitenanteile über ein
    statisches PDF. PDF und Feldpositionen müssen deshalb exakt zueinander
    passen. Dieses Skript erzeugt BEIDES aus EINER Koordinatentabelle
    (``FELDER``, Angaben in Millimetern auf A4):

    * ``kjr_event_sign/static/pdf/einwilligung_erziehungsberechtigte.pdf``
      (fpdf2, Kernschrift Helvetica, feste Erstellungszeit, damit jeder Lauf
      byte-gleich ist),
    * ``kjr_event_sign/data/sign_template_data.xml`` (noupdate="1": Rolle,
      Anhang, Vorlage, Dokument und die sieben Felder mit festen XML-IDs).

    Die XML-Datei wird NICHT von Hand bearbeitet. Wer das Formular ändern will,
    ändert dieses Skript und legt eine NEUE Vorlage mit eigener XML-ID an
    (z. B. ``sign_template_consent_v2``) und stellt in den Einstellungen auf die
    neue Vorlage um: noupdate="1" verhindert, dass eine geänderte Vorlage
    bestehende Installationen erreicht, und bereits versendete
    Unterschriftsanfragen verweisen auf die alte Vorlage.

INHALT DES PDF
    Neutral und ohne Firmennamen (White-Label: der Veranstalter steht im
    Anschreiben der Sign-Mail). Keine Gesundheitsfragen, kein Geburtsdatum,
    keine automatische Vorbefüllung mit Kinderdaten: den Namen des Kindes
    tragen die Eltern selbst ein.

AUFRUF
    python3 tools/einwilligung/build_einwilligung_pdf.py
        schreibt PDF und XML neu.
    python3 tools/einwilligung/build_einwilligung_pdf.py --check
        schreibt nichts und vergleicht die abgelegten Dateien mit dem, was das
        Skript heute erzeugen würde. Rückgabewert 1 bei Abweichung.

ABHÄNGIGKEIT
    fpdf2 (getestet mit 2.8.4). Eine andere fpdf2-Version kann andere Bytes
    erzeugen; ``--check`` meldet das dann als Abweichung.
"""

import argparse
import datetime
import os
import sys
from xml.sax.saxutils import escape

from fpdf import FPDF

# Verzeichnis des Repos (zwei Ebenen über tools/einwilligung/)
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODUL = "kjr_event_sign"
PDF_REL = "static/pdf/einwilligung_erziehungsberechtigte.pdf"
XML_REL = "data/sign_template_data.xml"
PDF_PFAD = os.path.join(REPO, MODUL, PDF_REL)
XML_PFAD = os.path.join(REPO, MODUL, XML_REL)

# A4 in Millimetern. Odoo Sign rechnet in Seitenanteilen mit Ursprung oben
# links: posX = x / 210, posY = y / 297 (sign.item, digits (4, 3)).
SEITE_B = 210.0
SEITE_H = 297.0

# Feste Erstellungszeit: ohne sie trüge jedes PDF die Uhrzeit des Laufs, und
# ``--check`` könnte nie "passt" melden.
ERSTELLT = datetime.datetime(2026, 10, 12, 0, 0, 0, tzinfo=datetime.timezone.utc)

TITEL = "Einwilligung der Erziehungsberechtigten zur Teilnahme an einer Veranstaltung"
VERANSTALTER = "Veranstalter: der im Anschreiben genannte Veranstalter"
EINLEITUNG = (
    "Bitte füllen Sie dieses Formular vollständig aus und unterschreiben Sie es. "
    "Tragen Sie dazu den Namen Ihres Kindes und die Veranstaltung ein, für die "
    "Sie die Einwilligung erteilen."
)
EINWILLIGUNG = (
    "Ich bin erziehungsberechtigt und willige in die Teilnahme meines Kindes an "
    "der oben genannten Veranstaltung ein. Mir ist bekannt, dass ich die "
    "Einwilligung jederzeit für die Zukunft widerrufen kann."
)
DATENSCHUTZ = (
    "Hinweis zum Datenschutz: Die Angaben in diesem Formular werden ausschließlich "
    "für die Durchführung der Veranstaltung und als Nachweis der Einwilligung "
    "verarbeitet. Weitere Informationen, insbesondere zu Ihren Rechten und zur "
    "Speicherdauer, finden Sie in den Datenschutzhinweisen des Veranstalters."
)
FUSSZEILE = "Dieses Formular wird elektronisch ausgefüllt und unterschrieben."

# ---------------------------------------------------------------------------
# DIE Koordinatentabelle. Einzige Quelle für PDF-Kästen UND sign.item.
#   xmlid     XML-ID des sign.item in kjr_event_sign
#   typ       XML-ID des sign.item.type (Modul sign)
#   name      Feldname in Odoo Sign (Platzhalter im Signierdialog)
#   text      Beschriftung im PDF (beim Ankreuzfeld: der Erklärungstext daneben)
#   x, y, b, h  Kasten in mm, Ursprung oben links
#   pflicht   sign.item.required
# ---------------------------------------------------------------------------
FELDER = (
    {"xmlid": "item_child_name", "typ": "sign.sign_item_type_text",
     "name": "Name des Kindes", "text": "Name des Kindes",
     "x": 20.0, "y": 80.0, "b": 170.0, "h": 8.0, "pflicht": True},
    {"xmlid": "item_event", "typ": "sign.sign_item_type_text",
     "name": "Veranstaltung", "text": "Veranstaltung",
     "x": 20.0, "y": 98.0, "b": 170.0, "h": 8.0, "pflicht": True},
    {"xmlid": "item_consent", "typ": "sign.sign_item_type_checkbox",
     "name": "Einwilligung", "text": EINWILLIGUNG,
     "x": 20.0, "y": 114.0, "b": 6.0, "h": 6.0, "pflicht": True},
    {"xmlid": "item_guardian_name", "typ": "sign.sign_item_type_name",
     "name": "Name", "text": "Name der erziehungsberechtigten Person",
     "x": 20.0, "y": 142.0, "b": 170.0, "h": 8.0, "pflicht": True},
    {"xmlid": "item_place", "typ": "sign.sign_item_type_text",
     "name": "Ort", "text": "Ort",
     "x": 20.0, "y": 160.0, "b": 80.0, "h": 8.0, "pflicht": True},
    {"xmlid": "item_date", "typ": "sign.sign_item_type_date",
     "name": "Datum", "text": "Datum",
     "x": 110.0, "y": 160.0, "b": 80.0, "h": 8.0, "pflicht": True},
    {"xmlid": "item_signature", "typ": "sign.sign_item_type_signature",
     "name": "Unterschrift", "text": "Unterschrift der erziehungsberechtigten Person",
     "x": 20.0, "y": 178.0, "b": 100.0, "h": 25.0, "pflicht": True},
)

ANKREUZ_TYP = "sign.sign_item_type_checkbox"


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def baue_pdf():
    """Das PDF als Bytes erzeugen (ohne zu schreiben)."""
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(False)
    pdf.set_margins(20, 20, 20)
    pdf.set_creation_date(ERSTELLT)
    pdf.set_title("Einwilligung der Erziehungsberechtigten")
    pdf.set_subject("Einwilligung zur Teilnahme an einer Veranstaltung")
    pdf.set_creator("KJR Veranstaltungen")
    pdf.set_lang("de-DE")
    pdf.add_page()

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_xy(20, 22)
    pdf.multi_cell(170, 7, TITEL, align="L")

    pdf.set_font("Helvetica", "", 10.5)
    pdf.set_xy(20, 42)
    pdf.multi_cell(170, 5.5, VERANSTALTER, align="L")
    pdf.set_xy(20, 52)
    pdf.multi_cell(170, 5.5, EINLEITUNG, align="L")

    pdf.set_draw_color(120, 120, 120)
    pdf.set_fill_color(245, 245, 245)
    pdf.set_line_width(0.3)
    for feld in FELDER:
        x, y, b, h = feld["x"], feld["y"], feld["b"], feld["h"]
        pdf.rect(x, y, b, h, style="DF")
        if feld["typ"] == ANKREUZ_TYP:
            # Erklärungstext rechts neben dem Ankreuzfeld
            pdf.set_font("Helvetica", "", 10.5)
            pdf.set_xy(x + b + 4, y - 0.5)
            pdf.multi_cell(SEITE_B - 20 - (x + b + 4), 5.5, feld["text"], align="L")
        else:
            # Beschriftung über dem Kasten
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_xy(x, y - 5.5)
            pdf.cell(b, 5, feld["text"])

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(60, 60, 60)
    pdf.set_xy(20, 222)
    pdf.multi_cell(170, 4.8, DATENSCHUTZ, align="L")

    pdf.set_font("Helvetica", "", 8)
    pdf.set_xy(20, 280)
    pdf.cell(170, 4, FUSSZEILE, align="C")
    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# XML
# ---------------------------------------------------------------------------
def _anteil(wert, bezug):
    return "%.3f" % round(wert / bezug, 3)


def baue_xml():
    """Die Datendatei der Sign-Vorlage als Text erzeugen (ohne zu schreiben)."""
    z = []
    z.append('<?xml version="1.0" encoding="utf-8"?>')
    z.append("<!--")
    z.append("    ERZEUGT von tools/einwilligung/build_einwilligung_pdf.py. NICHT VON HAND BEARBEITEN.")
    z.append("    PDF und Feldpositionen stammen aus derselben Koordinatentabelle im Skript")
    z.append("    (Millimeter auf A4, hier als Seitenanteile: posX = x/210, posY = y/297).")
    z.append("")
    z.append('    noupdate="1": Die Vorlage bleibt so, wie sie installiert wurde. Ein')
    z.append("    geändertes Formular bekommt eine NEUE XML-ID (z. B. sign_template_consent_v2)")
    z.append("    und wird in den Einstellungen als Standardvorlage gewählt; bereits")
    z.append("    versendete Anfragen verweisen weiter auf die alte Vorlage.")
    z.append("    TODO(KJR): Text des Formulars mit der Geschäftsstelle und der")
    z.append("    Datenschutzbeauftragten abstimmen.")
    z.append("-->")
    z.append("<odoo>")
    z.append('    <data noupdate="1">')
    z.append("")
    z.append('        <record id="sign_item_role_guardian" model="sign.item.role">')
    z.append("            <field name=\"name\">Erziehungsberechtigte/r</field>")
    z.append('            <field name="change_authorized" eval="True"/>')
    z.append("        </record>")
    z.append("")
    z.append('        <record id="attachment_consent_pdf" model="ir.attachment">')
    z.append("            <field name=\"name\">Einwilligung Erziehungsberechtigte.pdf</field>")
    z.append('            <field name="datas" type="base64" file="%s/%s"/>' % (MODUL, PDF_REL))
    z.append("            <field name=\"mimetype\">application/pdf</field>")
    z.append("        </record>")
    z.append("")
    z.append('        <record id="sign_template_consent" model="sign.template">')
    z.append("            <field name=\"name\">Einwilligung Erziehungsberechtigte (Standard)</field>")
    z.append('            <field name="signature_request_validity" eval="14"/>')
    z.append('            <field name="user_id" ref="base.user_admin"/>')
    z.append("        </record>")
    z.append("")
    z.append('        <record id="document_consent" model="sign.document">')
    z.append('            <field name="attachment_id" ref="attachment_consent_pdf"/>')
    z.append('            <field name="template_id" ref="sign_template_consent"/>')
    z.append('            <field name="sequence" eval="1"/>')
    z.append("        </record>")
    for feld in FELDER:
        z.append("")
        z.append("        <!-- %s: x %.1f mm, y %.1f mm, %.1f x %.1f mm -->"
                 % (escape(feld["name"]), feld["x"], feld["y"], feld["b"], feld["h"]))
        z.append('        <record id="%s" model="sign.item">' % feld["xmlid"])
        z.append('            <field name="document_id" ref="document_consent"/>')
        z.append('            <field name="type_id" ref="%s"/>' % feld["typ"])
        z.append('            <field name="responsible_id" ref="sign_item_role_guardian"/>')
        z.append('            <field name="required" eval="%s"/>' % ("True" if feld["pflicht"] else "False"))
        z.append("            <field name=\"name\">%s</field>" % escape(feld["name"]))
        z.append('            <field name="page" eval="1"/>')
        z.append('            <field name="posX" eval="%s"/>' % _anteil(feld["x"], SEITE_B))
        z.append('            <field name="posY" eval="%s"/>' % _anteil(feld["y"], SEITE_H))
        z.append('            <field name="width" eval="%s"/>' % _anteil(feld["b"], SEITE_B))
        z.append('            <field name="height" eval="%s"/>' % _anteil(feld["h"], SEITE_H))
        z.append("        </record>")
    z.append("")
    z.append("    </data>")
    z.append("</odoo>")
    return ("\n".join(z) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Prüfung und Aufruf
# ---------------------------------------------------------------------------
def pruefe_tabelle():
    """Plausibilität der Koordinatentabelle (innerhalb der Seite, eindeutige IDs)."""
    fehler = []
    ids = set()
    for feld in FELDER:
        if feld["xmlid"] in ids:
            fehler.append("doppelte XML-ID %s" % feld["xmlid"])
        ids.add(feld["xmlid"])
        if not (0 <= feld["x"] and feld["x"] + feld["b"] <= SEITE_B
                and 0 <= feld["y"] and feld["y"] + feld["h"] <= SEITE_H):
            fehler.append("%s liegt nicht vollständig auf der Seite" % feld["xmlid"])
        for schluessel in ("text", "name"):
            try:
                feld[schluessel].encode("latin-1")
            except UnicodeEncodeError:
                fehler.append("%s: %s nicht latin-1 (Kernschrift)" % (feld["xmlid"], schluessel))
    if len(FELDER) != 7:
        fehler.append("erwartet 7 Felder, gefunden %d" % len(FELDER))
    if not any(f["typ"] == "sign.sign_item_type_signature" for f in FELDER):
        fehler.append("kein Unterschriftsfeld")
    return fehler


def _vergleiche(pfad, soll):
    if not os.path.exists(pfad):
        return "%s fehlt" % os.path.relpath(pfad, REPO)
    with open(pfad, "rb") as datei:
        ist = datei.read()
    if ist != soll:
        return "%s weicht vom Skript ab, bitte ohne --check laufen lassen" % os.path.relpath(pfad, REPO)
    return None


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Einwilligungs-PDF und Sign-Vorlage für kjr_event_sign erzeugen.")
    p.add_argument("--check", action="store_true",
                   help="nichts schreiben, nur die abgelegten Dateien vergleichen")
    args = p.parse_args(argv)

    fehler = pruefe_tabelle()
    pdf = baue_pdf()
    xml = baue_xml()
    if not args.check and not fehler:
        for pfad, inhalt in ((PDF_PFAD, pdf), (XML_PFAD, xml)):
            os.makedirs(os.path.dirname(pfad), exist_ok=True)
            with open(pfad, "wb") as datei:
                datei.write(inhalt)
            print("geschrieben: %s (%d Bytes)" % (os.path.relpath(pfad, REPO), len(inhalt)))
    for pfad, soll in ((PDF_PFAD, pdf), (XML_PFAD, xml)):
        meldung = _vergleiche(pfad, soll)
        if meldung:
            fehler.append(meldung)
        else:
            print("passt: %s" % os.path.relpath(pfad, REPO))
    for zeile in fehler:
        print("FEHLER: %s" % zeile)
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
