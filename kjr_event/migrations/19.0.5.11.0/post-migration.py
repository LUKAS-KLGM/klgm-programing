# -*- coding: utf-8 -*-
"""19.0.5.11.0 (Termin 13.10.2026): Filter "Zielgruppe" auf der
Veranstaltungsübersicht entfernen.

Der Filter ist kein Code, sondern die veröffentlichte Schlagwort-Kategorie
"Zielgruppe" (event.tag.category). Sie wird nur unveröffentlicht, nicht
gelöscht: Schlagwörter und Zuordnungen bleiben erhalten, der KJR kann die
Kategorien danach selbst neu ordnen (Veranstaltungen → Konfiguration →
Schlagwort-Kategorien, "Auf der Website veröffentlicht").


Außerdem (Prüfbericht 22.10.2026):
* Mailvorlagen (noupdate): bei Minderjährigen gehen die Mails an die
  Erziehungsberechtigten; statt "Hallo <Name der Teilnehmer:in>" deshalb
  "Guten Tag,". Ersetzt wird nur der wörtliche Auslieferungstext.
* Website-Seite /service/schulungen (in der Datenbank gebaut, Schlüssel
  website.service-schulungen): Filter der Kurstermine auf die neue Einordnung
  'training', nur wenn der bekannte Filtertext gefunden wird, sonst Warnung.
"""
import json
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


OLD_GREETING = """<p>Hallo <t t-out="object.name or object.partner_id.name or ''"/>,</p>"""
NEW_GREETING = ("""<p t-if="object.is_minor">Guten Tag,</p><p t-else="">"""
                """Hallo <t t-out="object.name or object.partner_id.name or ''"/>,</p>""")
GREETING_TEMPLATES = ('mail_template_registration_confirm', 'mail_template_packing_list',
                      'mail_template_cancellation', 'mail_template_certificate')
OLD_FILTER = "('kjr_event_type', 'in', ['juleica_course', 'rescue_course'])"
NEW_FILTER = "('kjr_event_type', '=', 'training')"


def _migrate_greetings(env):
    for xmlid in GREETING_TEMPLATES:
        template = env.ref('kjr_event.%s' % xmlid, raise_if_not_found=False)
        if not template:
            continue
        env.cr.execute("SELECT body_html FROM mail_template WHERE id = %s", [template.id])
        body = env.cr.fetchone()[0] or {}
        changed = {lang: html.replace(OLD_GREETING, NEW_GREETING)
                   for lang, html in body.items() if html and OLD_GREETING in html}
        if changed:
            body.update(changed)
            env.cr.execute("UPDATE mail_template SET body_html = %s WHERE id = %s",
                           [json.dumps(body), template.id])
            _logger.info('kjr_event 19.0.5.11.0: Anrede in %s angepasst (%s).',
                         xmlid, ', '.join(changed))
    env.invalidate_all()


def _migrate_schulungen_page(env):
    views = env['ir.ui.view'].with_context(active_test=False).search(
        [('key', '=', 'website.service-schulungen')])
    if not views:
        _logger.info('kjr_event 19.0.5.11.0: Seite website.service-schulungen nicht gefunden.')
        return
    for view in views:
        env.cr.execute("SELECT arch_db FROM ir_ui_view WHERE id = %s", [view.id])
        arch = env.cr.fetchone()[0] or {}
        changed = {lang: text.replace(OLD_FILTER, NEW_FILTER)
                   for lang, text in arch.items() if text and OLD_FILTER in text}
        if changed:
            arch.update(changed)
            env.cr.execute("UPDATE ir_ui_view SET arch_db = %s WHERE id = %s",
                           [json.dumps(arch), view.id])
            _logger.info('kjr_event 19.0.5.11.0: Kursfilter der Seite /service/schulungen '
                         '(Ansicht %s) auf "Aus- und Weiterbildungen" umgestellt.', view.id)
        elif any(NEW_FILTER in (text or '') for text in arch.values()):
            continue
        else:
            _logger.warning('kjr_event 19.0.5.11.0: Ansicht %s (website.service-schulungen) '
                            'enthält den bekannten Kursfilter nicht; bitte von Hand auf '
                            "kjr_event_type = 'training' prüfen.", view.id)
    env.invalidate_all()
    env.registry.clear_cache('templates')


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    _migrate_greetings(env)
    _migrate_schulungen_page(env)
    Category = env['event.tag.category'].with_context(active_test=False)
    if 'is_published' not in Category._fields:
        return
    categories = Category.search([('is_published', '=', True)]).filtered(
        lambda c: (c.with_context(lang='de_DE').name or '').strip().lower() == 'zielgruppe'
        or (c.with_context(lang='en_US').name or '').strip().lower() == 'zielgruppe')
    if categories:
        categories.write({'is_published': False})
        _logger.info('kjr_event 19.0.5.11.0: Schlagwort-Kategorie "Zielgruppe" (%s) auf der '
                     'Website ausgeblendet.', categories.ids)
