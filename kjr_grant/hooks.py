# -*- coding: utf-8 -*-
"""Aufräumen der Portalseite „Mein Konto" (/my) bei der Installation.

Odoo blendet dort für jede installierte App eine Rubrik ein — Angebote,
Aufträge, Bestellungen, Projekte, Tickets. Für einen Kreisjugendring sind die
meisten davon sinnlos: er verkauft nichts und führt keine Kundenprojekte. Für
Mitgliedsverbände und Kooperationspartner steht am Ende eine Seite voller
Rubriken, die nie etwas enthalten, und die vier KJR-Rubriken gehen darin unter.

WARUM ALS HOOK UND NICHT ALS XML-DATENSATZ:
Ein <record id="sale.portal_my_home_sale"> mit active=False setzt voraus, dass
es diese External ID gibt. Ist die App nicht installiert, bricht die
Installation von kjr_grant mit einem Fehler ab — und welche Apps auf einer
Instanz liegen, weiß dieses Modul nicht. Der Hook löst jede ID einzeln und
defensiv auf und überspringt, was er nicht findet.

WANN ES GREIFT:
Nur bei der Installation, nicht bei jedem Update. Wer eine Rubrik später bewusst
wieder einblendet, behält sie. Das ist gewollt — das hier ist eine
Voreinstellung, keine Zwangsjacke.

PFLEGE:
Die Liste steht im Systemparameter 'kjr_grant.portal_hidden_entries' (kommagetrennte
External IDs). Ist er gesetzt, gilt er anstelle der Vorgabe unten. So lässt sich
die Auswahl anpassen, ohne den Code zu ändern.

TODO(KJR): Die Vorgabeliste ist nach den üblichen Odoo-Modulnamen
zusammengestellt, aber NICHT gegen die Zielinstanz geprüft. Nach dem ersten
Deployment ins Log schauen: der Hook protokolliert, was er ausgeblendet hat und
was er nicht gefunden hat. Danach die Liste bereinigen.
"""
import logging

_logger = logging.getLogger(__name__)

# Rubriken, die auf der Portalseite eines Jugendrings nichts verloren haben.
# BEWUSST NICHT dabei: 'account.portal_my_home_invoice' — Rechnungen betreffen
# Mieter der Einrichtungen und Entleiher des Materials und gehören ins Portal.
# Ebenso wenig die Kernrubriken von 'portal' selbst (Kontaktdaten, Sicherheit).
DEFAULT_HIDDEN_PORTAL_ENTRIES = (
    'sale.portal_my_home_sale',
    'sale.portal_my_home_menu_sale',
    'purchase.portal_my_home_purchase',
    'project.portal_my_home_project',
    'project.portal_my_home_task',
    'helpdesk.portal_my_home_helpdesk',
    'repair.portal_my_home_repair',
    'stock.portal_my_home_stock',
    'sale_subscription.portal_my_home_subscription',
    'hr_expense.portal_my_home_expense',
)

PARAM_KEY = 'kjr_grant.portal_hidden_entries'


def _entries_to_hide(env):
    """Liste der auszublendenden External IDs (Systemparameter schlägt Vorgabe)."""
    raw = (env['ir.config_parameter'].sudo().get_param(PARAM_KEY) or '').strip()
    if not raw:
        return DEFAULT_HIDDEN_PORTAL_ENTRIES
    return tuple(x.strip() for x in raw.split(',') if x.strip())


def post_init_hook(env):
    """Nicht benötigte Standardrubriken auf /my ausblenden."""
    hidden, missing = [], []
    for xmlid in _entries_to_hide(env):
        view = env.ref(xmlid, raise_if_not_found=False)
        if not view:
            missing.append(xmlid)
            continue
        if not view.active:
            continue
        view.active = False
        hidden.append(xmlid)

    if hidden:
        _logger.info(
            'Portal „Mein Konto": %d Standardrubrik(en) ausgeblendet: %s',
            len(hidden), ', '.join(hidden))
    if missing:
        # Kein Fehler: die zugehörige App ist schlicht nicht installiert.
        _logger.info(
            'Portal „Mein Konto": %d Eintrag/Einträge nicht gefunden (App nicht '
            'installiert, kein Problem): %s', len(missing), ', '.join(missing))
    if not hidden and not missing:
        _logger.info('Portal „Mein Konto": nichts auszublenden.')
