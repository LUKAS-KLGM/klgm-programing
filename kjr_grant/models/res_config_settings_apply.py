# -*- coding: utf-8 -*-
"""Einstellbare Texte und Links der Bestätigungen im Zuschussantrag (19.0.17.0.0).

Kundenabstimmung (Besprechung mit der Kassenleitung, Punkte B40 und B43):

* Checkbox 2 „Ich habe die Zuschussrichtlinien gelesen" bekommt einen Link auf
  die Richtlinien. Die Adresse ist einstellbar, weil jeder Träger seine
  Richtlinien woanders veröffentlicht (eigene Seite, PDF im Dokumentenbereich).
  Ein eigenes Richtlinien-Dokument liefert das Modul nicht aus.
  Bestandsinstanzen: ``migrations/19.0.17.0.0/post-formular.py`` setzt den
  Parameter auf das öffentliche Richtlinien-PDF der Website, wenn es eines gibt
  (``find_guidelines_attachment_url``). Ist nichts gepflegt, führt der Link auf
  den Abschnitt „Zuschussrichtlinien" der Hilfeseite
  (``/service/zuschuss-hilfe#zuschussrichtlinien``). Dort steht der Link auf
  das Dokument, sobald eine Adresse gepflegt ist, sonst der Hinweis, dass die
  Geschäftsstelle die Richtlinien zusendet. Der Link läuft also nie ins Leere.
* Checkbox 3 „Ich versichere ..." bekommt den Hinweis, wer die Fördermittel
  stellt. Beim KJR Oberallgäu ist das der Landkreis Oberallgäu. Für andere
  Träger (White-Label) ist der Satz frei einstellbar oder ganz abschaltbar.

Gespeichert wird in ``ir.config_parameter`` über ``config_parameter`` am Feld,
also ohne Seed-Datensatz (Begründung in ``res_config_settings.py``). Fehlt der
Parameter, gilt die Vorgabe aus den Konstanten unten. Ein geleertes Feld löscht
den Parameter (``res_config.py``: ``set_values``), danach gilt wieder die
Vorgabe. Deshalb gibt es für den Fördermittel-Hinweis einen eigenen Schalter
zum Ausblenden; er ist bewusst NEGATIV benannt (``hide_...``), weil Odoo einen
Boolean-Parameter mit Vorgabe ``True`` nach dem Abhaken löscht und beim
nächsten Öffnen wieder als ``True`` liest.
"""
import re
from urllib.parse import quote

from odoo import fields, models

# Vorgaben, solange in den Einstellungen nichts gepflegt ist.
DEFAULT_FUNDING_NOTICE = (
    'Die Mittel für die Förderung der Jugendarbeit stellt der Landkreis Oberallgäu.'
)
HELP_PAGE_PATH = '/service/zuschuss-hilfe'
GUIDELINES_ANCHOR = 'zuschussrichtlinien'
DEFAULT_GUIDELINES_URL = '%s#%s' % (HELP_PAGE_PATH, GUIDELINES_ANCHOR)

PARAM_FUNDING_NOTICE = 'kjr_grant.funding_notice'
PARAM_HIDE_FUNDING_NOTICE = 'kjr_grant.hide_funding_notice'
PARAM_GUIDELINES_URL = 'kjr_grant.guidelines_url'


def _safe_url(url):
    """Nur relative Pfade und http(s)-Adressen zulassen.

    Die Adresse landet im href des Antragsformulars. Ein ``javascript:``- oder
    ``data:``-Link aus einem vertippten oder böswilligen Parameter würde dort
    beim Klick ausgeführt. Alles andere fällt auf die Vorgabe zurück.
    """
    url = (url or '').strip()
    if not url:
        return DEFAULT_GUIDELINES_URL
    lowered = url.lower()
    if lowered.startswith(('http://', 'https://')):
        return url
    if url.startswith('/') and not url.startswith('//'):
        return url
    return DEFAULT_GUIDELINES_URL


def _is_help_page(url):
    """True, wenn ``url`` auf die Hilfeseite dieses Moduls zeigt (mit oder ohne Anker).

    Dann ist keine eigene Richtlinien-Adresse gepflegt. Das kommt auch vor,
    wenn die Einstellungsmaske die Vorgabe beim Speichern in den Parameter
    schreibt (``default`` am Feld).
    """
    path = (url or '').split('#', 1)[0].split('?', 1)[0].rstrip('/')
    return path == HELP_PAGE_PATH


