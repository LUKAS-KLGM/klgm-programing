#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Erzeugt die Einwilligungs-PDFs und Sign-Vorlagen von ``kjr_event_sign``.

Autor: KLGM UG (haftungsbeschränkt), https://www.klgm-consulting.de

ZWECK
    Odoo Sign legt die Eingabefelder (sign.item) als Seitenanteile über ein
    statisches PDF. PDF und Feldpositionen müssen deshalb exakt zueinander
    passen. Dieses Skript erzeugt BEIDES aus EINER Koordinatentabelle je
    Vorlage (``FELDER`` bzw. ``FELDER_V2``, Angaben in Millimetern auf A4).

    Zwei Vorlagen (``VARIANTEN``):

    v1  ``sign_template_consent`` (19.0.1.0.0, auf der Produktion installiert,
        NICHT mehr ändern): die Eltern tragen Kind, Veranstaltung und ihren
        Namen selbst ein.
        * ``kjr_event_sign/static/pdf/einwilligung_erziehungsberechtigte.pdf``
        * ``kjr_event_sign/data/sign_template_data.xml`` (mit der Rolle
          ``sign_item_role_guardian``)
    v2  ``sign_template_consent_v2`` (19.0.1.1.0, Standard): Name des Kindes,
        Veranstaltung (Name und Zeitraum) und Name der/des
        Erziehungsberechtigten kommen schreibgeschützt aus der Anmeldung
        (sign.item ``constant``; Feldtypen ``sign_item_type_kjr_*`` in
        ``data/sign_item_type_data.xml``). Die Eltern setzen nur Haken, Ort und
        Unterschrift, das Datum füllt Odoo Sign.
        * ``kjr_event_sign/static/pdf/einwilligung_erziehungsberechtigte_v2.pdf``
        * ``kjr_event_sign/data/sign_template_consent_v2_data.xml`` (nutzt die
          Rolle aus v1)

    PDFs: fpdf2, Kernschrift Helvetica, feste Erstellungszeit, damit jeder Lauf
    byte-gleich ist. Die XML-Dateien werden NICHT von Hand bearbeitet.

    Wer das Formular ändern will, ändert dieses Skript und legt eine NEUE
    Vorlage mit eigener XML-ID an (z. B. ``sign_template_consent_v3``) und
    stellt die Standardvorlage um: noupdate="1" verhindert, dass eine
    geänderte Vorlage bestehende Installationen erreicht, und bereits
    versendete Unterschriftsanfragen verweisen auf die alte Vorlage. Die
    Bausteine von v1 bleiben deshalb unverändert im Skript, ``--check`` prüft
    weiter, dass v1 byte-gleich reproduziert wird.

INHALT DER PDFs
    Neutral und ohne Firmennamen (White-Label: der Veranstalter steht im
    Anschreiben der Sign-Mail). Keine Gesundheitsfragen, kein Geburtsdatum.

AUFRUF
    python3 tools/einwilligung/build_einwilligung_pdf.py
        schreibt PDFs und XML-Dateien beider Vorlagen neu.
    python3 tools/einwilligung/build_einwilligung_pdf.py --check
        schreibt nichts und vergleicht die abgelegten Dateien beider Vorlagen
        mit dem, was das Skript heute erzeugen würde. Rückgabewert 1 bei
        Abweichung.

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

# A4 in Millimetern. Odoo Sign rechnet in Seitenanteilen mit Ursprung oben
# links: posX = x / 210, posY = y / 297 (sign.item, digits (4, 3)).
SEITE_B = 210.0
SEITE_H = 297.0

# Feste Erstellungszeit: ohne sie trüge jedes PDF die Uhrzeit des Laufs, und
# ``--check`` könnte nie "passt" melden.
ERSTELLT = datetime.datetime(2026, 10, 12, 0, 0, 0, tzinfo=datetime.timezone.utc)

TITEL = "Einwilligung der Erziehungsberechtigten zur Teilnahme an einer Veranstaltung"
VERANSTALTER = "Veranstalter: der im Anschreiben genannte Veranstalter"
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

