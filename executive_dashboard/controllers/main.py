import logging

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class ExecutiveDashboardController(http.Controller):

    @http.route('/executive_dashboard/data', type='jsonrpc', auth='user')
    def get_dashboard_data(self, dashboard_id, period='last_30_days', activity_state='all'):
        dashboard = request.env['executive.dashboard'].browse(dashboard_id)
        if not dashboard.exists():
            return {'error': 'Dashboard nicht gefunden'}
        return dashboard._get_dashboard_data(period, activity_state=activity_state)

    @http.route('/executive_dashboard/list', type='jsonrpc', auth='user')
    def get_dashboards(self):
        dashboards = request.env['executive.dashboard'].search([])
        return [{
            'id': d.id,
            'name': d.name,
            'role': d.role,
            'icon': d.icon,
            'default_period': d.default_period,
            'auto_refresh': d.auto_refresh or 0,
            'comparison_mode': d.comparison_mode or 'previous_period',
        } for d in dashboards]

    @http.route('/executive_dashboard/update_kpi', type='jsonrpc', auth='user')
    def update_kpi(self, kpi_id, values):
        kpi = request.env['executive.dashboard.kpi'].browse(kpi_id)
        if not kpi.exists():
            return {'error': 'KPI nicht gefunden'}
        allowed = {'display_type', 'width', 'target_value', 'budget_value',
                   'name', 'description', 'unit', 'color', 'journal_id'}
        safe_vals = {k: v for k, v in values.items() if k in allowed}
        if safe_vals:
            try:
                kpi.check_access_rights('write')
                kpi.check_access_rule('write')
            except AccessError:
                return {'error': 'Keine Berechtigung'}
            kpi.sudo().write(safe_vals)
        return {'ok': True}

    @http.route('/executive_dashboard/drilldown', type='jsonrpc', auth='user')
    def drilldown(self, kpi_id, period='last_30_days'):
        """Return a dynamic action to view the underlying records of a KPI."""
        kpi = request.env['executive.dashboard.kpi'].browse(kpi_id)
        if not kpi.exists():
            return False
        # If KPI has a predefined action, use it
        if kpi.action_xmlid:
            return kpi.action_xmlid
        # For model-based KPIs, build a dynamic action
        if kpi.source_type == 'model' and kpi.model_name:
            domain = safe_eval(kpi.domain or '[]')
            if kpi.apply_date_filter and kpi.date_field:
                date_from, date_to = kpi._get_date_range(period)
                domain += [
                    (kpi.date_field, '>=', str(date_from)),
                    (kpi.date_field, '<=', str(date_to)),
                ]
            return {
                'type': 'ir.actions.act_window',
                'name': kpi.name,
                'res_model': kpi.model_name,
                'views': [[False, 'list'], [False, 'form']],
                'domain': domain,
                'target': 'current',
            }
        return False

    # ── Drag & Drop: Sequence Update ──

    @http.route('/executive_dashboard/update_sequence', type='jsonrpc', auth='user')
    def update_sequence(self, kpi_ids):
        """kpi_ids: list of {id, sequence}"""
        KPI = request.env['executive.dashboard.kpi'].sudo()
        for item in kpi_ids:
            kpi = KPI.browse(item['id'])
            if kpi.exists():
                kpi.write({'sequence': item['sequence']})
        return {'ok': True}

    # ── Notes ──

    @http.route('/executive_dashboard/notes/get', type='jsonrpc', auth='user')
    def get_notes(self, kpi_id):
        notes = request.env['executive.dashboard.kpi.note'].search(
            [('kpi_id', '=', kpi_id)], order='create_date desc', limit=50)
        return [{
            'id': n.id,
            'text': n.text,
            'user': n.user_id.name,
            'date': n.create_date.strftime('%d.%m.%Y %H:%M') if n.create_date else '',
        } for n in notes]

    @http.route('/executive_dashboard/notes/create', type='jsonrpc', auth='user')
    def create_note(self, kpi_id, text):
        note = request.env['executive.dashboard.kpi.note'].create({
            'kpi_id': kpi_id,
            'text': text,
        })
        return {
            'id': note.id,
            'text': note.text,
            'user': note.user_id.name,
            'date': note.create_date.strftime('%d.%m.%Y %H:%M') if note.create_date else '',
        }

    @http.route('/executive_dashboard/notes/delete', type='jsonrpc', auth='user')
    def delete_note(self, note_id):
        note = request.env['executive.dashboard.kpi.note'].browse(note_id)
        if note.exists() and note.user_id.id == request.env.uid:
            note.unlink()
        return {'ok': True}

    # ── AI Insights ──

    @http.route('/executive_dashboard/has_ai_key', type='jsonrpc', auth='user')
    def has_ai_key(self):
        return request.env['executive.dashboard'].has_ai_key()

    @http.route('/executive_dashboard/module_status', type='jsonrpc', auth='user')
    def module_status(self):
        """Check optional module availability."""
        return {
            'activity_history': 'activity.summary' in request.env,
        }

    @http.route('/executive_dashboard/ai_insights', type='jsonrpc', auth='user')
    def get_ai_insights(self, dashboard_id, period='last_30_days'):
        dashboard = request.env['executive.dashboard'].browse(dashboard_id)
        if not dashboard.exists():
            return {'summary': [], 'ai': []}
        return {
            'summary': dashboard._get_ai_insights(period),
            'ai': [],
        }

    @http.route('/executive_dashboard/ai_insights_real', type='jsonrpc', auth='user')
    def get_real_ai_insights(self, dashboard_id, period='last_30_days'):
        dashboard = request.env['executive.dashboard'].browse(dashboard_id)
        if not dashboard.exists():
            return []
        return dashboard._get_real_ai_insights(period)

    # ── Templates ──

    @http.route('/executive_dashboard/templates', type='jsonrpc', auth='user')
    def get_templates(self):
        templates = request.env['executive.dashboard']._get_templates()
        return [{
            'key': t['key'],
            'name': t['name'],
            'description': t['description'],
            'icon': t['icon'],
            'kpi_count': len(t.get('kpis', [])),
        } for t in templates]

    @http.route('/executive_dashboard/create_from_template', type='jsonrpc', auth='user')
    def create_from_template(self, template_key):
        return request.env['executive.dashboard'].create_from_template(template_key)

    # ── KPI Builder ──

    @http.route('/executive_dashboard/builder/models', type='jsonrpc', auth='user')
    def get_available_models(self):
        """Return models suitable for KPI creation."""
        useful_models = [
            ('sale.report', 'Verkaufsanalyse'),
            ('sale.order', 'Verkaufsaufträge'),
            ('account.move', 'Buchungen'),
            ('account.invoice.report', 'Rechnungsanalyse'),
            ('purchase.report', 'Einkaufsanalyse'),
            ('purchase.order', 'Einkaufsaufträge'),
            ('stock.picking', 'Transfers'),
            ('crm.lead', 'CRM Leads'),
            ('project.task', 'Aufgaben'),
            ('project.project', 'Projekte'),
            ('hr.employee', 'Mitarbeiter'),
            ('hr.leave', 'Abwesenheiten'),
            ('res.partner', 'Kontakte'),
            ('mail.activity', 'Aktivitäten'),
        ]
        result = []
        for model_name, label in useful_models:
            try:
                request.env[model_name]
                result.append({'name': model_name, 'label': label})
            except KeyError:
                pass
        return result

    @http.route('/executive_dashboard/builder/fields', type='jsonrpc', auth='user')
    def get_model_fields(self, model_name):
        """Return numeric fields for a given model."""
        try:
            Model = request.env[model_name]
        except KeyError:
            return []

        numeric_types = ('integer', 'float', 'monetary')
        fields_data = Model.fields_get()
        result = []
        for fname, finfo in sorted(fields_data.items(), key=lambda x: x[1].get('string', '')):
            if finfo.get('type') in numeric_types and not fname.startswith('__'):
                result.append({
                    'name': fname,
                    'label': finfo.get('string', fname),
                    'type': finfo.get('type'),
                })
        return result

    @http.route('/executive_dashboard/builder/date_fields', type='jsonrpc', auth='user')
    def get_date_fields(self, model_name):
        """Return date/datetime fields for a given model."""
        try:
            Model = request.env[model_name]
        except KeyError:
            return []

        date_types = ('date', 'datetime')
        fields_data = Model.fields_get()
        result = []
        for fname, finfo in sorted(fields_data.items(), key=lambda x: x[1].get('string', '')):
            if finfo.get('type') in date_types and not fname.startswith('__'):
                result.append({
                    'name': fname,
                    'label': finfo.get('string', fname),
                })
        return result

    @http.route('/executive_dashboard/builder/create', type='jsonrpc', auth='user')
    def create_custom_kpi(self, dashboard_id, values):
        """Create a KPI from the builder dialog."""
        dashboard = request.env['executive.dashboard'].browse(dashboard_id)
        if not dashboard.exists():
            return {'error': 'Dashboard nicht gefunden'}

        # Get max sequence
        max_seq = max((k.sequence for k in dashboard.kpi_ids), default=0)

        allowed_fields = {
            'name', 'display_type', 'source_type', 'model_name', 'domain',
            'measure_field', 'aggregate', 'group_by', 'unit', 'color',
            'width', 'date_field', 'apply_date_filter', 'show_comparison',
            'target_value', 'target_warning', 'target_critical', 'budget_value',
            'formula', 'sql_query',
        }
        safe_vals = {k: v for k, v in values.items() if k in allowed_fields}
        safe_vals['dashboard_id'] = dashboard_id
        safe_vals['sequence'] = max_seq + 10

        kpi = request.env['executive.dashboard.kpi'].create(safe_vals)
        return {'id': kpi.id, 'name': kpi.name}

    # ── Dashboard Creator ──

    @http.route('/executive_dashboard/all_kpis', type='jsonrpc', auth='user')
    def get_all_kpis(self):
        """Return all KPIs across all dashboards as a catalog."""
        kpis = request.env['executive.dashboard.kpi'].sudo().search(
            [('name', 'not like', '\\_%')], order='dashboard_id, sequence')
        seen = {}
        result = []
        for k in kpis:
            key = (k.name, k.source_type, k.model_name or '', k.formula or '', k.sql_query or '')
            if key in seen:
                continue
            seen[key] = True
            result.append({
                'id': k.id,
                'name': k.name,
                'description': k.description or '',
                'display_type': k.display_type,
                'unit': k.unit or '',
                'dashboard_name': k.dashboard_id.name,
            })
        return result

    @http.route('/executive_dashboard/create_dashboard', type='jsonrpc', auth='user')
    def create_dashboard(self, name, icon, kpi_ids):
        """Create a new dashboard by copying selected KPIs."""
        Dashboard = request.env['executive.dashboard'].sudo()
        KPI = request.env['executive.dashboard.kpi'].sudo()

        dashboard = Dashboard.create({
            'name': name,
            'role': 'custom',
            'icon': icon or 'fa-tachometer',
        })

        for i, item in enumerate(kpi_ids):
            src = KPI.browse(item['id'])
            if not src.exists():
                continue
            vals = {
                'dashboard_id': dashboard.id,
                'name': src.name,
                'description': src.description,
                'sequence': (i + 1) * 10,
                'display_type': item.get('display_type', src.display_type),
                'source_type': src.source_type,
                'model_name': src.model_name,
                'domain': src.domain,
                'measure_field': src.measure_field,
                'aggregate': src.aggregate,
                'group_by': src.group_by,
                'formula': src.formula,
                'sql_query': src.sql_query,
                'unit': src.unit,
                'color': item.get('color', src.color),
                'width': src.width,
                'date_field': src.date_field,
                'apply_date_filter': src.apply_date_filter,
                'show_comparison': src.show_comparison,
            }
            KPI.create(vals)

            # Copy hidden dependency KPIs (prefixed with _)
            for dep in src.dashboard_id.kpi_ids:
                if dep.name.startswith('_') and dep.name in (src.formula or ''):
                    dep_key = dep.name
                    existing = KPI.search([
                        ('dashboard_id', '=', dashboard.id), ('name', '=', dep_key)], limit=1)
                    if not existing:
                        KPI.create({
                            'dashboard_id': dashboard.id,
                            'name': dep.name,
                            'sequence': 1,
                            'display_type': 'scorecard',
                            'source_type': dep.source_type,
                            'model_name': dep.model_name,
                            'domain': dep.domain,
                            'measure_field': dep.measure_field,
                            'aggregate': dep.aggregate,
                            'formula': dep.formula,
                            'sql_query': dep.sql_query,
                            'date_field': dep.date_field,
                            'apply_date_filter': dep.apply_date_filter,
                            'show_comparison': False,
                        })

        return {'id': dashboard.id, 'name': dashboard.name}

    # ── Comparison Mode ──

    @http.route('/executive_dashboard/set_comparison', type='jsonrpc', auth='user')
    def set_comparison_mode(self, dashboard_id, mode):
        dashboard = request.env['executive.dashboard'].browse(dashboard_id)
        if dashboard.exists():
            try:
                dashboard.check_access_rights('write')
                dashboard.check_access_rule('write')
            except AccessError:
                return {'error': 'Keine Berechtigung'}
            dashboard.sudo().write({'comparison_mode': mode})
        return {'ok': True}
