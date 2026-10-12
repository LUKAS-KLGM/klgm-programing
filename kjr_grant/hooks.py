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

from odoo import SUPERUSER_ID, fields

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


def backfill_affiliation_requests(env):
    """Aktive Portalkonten, die bereits unter einem Mitgliedsverband hängen, gelten
    als genehmigt (Vereinsregistrierung, seit 19.0.16.0.0). Idempotent.

    „Unter einem Mitgliedsverband“ heißt: derselbe Maßstab wie für die Rechte
    (res.partner._kjr_grants_member_rights, Mitgliedsverband im Teilbaum des
    commercial partners). Ein Dachverband ohne eigene Mitgliedschaft, unter dem
    Mitgliedsorganisationen hängen, zählt also mit; Zielorganisation des Nachweises
    ist immer der commercial partner.

    Ausgelassen werden Zugänge direkt auf dem Verbandspartner (kein Antrag nötig),
    nicht zugeordnete Konten, archivierte Konten (search mit active_test) und
    Personen, für die schon eine Vereinsregistrierung besteht. Ins Protokoll kommt
    nur der Zähler.
    """
    Request = env['kjr.affiliation.request'].sudo().with_context(
        tracking_disable=True, mail_create_nolog=True,
        mail_create_nosubscribe=True, mail_notrack=True)
    users = env['res.users'].sudo().search([('share', '=', True)])
    count = 0
    for user in users:
        partner = user.partner_id
        commercial = partner.commercial_partner_id
        # Gleicher Maßstab wie für die Rechte (child_of, schließt den Dachverband
        # ohne eigene Mitgliedschaft mit Mitgliedsorganisationen darunter ein).
        if not partner or commercial == partner or not partner._kjr_grants_member_rights():
            continue
        if Request.search_count([('partner_id', '=', partner.id)], limit=1):
            continue
        Request.create({
            'partner_id': partner.id,
            'user_id': user.id,
            'company_id': user.company_id.id or env.company.id,
            'requested_name': commercial.name,
            'state': 'approved',
            'origin': 'migration',
            'target_partner_id': commercial.id,
            'date_requested': user.create_date,
            'date_decided': fields.Datetime.now(),
            'decided_by_id': SUPERUSER_ID,
        })
        count += 1
    return count


def post_init_hook(env):
    """Bei der Installation aufräumen und Bestandskonten übernehmen.

    Die Übernahme läuft auch hier, weil is_kjr_member über kjr_rental und
    kjr_facility schon vor der Installation von kjr_grant gefüllt sein kann.
    """
    cleanup_portal_home(env)
    count = backfill_affiliation_requests(env)
    _logger.info('Vereinsregistrierung: %d Bestandskonto(en) als genehmigt übernommen.', count)