ANKREUZ_TYP = "sign.sign_item_type_checkbox"
UNTERSCHRIFT_TYP = "sign.sign_item_type_signature"
# Feldtypen, die Odoo Sign nicht schreibgeschützt (constant) zulässt
# (sign.item._check_constant, Odoo 19).
NICHT_KONSTANT_TYPEN = (
    "sign.sign_item_type_signature", "sign.sign_item_type_initial",
    "sign.sign_item_type_selection", "sign.sign_item_type_checkbox",
    "sign.sign_item_type_radio",
)

# ===========================================================================
# v1: sign_template_consent (19.0.1.0.0). AUF DER PRODUKTION INSTALLIERT.
# Texte, Tabelle und XML-Aufbau NICHT ändern: ``--check`` muss die abgelegten
# Dateien weiter byte-gleich reproduzieren.
# ===========================================================================
EINLEITUNG = (
    "Bitte füllen Sie dieses Formular vollständig aus und unterschreiben Sie es. "
    "Tragen Sie dazu den Namen Ihres Kindes und die Veranstaltung ein, für die "
    "Sie die Einwilligung erteilen."
)

# ---------------------------------------------------------------------------
# Koordinatentabelle v1. Einzige Quelle für PDF-Kästen UND sign.item.
#   xmlid     XML-ID des sign.item in kjr_event_sign
#   typ       XML-ID des sign.item.type
#   name      Feldname in Odoo Sign (Platzhalter im Signierdialog)
#   text      Beschriftung im PDF (beim Ankreuzfeld: der Erklärungstext daneben)
#   x, y, b, h  Kasten in mm, Ursprung oben links
#   pflicht   sign.item.required
#   konstant  (nur v2) sign.item.constant: Wert kommt aus der Anmeldung und
#             ist für die Eltern schreibgeschützt
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

# ===========================================================================
# v2: sign_template_consent_v2 (19.0.1.1.0). Vorbefüllt aus der Anmeldung.
# ===========================================================================
# Die Einleitung braucht vier Zeilen (v1: zwei); alle Kästen liegen deshalb
# 6 mm tiefer als in v1, damit die erste Beschriftung frei steht.
EINLEITUNG_V2 = (
    "Die Angaben zu Ihrem Kind, zur Veranstaltung und Ihr Name sind aus der "
    "Anmeldung übernommen. Bitte prüfen Sie sie, bestätigen Sie die Einwilligung mit dem "
    "Häkchen, tragen Sie den Ort ein und unterschreiben Sie. Stimmen die Angaben "
    "nicht, unterschreiben Sie bitte nicht und wenden Sie sich an den im "
    "Anschreiben genannten Veranstalter."
)
# Typen aus kjr_event_sign/data/sign_item_type_data.xml (auto_field auf
# event.registration; Odoo Sign liest sie über reference_doc der Anfrage).
TYP_KIND = "sign_item_type_kjr_child_name"
TYP_VERANSTALTUNG = "sign_item_type_kjr_event_label"
TYP_ERZIEHUNGSBERECHTIGTE = "sign_item_type_kjr_guardian_name"
AUTO_TYPEN = (TYP_KIND, TYP_VERANSTALTUNG, TYP_ERZIEHUNGSBERECHTIGTE)

FELDER_V2 = (
    {"xmlid": "item_v2_child_name", "typ": TYP_KIND,
     "name": "Name des Kindes / Teilnehmer/in", "text": "Name des Kindes / Teilnehmer/in",
     "x": 20.0, "y": 86.0, "b": 170.0, "h": 8.0, "pflicht": False, "konstant": True},
    {"xmlid": "item_v2_event", "typ": TYP_VERANSTALTUNG,
     "name": "Veranstaltung", "text": "Veranstaltung",
     "x": 20.0, "y": 104.0, "b": 170.0, "h": 8.0, "pflicht": False, "konstant": True},
    {"xmlid": "item_v2_consent", "typ": "sign.sign_item_type_checkbox",
     "name": "Einwilligung", "text": EINWILLIGUNG,
     "x": 20.0, "y": 120.0, "b": 6.0, "h": 6.0, "pflicht": True},
    {"xmlid": "item_v2_guardian_name", "typ": TYP_ERZIEHUNGSBERECHTIGTE,
     "name": "Name der/des Erziehungsberechtigten",
     "text": "Name der/des Erziehungsberechtigten",
     "x": 20.0, "y": 148.0, "b": 170.0, "h": 8.0, "pflicht": False, "konstant": True},
    {"xmlid": "item_v2_place", "typ": "sign.sign_item_type_text",
     "name": "Ort", "text": "Ort",
     "x": 20.0, "y": 166.0, "b": 80.0, "h": 8.0, "pflicht": True},
    {"xmlid": "item_v2_date", "typ": "sign.sign_item_type_date",
     "name": "Datum", "text": "Datum",
     "x": 110.0, "y": 166.0, "b": 80.0, "h": 8.0, "pflicht": True},
    {"xmlid": "item_v2_signature", "typ": "sign.sign_item_type_signature",
     "name": "Unterschrift",
     "text": "Unterschrift der/des Erziehungsberechtigten",
     "x": 20.0, "y": 184.0, "b": 100.0, "h": 25.0, "pflicht": True},
)

