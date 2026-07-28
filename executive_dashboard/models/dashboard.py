import json
import logging
from datetime import date, timedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class ExecutiveDashboard(models.Model):
    _name = 'executive.dashboard'
    _description = 'Executive Dashboard'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    role = fields.Selection([
        ('ceo', 'CEO — Company Overview'),
        ('cfo', 'CFO — Finance'),
        ('coo', 'COO — Operations'),
        ('cto', 'CTO — Projects & Team'),
        ('cso', 'CSO — Sales Performance'),
        ('custom', 'Custom'),
    ], required=True, default='custom')
    color = fields.Integer(default=0)
    icon = fields.Char(default='fa-tachometer')

    kpi_ids = fields.One2many('executive.dashboard.kpi', 'dashboard_id', string='KPIs')
    group_ids = fields.Many2many('res.groups', string='Visible to Groups',
        help='Empty = visible to all internal users')

    default_period = fields.Selection([
        ('last_7_days', 'Last 7 Days'),
        ('last_30_days', 'Last 30 Days'),
        ('last_90_days', 'Last 90 Days'),
        ('this_month', 'This Month'),
        ('this_quarter', 'This Quarter'),
        ('this_year', 'This Year'),
        ('last_year', 'Last Year'),
    ], default='last_30_days', required=True)

    auto_refresh = fields.Integer(default=0, help='Auto-refresh interval in seconds. 0 = off.')

    # ── Mail Report (v5, merged from dashboard_mail.py) ──
    mail_enabled = fields.Boolean('Email Sending Enabled', default=False)
    mail_frequency = fields.Selection([
        ('daily', 'Daily'),
        ('weekly', 'Weekly (Monday)'),
        ('monthly', 'Monthly (1st of the month)'),
    ], default='weekly')
    mail_recipient_ids = fields.Many2many(
        'res.users', string='Recipients',
        help='Users who receive the dashboard report by email')
    mail_last_sent = fields.Datetime('Last Sent', readonly=True)

    # ── Comparison Mode (v6) ──
    comparison_mode = fields.Selection([
        ('previous_period', 'Previous Period'),
        ('previous_year', 'Previous Year'),
        ('budget', 'Budget'),
    ], default='previous_period')

    # ── Multi-Company (v6) ──
    company_id = fields.Many2one('res.company', string='Company',
        default=lambda self: self.env.company)

    # ── Template origin ──
    template_key = fields.Char(readonly=True, help='Internal key of the industry template')

    # ═══════════════════════════════════════════
    # Actions
    # ═══════════════════════════════════════════

    def action_open_dashboard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'executive_dashboard',
            'name': self.name,
            'params': {'dashboard_id': self.id},
        }

    # ═══════════════════════════════════════════
    # Dashboard Data
    # ═══════════════════════════════════════════

    def _get_dashboard_data(self, period='last_30_days', activity_state='all'):
        self.ensure_one()
        comparison_mode = self.comparison_mode or 'previous_period'

        # Phase 1: Compute all model/sql KPIs and cache values
        kpi_cache = {}
        kpi_results = []
        for kpi in self.kpi_ids.sorted('sequence'):
            if kpi.source_type in ('model', 'sql', 'bank_balance'):
                result = kpi._compute_value(period, kpi_cache=None,
                    activity_state=activity_state, comparison_mode=comparison_mode)
                kpi_cache[kpi._cache_key()] = result['value']
                kpi_results.append(result)
            else:
                kpi_results.append(kpi)

        # Phase 2: Resolve formula KPIs using cached values
        final = []
        for item in kpi_results:
            if isinstance(item, dict):
                final.append(item)
            else:
                result = item._compute_value(period, kpi_cache=kpi_cache,
                    activity_state=activity_state, comparison_mode=comparison_mode)
                final.append(result)

        return {
            'id': self.id,
            'name': self.name,
            'role': self.role,
            'period': period,
            'auto_refresh': self.auto_refresh or 0,
            'activity_state': activity_state,
            'comparison_mode': comparison_mode,
            'kpis': final,
        }

    # ═══════════════════════════════════════════
    # AI Insights (regelbasiert)
    # ═══════════════════════════════════════════

    def _get_ai_insights(self, period='last_30_days'):
        self.ensure_one()
        data = self._get_dashboard_data(period)
        kpis = data.get('kpis', [])
        insights = []

        scorecards = [k for k in kpis
                      if k['display_type'] == 'scorecard' and not k['name'].startswith('_')]

        # 1. Top performer
        improving = sorted(
            [k for k in scorecards if k.get('change_pct', 0) > 5],
            key=lambda k: k['change_pct'], reverse=True)
        if improving:
            top = improving[0]
            insights.append({
                'type': 'positive', 'icon': 'fa-arrow-up',
                'title': _('Strongest Improvement'),
                'text': _(
                    '%(name)s is up %(pct)s%% (currently: %(value)s %(unit)s).',
                    name=top['name'], pct=top['change_pct'],
                    value=top['display_value'], unit=top.get('unit', ''),
                ),
            })

        # 2. Underperformer
        declining = sorted(
            [k for k in scorecards if k.get('change_pct', 0) < -5],
            key=lambda k: k['change_pct'])
        if declining:
            worst = declining[0]
            insights.append({
                'type': 'negative', 'icon': 'fa-arrow-down',
                'title': _('Largest Decline'),
                'text': _(
                    '%(name)s is down %(pct)s%% (currently: %(value)s %(unit)s).',
                    name=worst['name'], pct=abs(worst['change_pct']),
                    value=worst['display_value'], unit=worst.get('unit', ''),
                ),
            })

        # 3. Zielerreichung
        with_targets = [k for k in scorecards if k.get('target_value')]
        if with_targets:
            green = len([k for k in with_targets if k.get('target_status') == 'green'])
            total = len(with_targets)
            pct = round(green / total * 100) if total else 0
            status = 'positive' if pct >= 70 else 'warning' if pct >= 40 else 'negative'
            insights.append({
                'type': status, 'icon': 'fa-bullseye',
                'title': _('Target Achievement'),
                'text': _(
                    '%(green)s of %(total)s KPIs (%(pct)s%%) reached their target.',
                    green=green, total=total, pct=pct,
                ),
            })
            red_kpis = [k for k in with_targets if k.get('target_status') == 'red']
            if red_kpis:
                names = ', '.join(k['name'] for k in red_kpis[:3])
                insights.append({
                    'type': 'negative', 'icon': 'fa-exclamation-triangle',
                    'title': _('Critical KPIs'),
                    'text': _('Below target: %(names)s.', names=names),
                })

        # 4. Overview
        if scorecards:
            up = len([k for k in scorecards if k.get('change_pct', 0) > 0])
            down = len([k for k in scorecards if k.get('change_pct', 0) < 0])
            stable = len(scorecards) - up - down
            insights.append({
                'type': 'info', 'icon': 'fa-info-circle',
                'title': _('Overview'),
                'text': _(
                    '%(count)s KPIs: %(up)s rising, %(down)s falling, %(stable)s stable.',
                    count=len(scorecards), up=up, down=down, stable=stable,
                ),
            })

        # 5. Anomalies (>50% change)
        for k in scorecards:
            if abs(k.get('change_pct', 0)) > 50:
                if k['change_pct'] > 0:
                    text = _(
                        '%(name)s is up %(pct)s%%. This may be worth reviewing.',
                        name=k['name'], pct=abs(k['change_pct']),
                    )
                else:
                    text = _(
                        '%(name)s is down %(pct)s%%. This may be worth reviewing.',
                        name=k['name'], pct=abs(k['change_pct']),
                    )
                insights.append({
                    'type': 'warning', 'icon': 'fa-exclamation-circle',
                    'title': _('Unusual Change'),
                    'text': text,
                })

        if not insights:
            insights.append({
                'type': 'info', 'icon': 'fa-check-circle',
                'title': _('All Clear'),
                'text': _('No notable changes in the current period.'),
            })

        return insights

    # ═══════════════════════════════════════════
    # AI Insights (API-basiert)
    # ═══════════════════════════════════════════

    def _get_real_ai_insights(self, period='last_30_days'):
        """Call Anthropic or OpenAI API with KPI data for intelligent analysis."""
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        api_key = ICP.get_param('executive_dashboard.ai_api_key', '')
        if not api_key:
            return [{'type': 'warning', 'icon': 'fa-key',
                     'title': _('API Key Missing'),
                     'text': _('Add an AI API key (Anthropic or OpenAI) in the '
                               'Dashboard Configuration to enable AI Insights.')}]

        data = self._get_dashboard_data(period)
        kpis = [k for k in data.get('kpis', [])
                if not k['name'].startswith('_')]

        # Build KPI summary for prompt
        kpi_lines = []
        for k in kpis:
            if k['display_type'] == 'scorecard':
                line = f"- {k['name']}: {k['display_value']} {k.get('unit', '')}"
                if k.get('change_pct'):
                    line += f" ({'+' if k['change_pct'] > 0 else ''}{k['change_pct']}% vs. previous period)"
                if k.get('target_value'):
                    line += f" [target: {k['target_value']}, status: {k.get('target_status', '?')}]"
                kpi_lines.append(line)

        kpi_text = '\n'.join(kpi_lines)
        period_label = period.replace('_', ' ')

        # The analysis is written in the reader's language, not a fixed one:
        # `self.env.lang` follows the user's profile language.
        lang_name = self.env['res.lang']._lang_get(self.env.lang or 'en_US').name

        prompt = f"""Analyse the following KPIs from the company dashboard "{data.get('name', '')}" for the period "{period_label}".

KPIs:
{kpi_text}

Give a short, precise analysis written in {lang_name}, covering:
1. The single most important finding (1-2 sentences)
2. Risks or areas needing action (1-2 sentences)
3. A positive highlight (1 sentence)
4. One concrete recommended action (1 sentence)

Respond with a JSON array of objects: {{"type": "positive|negative|warning|info", "icon": "fa-icon-name", "title": "short title", "text": "explanation"}}
Return only the JSON array, no other text."""

        try:
            import requests
            provider = ICP.get_param('executive_dashboard.ai_provider', 'anthropic')

            if provider == 'anthropic':
                resp = requests.post(
                    'https://api.anthropic.com/v1/messages',
                    headers={
                        'x-api-key': api_key,
                        'anthropic-version': '2023-06-01',
                        'content-type': 'application/json',
                    },
                    json={
                        'model': 'claude-sonnet-5',
                        'max_tokens': 1024,
                        # Sonnet 5 thinks by default; thinking and response text
                        # share max_tokens, so leaving it on would risk cutting
                        # the JSON array off mid-array. This is a short,
                        # well-specified generation — no thinking needed.
                        'thinking': {'type': 'disabled'},
                        'messages': [{'role': 'user', 'content': prompt}],
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                content = resp.json()['content'][0]['text']

            else:  # openai
                resp = requests.post(
                    'https://api.openai.com/v1/chat/completions',
                    headers={
                        'Authorization': f'Bearer {api_key}',
                        'Content-Type': 'application/json',
                    },
                    json={
                        'model': 'gpt-4o-mini',
                        'messages': [{'role': 'user', 'content': prompt}],
                        'max_tokens': 1024,
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                content = resp.json()['choices'][0]['message']['content']

            # Parse JSON from response
            content = content.strip()
            if content.startswith('```'):
                content = content.split('\n', 1)[1].rsplit('```', 1)[0]
            insights = json.loads(content)
            if isinstance(insights, list):
                return insights

        except Exception as e:
            _logger.warning("AI Insights API error: %s", e)
            return [{'type': 'negative', 'icon': 'fa-exclamation-triangle',
                     'title': 'AI Fehler',
                     'text': f'API-Anfrage fehlgeschlagen: {str(e)[:200]}'}]

        return [{'type': 'info', 'icon': 'fa-robot',
                 'title': 'Keine Analyse', 'text': 'Die AI konnte keine Analyse generieren.'}]

    @api.model
    def has_ai_key(self):
        return bool(self.env['ir.config_parameter'].sudo().get_param(
            'executive_dashboard.ai_api_key', ''))

    # ═══════════════════════════════════════════
    # Mail Report
    # ═══════════════════════════════════════════

    def action_send_dashboard_mail(self):
        self.ensure_one()
        self._send_dashboard_report()

    def _send_dashboard_report(self):
        self.ensure_one()
        if not self.mail_recipient_ids:
            return
        data = self._get_dashboard_data(self.default_period)
        html = self._render_email_html(data)
        for user in self.mail_recipient_ids:
            if not user.email:
                continue
            try:
                mail = self.env['mail.mail'].sudo().create({
                    'subject': f'Dashboard Report: {self.name} — {date.today().strftime("%d.%m.%Y")}',
                    'body_html': html,
                    'email_to': user.email,
                    'auto_delete': True,
                })
                mail.send()
            except Exception as e:
                _logger.warning("Failed to send dashboard mail to %s: %s", user.email, e)
        self.mail_last_sent = fields.Datetime.now()

    def _render_email_html(self, data):
        kpis = [k for k in data.get('kpis', [])
                if k['display_type'] == 'scorecard' and not k['name'].startswith('_')]
        rows = ""
        for i, kpi in enumerate(kpis):
            bg = "#f8f9fa" if i % 2 == 0 else "#ffffff"
            change = ""
            if kpi.get('show_comparison') and kpi.get('change_pct'):
                pct = kpi['change_pct']
                color = "#059669" if pct > 0 else "#dc2626"
                arrow = "&#8593;" if pct > 0 else "&#8595;"
                change = f'<span style="color:{color};font-size:12px;">{arrow} {pct}%</span>'
            target = ""
            if kpi.get('target_value') and kpi.get('target_status'):
                colors = {'green': '#059669', 'yellow': '#d97706', 'red': '#dc2626'}
                tc = colors.get(kpi['target_status'], '#999')
                target_label = _('Target')
                target = f'<span style="color:{tc};font-size:11px;">&#9679; {target_label}: {kpi["target_value"]}</span>'
            rows += f"""
            <tr style="background:{bg};">
                <td style="padding:10px 14px;font-weight:500;color:#333;">{kpi['name']}</td>
                <td style="padding:10px 14px;text-align:right;font-size:20px;font-weight:700;color:#2d2d2d;">
                    {kpi['display_value']} <span style="font-size:12px;color:#888;">{kpi.get('unit','')}</span>
                </td>
                <td style="padding:10px 14px;text-align:right;">{change}</td>
                <td style="padding:10px 14px;text-align:right;">{target}</td>
            </tr>"""

        return f"""
        <div style="max-width:640px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
            <div style="background:#714B67;padding:20px 24px;border-radius:10px 10px 0 0;">
                <h1 style="color:#fff;font-size:18px;margin:0;">{data.get('name', 'Dashboard')}</h1>
                <p style="color:#e8d5e2;font-size:13px;margin:4px 0 0;">
                    Zeitraum: {data.get('period', '').replace('_', ' ')} &mdash; {date.today().strftime('%d.%m.%Y')}
                </p>
            </div>
            <table style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;border-top:none;">
                <thead>
                    <tr style="background:#f3edf1;">
                        <th style="padding:8px 14px;text-align:left;font-size:11px;text-transform:uppercase;color:#714B67;">KPI</th>
                        <th style="padding:8px 14px;text-align:right;font-size:11px;text-transform:uppercase;color:#714B67;">Wert</th>
                        <th style="padding:8px 14px;text-align:right;font-size:11px;text-transform:uppercase;color:#714B67;">Trend</th>
                        <th style="padding:8px 14px;text-align:right;font-size:11px;text-transform:uppercase;color:#714B67;">Ziel</th>
                    </tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>
            <div style="padding:16px 24px;background:#f8f9fa;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 10px 10px;text-align:center;">
                <p style="color:#888;font-size:11px;margin:0;">
                    Automatischer Report von Executive Dashboard &middot; Odoo 19
                </p>
            </div>
        </div>
        """

    @api.model
    def _cron_send_dashboard_reports(self):
        today = date.today()
        dashboards = self.search([('mail_enabled', '=', True)])
        for db in dashboards:
            should_send = False
            if db.mail_frequency == 'daily':
                should_send = True
            elif db.mail_frequency == 'weekly' and today.weekday() == 0:
                should_send = True
            elif db.mail_frequency == 'monthly' and today.day == 1:
                should_send = True
            if should_send:
                try:
                    db._send_dashboard_report()
                    _logger.info("Dashboard report sent: %s", db.name)
                except Exception as e:
                    _logger.error("Failed to send dashboard report %s: %s", db.name, e)

    # ═══════════════════════════════════════════
    # Branchen-Templates
    # ═══════════════════════════════════════════

    @api.model
    def create_from_template(self, template_key):
        templates = self._get_templates()
        template = next((t for t in templates if t['key'] == template_key), None)
        if not template:
            return {'error': 'Template nicht gefunden'}

        dashboard = self.create({
            'name': template['name'],
            'role': template.get('role', 'custom'),
            'icon': template.get('icon', 'fa-tachometer'),
            'default_period': template.get('default_period', 'last_30_days'),
            'template_key': template_key,
        })

        KPI = self.env['executive.dashboard.kpi']
        for i, kpi_def in enumerate(template.get('kpis', [])):
            vals = dict(kpi_def)
            vals['dashboard_id'] = dashboard.id
            vals['sequence'] = (i + 1) * 10
            KPI.create(vals)

        return {'id': dashboard.id, 'name': dashboard.name}

    @api.model
    def _get_templates(self):
        return [
            {
                'key': 'ecommerce',
                'name': 'E-Commerce',
                'description': 'Online shop KPIs: revenue, orders, AOV, returns, top products',
                'icon': 'fa-shopping-cart',
                'role': 'custom',
                'default_period': 'last_30_days',
                'kpis': [
                    {'name': 'Online Revenue', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'sale.report', 'domain': "[('state', 'not in', ['draft', 'cancel', 'sent'])]",
                     'measure_field': 'price_subtotal', 'aggregate': 'sum', 'unit': 'EUR', 'color': '#EFF6FF',
                     'date_field': 'date'},
                    {'name': 'Orders', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'sale.report', 'domain': "[('state', 'not in', ['draft', 'cancel', 'sent'])]",
                     'measure_field': 'price_subtotal', 'aggregate': 'count', 'color': '#EFF6FF',
                     'date_field': 'date'},
                    {'name': 'AOV', 'display_type': 'scorecard', 'source_type': 'formula',
                     'formula': "kpi('Online Revenue') / kpi('Orders') if kpi('Orders') else 0",
                     'unit': 'EUR', 'color': '#F0FFF4', 'show_comparison': False},
                    {'name': 'Returns', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'stock.picking',
                     'domain': "[('picking_type_code', '=', 'incoming'), ('origin', 'like', 'Return')]",
                     'measure_field': 'id', 'aggregate': 'count', 'color': '#FFF7ED',
                     'date_field': 'date_done'},
                    {'name': 'New Customers', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'res.partner', 'domain': "[('customer_rank', '>', 0)]",
                     'measure_field': 'id', 'aggregate': 'count', 'color': '#F0FFF4',
                     'date_field': 'create_date'},
                    {'name': 'Revenue per Month', 'display_type': 'chart_bar', 'source_type': 'model',
                     'model_name': 'sale.report', 'domain': "[('state', 'not in', ['draft', 'cancel', 'sent'])]",
                     'measure_field': 'price_subtotal', 'aggregate': 'sum', 'group_by': 'date:month',
                     'width': 'full', 'date_field': 'date', 'show_comparison': False},
                    {'name': 'Top Products', 'display_type': 'chart_bar_h', 'source_type': 'model',
                     'model_name': 'sale.report', 'domain': "[('state', 'not in', ['draft', 'cancel', 'sent'])]",
                     'measure_field': 'price_subtotal', 'aggregate': 'sum', 'group_by': 'product_id',
                     'width': 'full', 'date_field': 'date', 'show_comparison': False},
                    {'name': 'Revenue by Country', 'display_type': 'chart_pie', 'source_type': 'model',
                     'model_name': 'sale.report', 'domain': "[('state', 'not in', ['draft', 'cancel', 'sent'])]",
                     'measure_field': 'price_subtotal', 'aggregate': 'sum', 'group_by': 'country_id',
                     'date_field': 'date', 'show_comparison': False},
                ],
            },
            {
                'key': 'dienstleistung',
                'name': 'Services & Consulting',
                'description': 'Project-based KPIs: utilisation, revenue per employee, project margin',
                'icon': 'fa-briefcase',
                'role': 'custom',
                'default_period': 'last_30_days',
                'kpis': [
                    {'name': 'Revenue', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'sale.report', 'domain': "[('state', 'not in', ['draft', 'cancel', 'sent'])]",
                     'measure_field': 'price_subtotal', 'aggregate': 'sum', 'unit': 'EUR', 'color': '#EFF6FF',
                     'date_field': 'date'},
                    {'name': 'Active Projects', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'project.project', 'domain': "[]",
                     'measure_field': 'id', 'aggregate': 'count', 'color': '#F0FFF4',
                     'apply_date_filter': False, 'show_comparison': False},
                    {'name': 'Open Tasks', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'project.task', 'domain': "[('stage_id.fold', '=', False)]",
                     'measure_field': 'id', 'aggregate': 'count', 'color': '#FFF7ED',
                     'date_field': 'create_date'},
                    {'name': 'Employees', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'hr.employee', 'domain': "[('departure_date', '=', False)]",
                     'measure_field': 'id', 'aggregate': 'count', 'color': '#EFF6FF',
                     'apply_date_filter': False, 'show_comparison': False},
                    {'name': 'Pipeline Value', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'crm.lead', 'domain': "[('type', '=', 'opportunity')]",
                     'measure_field': 'prorated_revenue', 'aggregate': 'sum', 'unit': 'EUR', 'color': '#FFF7ED',
                     'date_field': 'create_date'},
                    {'name': 'Invoicing per Month', 'display_type': 'chart_bar', 'source_type': 'model',
                     'model_name': 'account.invoice.report',
                     'domain': "[('move_type', 'in', ['out_invoice', 'out_refund']), ('state', '=', 'posted')]",
                     'measure_field': 'price_subtotal', 'aggregate': 'sum', 'group_by': 'invoice_date:month',
                     'width': 'full', 'date_field': 'invoice_date', 'show_comparison': False},
                    {'name': 'Tasks by Project', 'display_type': 'chart_pie', 'source_type': 'model',
                     'model_name': 'project.task', 'domain': "[]",
                     'measure_field': 'id', 'aggregate': 'count', 'group_by': 'project_id',
                     'date_field': 'create_date', 'show_comparison': False},
                    {'name': 'Team by Department', 'display_type': 'chart_doughnut', 'source_type': 'model',
                     'model_name': 'hr.employee', 'domain': "[('departure_date', '=', False)]",
                     'measure_field': 'id', 'aggregate': 'count', 'group_by': 'department_id',
                     'apply_date_filter': False, 'show_comparison': False},
                ],
            },
            {
                'key': 'produktion',
                'name': 'Production & Manufacturing',
                'description': 'Lager, Einkauf, Lieferungen, Durchlaufzeiten',
                'icon': 'fa-industry',
                'role': 'custom',
                'default_period': 'last_30_days',
                'kpis': [
                    {'name': 'Purchase Volume', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'purchase.report', 'domain': "[('state', 'in', ['purchase', 'done'])]",
                     'measure_field': 'price_total', 'aggregate': 'sum', 'unit': 'EUR', 'color': '#EFF6FF',
                     'date_field': 'date_order'},
                    {'name': 'Deliveries', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'stock.picking',
                     'domain': "[('picking_type_code', '=', 'outgoing'), ('state', '=', 'done')]",
                     'measure_field': 'id', 'aggregate': 'count', 'color': '#F0FFF4',
                     'date_field': 'date_done'},
                    {'name': 'Goods Receipts', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'stock.picking',
                     'domain': "[('picking_type_code', '=', 'incoming'), ('state', '=', 'done')]",
                     'measure_field': 'id', 'aggregate': 'count', 'color': '#FFF7ED',
                     'date_field': 'date_done'},
                    {'name': 'Open Purchase Orders', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'purchase.order', 'domain': "[('state', '=', 'purchase')]",
                     'measure_field': 'id', 'aggregate': 'count', 'color': '#EFF6FF',
                     'apply_date_filter': False, 'show_comparison': False},
                    {'name': 'Purchases per Month', 'display_type': 'chart_bar', 'source_type': 'model',
                     'model_name': 'purchase.report', 'domain': "[('state', 'in', ['purchase', 'done'])]",
                     'measure_field': 'price_total', 'aggregate': 'sum', 'group_by': 'date_order:month',
                     'width': 'full', 'unit': 'EUR', 'date_field': 'date_order', 'show_comparison': False},
                    {'name': 'Deliveries per Month', 'display_type': 'chart_bar', 'source_type': 'model',
                     'model_name': 'stock.picking',
                     'domain': "[('picking_type_code', '=', 'outgoing'), ('state', '=', 'done')]",
                     'measure_field': 'id', 'aggregate': 'count', 'group_by': 'date_done:month',
                     'width': 'full', 'date_field': 'date_done', 'show_comparison': False},
                    {'name': 'Purchases by Vendor', 'display_type': 'chart_pie', 'source_type': 'model',
                     'model_name': 'purchase.report', 'domain': "[('state', 'in', ['purchase', 'done'])]",
                     'measure_field': 'price_total', 'aggregate': 'sum', 'group_by': 'partner_id',
                     'date_field': 'date_order', 'show_comparison': False},
                ],
            },
            {
                'key': 'handel',
                'name': 'Trade & Retail',
                'description': 'Verkauf, Lager, Marge, Kundenstamm',
                'icon': 'fa-shopping-bag',
                'role': 'custom',
                'default_period': 'last_30_days',
                'kpis': [
                    {'name': 'Revenue', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'sale.report', 'domain': "[('state', 'not in', ['draft', 'cancel', 'sent'])]",
                     'measure_field': 'price_subtotal', 'aggregate': 'sum', 'unit': 'EUR', 'color': '#EFF6FF',
                     'date_field': 'date'},
                    {'name': 'Orders', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'sale.report', 'domain': "[('state', 'not in', ['draft', 'cancel', 'sent'])]",
                     'measure_field': 'price_subtotal', 'aggregate': 'count', 'color': '#EFF6FF',
                     'date_field': 'date'},
                    {'name': 'Margin', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'account.invoice.report',
                     'domain': "[('move_type', 'in', ['out_invoice', 'out_refund']), ('state', '=', 'posted')]",
                     'measure_field': 'price_margin', 'aggregate': 'sum', 'unit': 'EUR', 'color': '#F0FFF4',
                     'date_field': 'invoice_date'},
                    {'name': 'Open Receivables', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'account.move',
                     'domain': "[('move_type', '=', 'out_invoice'), ('state', '=', 'posted'), ('payment_state', 'in', ['not_paid', 'partial'])]",
                     'measure_field': 'amount_residual', 'aggregate': 'sum', 'unit': 'EUR', 'color': '#FFF7ED',
                     'apply_date_filter': False, 'show_comparison': False},
                    {'name': 'Customers', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'res.partner', 'domain': "[('customer_rank', '>', 0)]",
                     'measure_field': 'id', 'aggregate': 'count', 'color': '#F0FFF4',
                     'apply_date_filter': False, 'show_comparison': False},
                    {'name': 'Revenue per Month', 'display_type': 'chart_bar', 'source_type': 'model',
                     'model_name': 'sale.report', 'domain': "[('state', 'not in', ['draft', 'cancel', 'sent'])]",
                     'measure_field': 'price_subtotal', 'aggregate': 'sum', 'group_by': 'date:month',
                     'width': 'full', 'date_field': 'date', 'show_comparison': False},
                    {'name': 'Revenue by Product Category', 'display_type': 'chart_doughnut',
                     'source_type': 'model', 'model_name': 'sale.report',
                     'domain': "[('state', 'not in', ['draft', 'cancel', 'sent'])]",
                     'measure_field': 'price_subtotal', 'aggregate': 'sum', 'group_by': 'categ_id',
                     'date_field': 'date', 'show_comparison': False},
                    {'name': 'Payment Status', 'display_type': 'chart_pie', 'source_type': 'model',
                     'model_name': 'account.move',
                     'domain': "[('move_type', '=', 'out_invoice'), ('state', '=', 'posted')]",
                     'measure_field': 'id', 'aggregate': 'count', 'group_by': 'payment_state',
                     'date_field': 'invoice_date', 'show_comparison': False},
                ],
            },
        ]