def find_guidelines_attachment_url(env):
    """Adresse des öffentlichen Richtlinien-PDFs der Website, sonst ''.

    Gesucht wird ein öffentlicher (``public``) PDF-Anhang, dessen Name
    „Zuschussrichtlinien" enthält; so liegt das Dokument auf der Zuschussseite
    der KJR-Website (Übernahme aus WordPress). Bei mehreren Treffern gewinnt
    die höchste Jahreszahl im Dateinamen, dann der neueste Anhang. Nicht
    öffentliche Anhänge bleiben außen vor: Antragstellende ohne Login dürften
    sie nicht öffnen (``ir.attachment``: ``public`` ist immer lesbar).
    Rückgabe ``/web/content/<id>/<Dateiname>``, dieselbe Form wie im
    Website-Modul (``website/controllers/main.py``).
    """
    attachments = env['ir.attachment'].sudo().search([
        ('public', '=', True),
        ('mimetype', '=', 'application/pdf'),
        ('name', 'ilike', 'zuschussrichtlinie'),
        ('res_field', '=', False),
    ], order='id desc')
    if not attachments:
        return ''

    def _year(att):
        years = [int(y) for y in re.findall(r'(?<!\d)(20\d\d)(?!\d)', att.name or '')]
        return max(years) if years else 0

    best = max(attachments, key=lambda att: (_year(att), att.id))
    return '/web/content/%s/%s' % (best.id, quote(best.name or 'zuschussrichtlinien.pdf'))


def get_apply_form_settings(env):
    """Texte und Links für die Bestätigungen im Antragsformular.

    Rückgabe: dict mit
      ``funding_notice``  Satz unter Checkbox 3, '' wenn ausgeblendet
      ``guidelines_url``  Ziel des Links „Zuschussrichtlinien" in Checkbox 2
      ``guidelines_document_url``  gepflegte Richtlinien-Adresse, '' wenn keine
                          gepflegt ist (Vorgabe bzw. Hilfeseite); für den
                          Abschnitt „Zuschussrichtlinien" der Hilfeseite

    Eine Stelle für Controller und Tests, damit Vorlage und Prüfung nicht
    auseinanderlaufen. sudo(): Portalnutzer dürfen ir.config_parameter nicht lesen.
    """
    params = env['ir.config_parameter'].sudo()
    hidden = (params.get_param(PARAM_HIDE_FUNDING_NOTICE) or '').strip().lower() in (
        '1', 'true', 'yes',
    )
    notice = '' if hidden else (
        (params.get_param(PARAM_FUNDING_NOTICE) or '').strip() or DEFAULT_FUNDING_NOTICE
    )
    guidelines_url = _safe_url(params.get_param(PARAM_GUIDELINES_URL))
    return {
        'funding_notice': notice,
        'guidelines_url': guidelines_url,
        'guidelines_document_url': '' if _is_help_page(guidelines_url) else guidelines_url,
    }


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    kjr_grant_guidelines_url = fields.Char(
        string='Link zu den Zuschussrichtlinien',
        config_parameter=PARAM_GUIDELINES_URL,
        default=DEFAULT_GUIDELINES_URL,
        help='Ziel des Links „Zuschussrichtlinien" in der zweiten Pflichtbestätigung '
             'des Antragsformulars und der Hilfeseite. Relativer Pfad (z. B. der '
             'Link auf ein öffentlich hochgeladenes PDF, /web/content/...) oder '
             'vollständige Adresse mit https://. Leer lassen setzt die Vorgabe wieder '
             'ein: dann führt der Link auf die Hilfeseite, und dort steht, dass die '
             'Geschäftsstelle die Richtlinien zusendet.',
    )
    kjr_grant_funding_notice = fields.Char(
        string='Hinweis zur Herkunft der Fördermittel',
        config_parameter=PARAM_FUNDING_NOTICE,
        default=DEFAULT_FUNDING_NOTICE,
        help='Steht im Antragsformular direkt unter der dritten Pflichtbestätigung '
             '(Angaben vollständig und wahrheitsgemäß). Leer lassen setzt die '
             'Vorgabe wieder ein; ganz ausblenden über den Schalter daneben.',
    )
    kjr_grant_hide_funding_notice = fields.Boolean(
        string='Hinweis zur Herkunft der Fördermittel ausblenden',
        config_parameter=PARAM_HIDE_FUNDING_NOTICE,
    )