# ---------------------------------------------------------------------------
# Beide Vorlagen. Alle Werte, die zwischen v1 und v2 abweichen, stehen hier.
# ---------------------------------------------------------------------------
V1 = {
    "kennung": "v1",
    "pdf_rel": "static/pdf/einwilligung_erziehungsberechtigte.pdf",
    "xml_rel": "data/sign_template_data.xml",
    "einleitung": EINLEITUNG,
    "felder": FELDER,
    "rolle_anlegen": True,
    "anhang_id": "attachment_consent_pdf",
    "anhang_name": "Einwilligung Erziehungsberechtigte.pdf",
    "vorlage_id": "sign_template_consent",
    "vorlage_name": "Einwilligung Erziehungsberechtigte (Standard)",
    "vorlage_modell": None,
    "dokument_id": "document_consent",
}
V2 = {
    "kennung": "v2",
    "pdf_rel": "static/pdf/einwilligung_erziehungsberechtigte_v2.pdf",
    "xml_rel": "data/sign_template_consent_v2_data.xml",
    "einleitung": EINLEITUNG_V2,
    "felder": FELDER_V2,
    "rolle_anlegen": False,
    "anhang_id": "attachment_consent_pdf_v2",
    "anhang_name": "Einwilligung Erziehungsberechtigte (vorausgefüllt).pdf",
    "vorlage_id": "sign_template_consent_v2",
    # Bewusst ohne "Standard": welche Vorlage Standard ist, legen die
    # Einstellungen fest. v1 heißt nach der Umstellung "… (alt, ohne
    # Vorbefüllung)" (event.event._kjr_sign_rename_template_v1); ihr Name in
    # sign_template_data.xml bleibt, damit v1 byte-gleich erzeugt wird.
    "vorlage_name": "Einwilligung Erziehungsberechtigte (vorausgefüllt)",
    # Vorlage an Anmeldungen gebunden: Odoo Sign bietet sie dann nur aus einer
    # Anmeldung heraus an (Senden-Assistent) und zeigt im Editor die
    # passenden Feldtypen. sign.template._constraint_model_items verlangt,
    # dass alle modellgebundenen Feldtypen zu diesem Modell passen.
    "vorlage_modell": "event.model_event_registration",
    "dokument_id": "document_consent_v2",
}
VARIANTEN = (V1, V2)


def _pfad(variante, schluessel):
    return os.path.join(REPO, MODUL, variante[schluessel])


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def baue_pdf(variante=V1):
    """Das PDF einer Vorlage als Bytes erzeugen (ohne zu schreiben)."""
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
    pdf.multi_cell(170, 5.5, variante["einleitung"], align="L")

    pdf.set_draw_color(120, 120, 120)
    pdf.set_fill_color(245, 245, 245)
    pdf.set_line_width(0.3)
    for feld in variante["felder"]:
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


def _kopf_v1(z):
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


