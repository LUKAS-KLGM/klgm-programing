# -*- coding: utf-8 -*-
"""Aufräumen der Portalseite „Mein Konto" (/my).

Odoo blendet dort für jede installierte App eine Rubrik ein — Angebote,
Aufträge, Bestellungen, Projekte, Tickets. Für einen Kreisjugendring sind die
meisten davon sinnlos: er verkauft nichts und führt keine Kundenprojekte. Für
Mitgliedsverbände und Kooperationspartner steht am Ende eine Seite voller
Rubriken, die nie etwas enthalten, und die vier KJR-Rubriken gehen darin unter.

ANSATZ: Es wird NICHT aufgezählt, was verschwinden soll, sondern was bleibt.
Eine Liste auszublendender External IDs wäre ein Ratespiel — welche Apps auf
einer Instanz liegen, weiß dieses Modul nicht, und jede nicht installierte App
fehlt in der Liste bzw. steht zu Unrecht darin. Stattdessen werden alle Views
gesucht, die portal.portal_my_home erweitern, und alles deaktiviert, was nicht
aus einem Modul der Positivliste stammt. Das greift unabhängig davon, was sonst
installiert ist.

WANN ES LÄUFT:
  * bei der Installation (post_init_hook)
  * bei jedem Versionssprung (migrations/<version>/post-migration.py)
  * jederzeit von Hand über die Server-Aktion „Portalseite Mein Konto aufräumen"
    (Einstellungen ▸ Technisch ▸ Aktionen ▸ Server-Aktionen)
Der letzte Weg ist der wichtigste: auf einer bereits installierten Instanz läuft
ein post_init_hook nie.

Wer eine Rubrik später bewusst wieder einblendet, behält sie bis zum nächsten
Lauf. Es ist eine Voreinstellung, keine Zwangsjacke.
"""
import logging

_logger = logging.getLogger(__name__)

# Module, deren Portal-Rubriken bleiben.
#  * die vier KJR-Module: das ist der Zweck des Portals
#  * portal: Kontaktdaten und Sicherheit, ohne die das Portal unbenutzbar wäre
#  * account: Rechnungen betreffen Mieter der Einrichtungen und Entleiher des
#    Materials und gehören ins Portal
DEFAULT_KEEP_MODULES = (
    'kjr_grant', 'kjr_event', 'kjr_facility', 'kjr_rental',
    'portal', 'account',
)

PARAM_KEEP = 'kjr_grant.portal_keep_modules'


def _keep_modules(env):
    """Module, deren Rubriken bleiben (Systemparameter schlägt Vorgabe)."""
    raw = (env['ir.config_parameter'].sudo().get_param(PARAM_KEEP) or '').strip()
    if not raw:
        return set(DEFAULT_KEEP_MODULES)
    return {x.strip() for x in raw.split(',') if x.strip()}


def cleanup_portal_home(env):
    """Fremde Rubriken auf /my deaktivieren. Idempotent, beliebig oft aufrufbar."""
    home = env.ref('portal.portal_my_home', raise_if_not_found=False)
    if not home:
        _logger.warning('Portalseite „Mein Konto" nicht gefunden — nichts zu tun.')
        return 0

    keep = _keep_modules(env)
    views = env['ir.ui.view'].sudo().search([
        ('inherit_id', '=', home.id), ('active', '=', True),
    ])
    if not views:
        return 0

    # Herkunftsmodul je View über die External ID bestimmen. Ohne External ID
    # stammt die View aus dem Website-Editor (von Hand angelegt) — die bleibt,
    # weil sie jemand bewusst gebaut hat.
    data = env['ir.model.data'].sudo().search([
        ('model', '=', 'ir.ui.view'), ('res_id', 'in', views.ids),
    ])
    module_by_view = {d.res_id: d.module for d in data}

    deactivated = []
    for view in views:
        module = module_by_view.get(view.id)
        if module is None or module in keep:
            continue
        view.active = False
        deactivated.append('%s.%s' % (module, view.name or view.id))

    if deactivated:
        _logger.info(
            'Portal „Mein Konto": %d fremde Rubrik(en) ausgeblendet: %s',
            len(deactivated), ', '.join(deactivated))
    else:
        _logger.info('Portal „Mein Konto": nichts auszublenden.')
    return len(deactivated)


def post_init_hook(env):
    """Bei der Installation aufräumen."""
    cleanup_portal_home(env)
