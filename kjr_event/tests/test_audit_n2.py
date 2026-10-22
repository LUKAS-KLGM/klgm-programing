# -*- coding: utf-8 -*-
"""Prüfbericht 22.10.2026 (19.0.5.11.1): deutsche Fassung der Mailvorlagen,
deutsches Datumsformat auf der Veranstaltungsseite."""
import json

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.kjr_event.lang_fill import fill_module_templates


@tagged('post_install', '-at_install')
class TestKjrEventAuditN2(TransactionCase):

    def test_module_templates_get_german_copy(self):
        self.env['res.lang']._activate_lang('de_DE')
        template = self.env.ref('kjr_event.mail_template_packing_list')
        self.env.cr.execute(
            "UPDATE mail_template SET subject = %s WHERE id = %s",
            [json.dumps({'en_US': 'Packliste {{ object.event_id.name }}'}), template.id])
        template.invalidate_recordset()
        self.assertGreaterEqual(fill_module_templates(self.env, 'kjr_event'), 1)
        self.env.cr.execute("SELECT subject FROM mail_template WHERE id = %s", [template.id])
        self.assertEqual(self.env.cr.fetchone()[0].get('de_DE'),
                         'Packliste {{ object.event_id.name }}')
        # Alle Vorlagen des Moduls haben danach eine de_DE-Fassung.
        data = self.env['ir.model.data'].search(
            [('module', '=', 'kjr_event'), ('model', '=', 'mail.template')])
        self.env.cr.execute(
            "SELECT id FROM mail_template WHERE id = ANY(%s) AND NOT body_html ? 'de_DE'",
            [data.mapped('res_id')])
        self.assertFalse(self.env.cr.fetchall())

    def _render_dates(self, event):
        self.env['res.lang']._activate_lang('de_DE')
        html = self.env['ir.qweb'].with_context(lang='de_DE')._render(
            'website_event.event_description_dates', {
                'event': event, 'opt_event_dates_block': True,
                'website_visitor_timezone': event.date_tz, 'slots': {},
            })
        return str(html)

    def test_event_page_date_german(self):
        event = self.env['event.event'].create({
            'name': 'Selbstbehauptung (Datum)', 'date_tz': 'Europe/Berlin',
            'date_begin': '2026-12-30 09:00:00', 'date_end': '2026-12-31 13:30:00'})
        html = self._render_dates(event)
        self.assertIn('>30.<', html)
        self.assertIn('>31.<', html)
        self.assertIn('Dezember 2026', html, 'Kalenderjahr statt Wochenjahr, deutscher Monat')
        self.assertNotIn('2027', html)

    def test_event_page_date_german_one_day(self):
        event = self.env['event.event'].create({
            'name': 'Tagesfahrt (Datum)', 'date_tz': 'Europe/Berlin',
            'date_begin': '2026-11-03 09:00:00', 'date_end': '2026-11-03 13:30:00'})
        html = self._render_dates(event)
        self.assertIn('>03.<', html)
        self.assertIn('November 2026', html)