def _kopf_v2(z):
    z.append("<!--")
    z.append("    ERZEUGT von tools/einwilligung/build_einwilligung_pdf.py. NICHT VON HAND BEARBEITEN.")
    z.append("    PDF und Feldpositionen stammen aus derselben Koordinatentabelle im Skript")
    z.append("    (Millimeter auf A4, hier als Seitenanteile: posX = x/210, posY = y/297).")
    z.append("")
    z.append("    Vorlage v2 (19.0.1.1.0): Name des Kindes, Veranstaltung (Name und Zeitraum)")
    z.append("    und Name der/des Erziehungsberechtigten sind schreibgeschützt (constant) und")
    z.append("    werden beim Anlegen der Unterschriftsanfrage aus der Anmeldung gefüllt")
    z.append("    (sign.request._populate_constant_items -> auto_field der Feldtypen aus")
    z.append("    data/sign_item_type_data.xml, gelesen über reference_doc der Anfrage).")
    z.append("    Die Rolle sign_item_role_guardian stammt aus sign_template_data.xml (v1).")
    z.append("")
    z.append('    noupdate="1": Die Vorlage bleibt so, wie sie installiert wurde. Ein')
    z.append("    geändertes Formular bekommt eine NEUE XML-ID (z. B. sign_template_consent_v3);")
    z.append("    bereits versendete Anfragen verweisen weiter auf ihre Vorlage.")
    z.append("    TODO(KJR): Text des Formulars mit der Geschäftsstelle und der")
    z.append("    Datenschutzbeauftragten abstimmen.")
    z.append("-->")


