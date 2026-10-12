# -*- coding: utf-8 -*-
"""Unterschriftsseite zum Buchungsvertrag (reportlab) und Geometrie der Sign-Felder.

Reine Funktionen ohne Odoo-Umgebung (testbar ohne Datenbank).

Zeichnung und Sign-Items entstehen aus denselben mm-Konstanten (``FIELDS``,
``FIELD_X``, ``FIELD_W``). Weicht die Lage auf der Instanz ab, nur diese
Konstanten anpassen: Rahmen und Felder verschieben sich gemeinsam.

Koordinaten in mm ab OBERKANTE der Seite, x ab linkem Rand.
Odoo Sign: Anteile 0..1, Ursprung oben links, posY = Oberkante des Feldes
(ent-19 sign/models/sign_document.py, render_document_with_items:
``height * (1 - item.posY - item.height)``). reportlab: Ursprung unten links.
"""
import io

from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

LEFT = 20          # mm, Beschriftungsspalte
FIELD_X = 60       # mm, linker Rand der Felder
FIELD_W = 100      # mm, Breite der Felder
TEXT_W = 170       # mm, Umbruchbreite Fließtext
FONT = 'Helvetica'
FONT_BOLD = 'Helvetica-Bold'
# Odoo Sign stempelt Text in Höhe ``Seitenhöhe * item.height * 0.8`` und ohne
# Beschneidung (ent-19 sign/models/sign_document.py, render_document_with_items).
# Ort/Datum daher 5 mm hoch (A4: height 0.017 -> ca. 11 pt, nahe dem Sign-Standard
# 0.015); die Unterschrift bleibt 30 mm hoch (Bild wird in das Feld eingepasst).
FIELDS = (         # (key, top_mm, height_mm)
    ('place', 112, 5),
    ('date', 128, 5),
    ('signature', 144, 30),
)
LABEL_BASELINE = 4  # mm unter Feldoberkante: Beschriftung mittig neben 5-mm-Feldern
FIELD_KEYS = tuple(key for key, _top, _height in FIELDS)


def _safe(text):
    """Die Standardschrift Helvetica kann nur WinAnsi (cp1252); alles andere wird '?'."""
    return (text or '').encode('cp1252', 'replace').decode('cp1252')


def field_geometry(page_w_pt, page_h_pt):
    """Lage der Sign-Felder als Anteile der Seite (für sign.item).

    :param float page_w_pt: Seitenbreite in Punkt
    :param float page_h_pt: Seitenhöhe in Punkt
    :return: Liste von dicts mit key, posX, posY, width, height (3 Nachkommastellen)
    :raises ValueError: wenn ein Feld nicht vollständig auf der Seite liegt
    """
    if not page_w_pt or not page_h_pt or page_w_pt <= 0 or page_h_pt <= 0:
        raise ValueError('Ungültige Seitengröße.')
    result = []
    for key, top, height in FIELDS:
        geo = {
            'key': key,
            'posX': round(FIELD_X * mm / page_w_pt, 3),
            'posY': round(top * mm / page_h_pt, 3),
            'width': round(FIELD_W * mm / page_w_pt, 3),
            'height': round(height * mm / page_h_pt, 3),
        }
        if not (0 <= geo['posX'] and geo['posX'] + geo['width'] <= 1
                and 0 <= geo['posY'] and geo['posY'] + geo['height'] <= 1):
            raise ValueError('Sign-Feld %s liegt außerhalb der Seite.' % key)
        result.append(geo)
    return result


def build_signature_page(page_w_pt, page_h_pt, texts):
    """Zeichnet die Unterschriftsseite als einseitiges PDF.

    :param float page_w_pt: Seitenbreite in Punkt (wie die letzte Vertragsseite)
    :param float page_h_pt: Seitenhöhe in Punkt
    :param dict texts: alle Texte (bereits übersetzt), Schlüssel siehe
        ``kjr.facility.booking._kjr_sign_page_texts``
    :return: PDF als bytes
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w_pt, page_h_pt))

    def y(top_mm):
        return page_h_pt - top_mm * mm

    c.setTitle(_safe(texts.get('title')))
    c.setFont(FONT_BOLD, 14)
    c.drawString(LEFT * mm, y(30), _safe(texts.get('title')))

    # Eckdaten: je Angabe höchstens 2 Zeilen -> endet spätestens bei 42 + 8 * 5 = 82 mm.
    c.setFont(FONT, 10)
    top = 42
    for label, value in ((texts.get('label_facility'), texts.get('facility')),
                         (texts.get('label_period'), texts.get('period')),
                         (texts.get('label_party'), texts.get('party')),
                         (texts.get('label_company'), texts.get('company'))):
        line_text = _safe('%s: %s' % (label or '', value or ''))
        for line in simpleSplit(line_text, FONT, 10, TEXT_W * mm)[:2]:
            c.drawString(LEFT * mm, y(top), line)
            top += 5

    # Erklärung: ab max(., 78 mm), höchstens 5 Zeilen -> letzte Grundlinie <= 105 mm,
    # also oberhalb des ersten Feldes (112 mm).
    top = max(top + 3, 78)
    for line in simpleSplit(_safe(texts.get('declaration')), FONT, 10, TEXT_W * mm)[:5]:
        c.drawString(LEFT * mm, y(top), line)
        top += 5

    labels = {
        'place': texts.get('label_place'),
        'date': texts.get('label_date'),
        'signature': texts.get('label_signature'),
    }
    c.setStrokeGray(0.5)
    c.setLineWidth(0.5)
    for key, ftop, fheight in FIELDS:
        c.setFont(FONT, 10)
        c.drawString(LEFT * mm, y(ftop + LABEL_BASELINE), _safe(labels[key]))
        c.rect(FIELD_X * mm, y(ftop + fheight), FIELD_W * mm, fheight * mm, stroke=1, fill=0)

    last_bottom = max(ftop + fheight for _key, ftop, fheight in FIELDS)
    c.setFont(FONT, 8)
    c.drawString(FIELD_X * mm, y(last_bottom + 4), _safe(texts.get('caption')))

    c.setFillGray(0.4)
    c.drawString(LEFT * mm, 12 * mm, _safe(texts.get('company')))
    c.drawRightString(page_w_pt - LEFT * mm, 12 * mm, _safe(texts.get('footer_page')))
    c.showPage()
    c.save()
    return buf.getvalue()