def baue_xml(variante=V1):
    """Die Datendatei einer Sign-Vorlage als Text erzeugen (ohne zu schreiben)."""
    z = []
    z.append('<?xml version="1.0" encoding="utf-8"?>')
    if variante["kennung"] == "v1":
        _kopf_v1(z)
    else:
        _kopf_v2(z)
    z.append("<odoo>")
    z.append('    <data noupdate="1">')
    z.append("")
    if variante["rolle_anlegen"]:
        z.append('        <record id="sign_item_role_guardian" model="sign.item.role">')
        z.append("            <field name=\"name\">Erziehungsberechtigte/r</field>")
        z.append('            <field name="change_authorized" eval="True"/>')
        z.append("        </record>")
        z.append("")
    z.append('        <record id="%s" model="ir.attachment">' % variante["anhang_id"])
    z.append("            <field name=\"name\">%s</field>" % escape(variante["anhang_name"]))
    z.append('            <field name="datas" type="base64" file="%s/%s"/>' % (MODUL, variante["pdf_rel"]))
    z.append("            <field name=\"mimetype\">application/pdf</field>")
    z.append("        </record>")
    z.append("")
    z.append('        <record id="%s" model="sign.template">' % variante["vorlage_id"])
    z.append("            <field name=\"name\">%s</field>" % escape(variante["vorlage_name"]))
    z.append('            <field name="signature_request_validity" eval="14"/>')
    z.append('            <field name="user_id" ref="base.user_admin"/>')
    if variante["vorlage_modell"]:
        z.append('            <field name="model_id" ref="%s"/>' % variante["vorlage_modell"])
    z.append("        </record>")
    z.append("")
    z.append('        <record id="%s" model="sign.document">' % variante["dokument_id"])
    z.append('            <field name="attachment_id" ref="%s"/>' % variante["anhang_id"])
    z.append('            <field name="template_id" ref="%s"/>' % variante["vorlage_id"])
    z.append('            <field name="sequence" eval="1"/>')
    z.append("        </record>")
    for feld in variante["felder"]:
        z.append("")
        z.append("        <!-- %s: x %.1f mm, y %.1f mm, %.1f x %.1f mm -->"
                 % (escape(feld["name"]), feld["x"], feld["y"], feld["b"], feld["h"]))
        z.append('        <record id="%s" model="sign.item">' % feld["xmlid"])
        z.append('            <field name="document_id" ref="%s"/>' % variante["dokument_id"])
        z.append('            <field name="type_id" ref="%s"/>' % feld["typ"])
        z.append('            <field name="responsible_id" ref="sign_item_role_guardian"/>')
        z.append('            <field name="required" eval="%s"/>' % ("True" if feld["pflicht"] else "False"))
        if feld.get("konstant"):
            z.append('            <field name="constant" eval="True"/>')
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
def pruefe_tabelle(variante=V1):
    """Plausibilität einer Koordinatentabelle (innerhalb der Seite, eindeutige
    IDs, latin-1, Unterschriftsfeld, Regeln für schreibgeschützte Felder)."""
    fehler = []
    ids = set()
    felder = variante["felder"]
    kennung = variante["kennung"]
    for feld in felder:
        if feld["xmlid"] in ids:
            fehler.append("%s: doppelte XML-ID %s" % (kennung, feld["xmlid"]))
        ids.add(feld["xmlid"])
        if not (0 <= feld["x"] and feld["x"] + feld["b"] <= SEITE_B
                and 0 <= feld["y"] and feld["y"] + feld["h"] <= SEITE_H):
            fehler.append("%s: %s liegt nicht vollständig auf der Seite" % (kennung, feld["xmlid"]))
        for schluessel in ("text", "name"):
            try:
                feld[schluessel].encode("latin-1")
            except UnicodeEncodeError:
                fehler.append("%s: %s: %s nicht latin-1 (Kernschrift)"
                              % (kennung, feld["xmlid"], schluessel))
        if feld.get("konstant"):
            # sign.item._check_constant lehnt diese Typen ab; ein
            # schreibgeschütztes Pflichtfeld könnten die Eltern nie füllen.
            if feld["typ"] in NICHT_KONSTANT_TYPEN:
                fehler.append("%s: %s: Typ %s darf nicht schreibgeschützt sein"
                              % (kennung, feld["xmlid"], feld["typ"]))
            if feld["pflicht"]:
                fehler.append("%s: %s: schreibgeschütztes Feld darf kein Pflichtfeld sein"
                              % (kennung, feld["xmlid"]))
    try:
        variante["einleitung"].encode("latin-1")
    except UnicodeEncodeError:
        fehler.append("%s: Einleitung nicht latin-1 (Kernschrift)" % kennung)
    else:
        # Die Einleitung (ab y=52, Zeilenhöhe 5,5 mm, wie in baue_pdf) darf
        # nicht in die Beschriftung des obersten Feldes laufen.
        messung = FPDF(orientation="P", unit="mm", format="A4")
        messung.add_page()
        messung.set_font("Helvetica", "", 10.5)
        zeilen = len(messung.multi_cell(170, 5.5, variante["einleitung"],
                                        dry_run=True, output="LINES"))
        oben = min(f["y"] for f in felder) - 5.5
        if 52 + zeilen * 5.5 > oben:
            fehler.append("%s: Einleitung (%d Zeilen) überdeckt das oberste Feld"
                          % (kennung, zeilen))
    if len(felder) != 7:
        fehler.append("%s: erwartet 7 Felder, gefunden %d" % (kennung, len(felder)))
    if not any(f["typ"] == UNTERSCHRIFT_TYP and f["pflicht"] for f in felder):
        fehler.append("%s: kein Pflicht-Unterschriftsfeld" % kennung)
    if kennung == "v2":
        typen = {f["typ"] for f in felder if f.get("konstant")}
        if typen != set(AUTO_TYPEN):
            fehler.append("v2: schreibgeschützt müssen genau Kind, Veranstaltung und "
                          "Erziehungsberechtigte/r sein")
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
        description="Einwilligungs-PDFs und Sign-Vorlagen (v1, v2) für kjr_event_sign erzeugen.")
    p.add_argument("--check", action="store_true",
                   help="nichts schreiben, nur die abgelegten Dateien vergleichen")
    args = p.parse_args(argv)

    fehler = []
    dateien = []
    for variante in VARIANTEN:
        fehler.extend(pruefe_tabelle(variante))
        dateien.append((_pfad(variante, "pdf_rel"), baue_pdf(variante)))
        dateien.append((_pfad(variante, "xml_rel"), baue_xml(variante)))
    if not args.check and not fehler:
        for pfad, inhalt in dateien:
            os.makedirs(os.path.dirname(pfad), exist_ok=True)
            with open(pfad, "wb") as datei:
                datei.write(inhalt)
            print("geschrieben: %s (%d Bytes)" % (os.path.relpath(pfad, REPO), len(inhalt)))
    for pfad, soll in dateien:
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
