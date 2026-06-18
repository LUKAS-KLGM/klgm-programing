import json
import logging
from datetime import date, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ExecutiveDashboard(models.Model):
    _name = 'executive.dashboard'
    _description = 'Executive Dashboard'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    role = fields.Selection([
        ('ceo', 'CEO — Unternehmensübersicht'),
        ('cfo', 'CFO — Finanzen'),
        ('coo', 'COO — Operations'),
        ('cto', 'CTO — Projekte & Team'),
        ('cso', 'CSO — Sales Performance'),
        ('custom', 'Benutzerdefiniert'),
    ], required=True, default='custom')
    color = fields.Integer(default=0)
    icon = fields.Char(default='fa-tachometer')

    kpi_ids = fields.One2many('executive.dashboard.kpi', 'dashboard_id', string='KPIs')
    group_ids = fields.Many2many('res.groups', string='Sichtbar für Gruppen',
        help='Leer = sichtbar für alle internen Benutzer')

    default_period = fields.Selection([
        ('last_7_days', 'Letzte 7 Tage'),
        ('last_30_days', 'Letzte 30 Tage'),
        ('last_90_days', 'Letzte 90 Tage'),
        ('this_month', 'Aktueller Monat'),
        ('this_quarter', 'Aktuelles Quartal'),
        ('this_year', 'Aktuelles Jahr'),
        ('last_year', 'Letztes Jahr'),
    ], default='last_30_days', required=True)

    auto_refresh = fields.Integer(default=0, help='Auto-Refresh in Sekunden. 0 = aus.')

    # ── Mail Report (v5, merged from dashboard_mail.py) ──
    mail_enabled = fields.Boolean('E-Mail-Versand aktiviert', default=False)
    mail_frequency = fields.Selection([
        ('daily', 'Täglich'),
        ('weekly', 'Wöchentlich (Montag)'),
        ('monthly', 'Monatlich (1. des Monats)'),
    ], default='weekly')
    mail_recipient_ids = fields.Many2many(
        'res.users', string='Empfänger',
        help='Benutzer die den Dashboard-Report per E-Mail erhalten')
    mail_last_sent = fields.Datetime('Zuletzt gesendet', readonly=True)

    # ── Comparison Mode (v6) ──
    comparison_mode = fields.Selection([
        ('previous_period', 'Vorperiode'),
        ('previous_year', 'Vorjahr'),
        ('budget', 'Budget'),
    ], default='previous_period')

    # ── Multi-Company (v6) ──
    company_id = fields.Many2one('res.company', string='Unternehmen',
        default=lambda self: self.env.company)

    # ── Template origin ──
    template_key = fields.Char(readonly=True, help='Interner Schlüssel des Branchen-Templates')

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
                kpi_cache[kpi.name] = result['value']
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
                'title': 'Stärkste Verbesserung',
                'text': f"{top['name']} ist um {top['change_pct']}% gestiegen "
                        f"(aktuell: {top['display_value']} {top.get('unit', '')}).",
            })

        # 2. Underperformer
        declining = sorted(
            [k for k in scorecards if k.get('change_pct', 0) < -5],
            key=lambda k: k['change_pct'])
        if declining:
            worst = declining[0]
            insights.append({
                'type': 'negative', 'icon': 'fa-arrow-down',
                'title': 'Stärkster Rückgang',
                'text': f"{worst['name']} ist um {abs(worst['change_pct'])}% gefallen "
                        f"(aktuell: {worst['display_value']} {worst.get('unit', '')}).",
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
                'title': 'Zielerreichung',
                'text': f"{green} von {total} KPIs ({pct}%) haben ihr Ziel erreicht.",
            })
            red_kpis = [k for k in with_targets if k.get('target_status') == 'red']
            if red_kpis:
                names = ', '.join(k['name'] for k in red_kpis[:3])
                insights.append({
                    'type': 'negative', 'icon': 'fa-exclamation-triangle',
                    'title': 'Kritische KPIs',
                    'text': f"Unter Ziel: {names}.",
                })

        # 4. Übersicht
        if scorecards:
            up = len([k for k in scorecards if k.get('change_pct', 0) > 0])
            down = len([k for k in scorecards if k.get('change_pct', 0) < 0])
            stable = len(scorecards) - up - down
            insights.append({
                'type': 'info', 'icon': 'fa-info-circle',
                'title': 'Übersicht',
                'text': f"{len(scorecards)} KPIs: {up} steigend, {down} fallend, {stable} stabil.",
            })

        # 5. Anomalien (>50% Veränderung)
        for k in scorecards:
            if abs(k.get('change_pct', 0)) > 50:
                direction = 'gestiegen' if k['change_pct'] > 0 else 'gefallen'
                insights.append({
                    'type': 'warning', 'icon': 'fa-exclamation-circle',
                    'title': 'Ungewöhnliche Veränderung',
                    'text': f"{k['name']} ist um {abs(k['change_pct'])}% {direction}. "
                            f"Das könnte überprüft werden.",
                })

        if not insights:
            insights.append({
                'type': 'info', 'icon': 'fa-check-circle',
                'title': 'Alles im grünen Bereich',
                'text': 'Keine auffälligen Veränderungen im aktuellen Zeitraum.',
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
                     'title': 'API Key fehlt',
                     'text': 'Bitte hinterlege einen AI API Key in der Dashboard-Konfiguration '
                             '(Anthropic oder OpenAI).'}]

        data = self._get_dashboard_data(period)
        kpis = [k for k in data.get('kpis', [])
                if not k['name'].startswith('_')]

        # Build KPI summary for prompt
        kpi_lines = []
        for k in kpis:
            if k['display_type'] == 'scorecard':
                line = f"- {k['name']}: {k['display_value']} {k.get('unit', '')}"
                if k.get('change_pct'):
                    line += f" ({'+' if k['change_pct'] > 0 else ''}{k['change_pct']}% vs. Vorperiode)"
                if k.get('target_value'):
                    line += f" [Ziel: {k['target_value']}, Status: {k.get('target_status', '?')}]"
                kpi_lines.append(line)

        kpi_text = '\n'.join(kpi_lines)
        period_label = period.replace('_', ' ')

        prompt = f"""Analysiere die folgenden KPIs eines Unternehmens-Dashboards "{data.get('name', '')}" für den Zeitraum "{period_label}".

KPIs:
{kpi_text}

Gib eine kurze, prägnante Analyse auf Deutsch mit:
1. Die wichtigste Erkenntnis (1-2 Sätze)
2. Risiken oder Handlungsbedarf (1-2 Sätze)
3. Positives Highlight (1 Satz)
4. Konkreter Handlungsvorschlag (1 Satz)

Antworte als JSON-Array mit Objects: {{"type": "positive|negative|warning|info", "icon": "fa-icon-name", "title": "Kurztitel", "text": "Erklärung"}}
Nur das JSON-Array, kein anderer Text."""

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
                        'model': 'claude-sonnet-4-20250514',
                        'max_tokens': 1024,
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
                target = f'<span style="color:{tc};font-size:11px;">&#9679; Ziel: {kpi["target_value"]}</span>'
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
                    Automatischer Report von Controlling Dashboard &middot; Odoo 19
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
                'description': 'Online-Shop KPIs: Umsatz, Bestellungen, AOV, Retouren, Top-Produkte',
                'icon': 'fa-shopping-cart',
                'role': 'custom',
                'default_period': 'last_30_days',
                'kpis': [
                    {'name': 'Online-Umsatz', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'sale.report', 'domain': "[('state', 'not in', ['draft', 'cancel', 'sent'])]",
                     'measure_field': 'price_subtotal', 'aggregate': 'sum', 'unit': 'EUR', 'color': '#EFF6FF',
                     'date_field': 'date'},
                    {'name': 'Bestellungen', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'sale.report', 'domain': "[('state', 'not in', ['draft', 'cancel', 'sent'])]",
                     'measure_field': 'price_subtotal', 'aggregate': 'count', 'color': '#EFF6FF',
                     'date_field': 'date'},
                    {'name': 'AOV', 'display_type': 'scorecard', 'source_type': 'formula',
                     'formula': "kpi('Online-Umsatz') / kpi('Bestellungen') if kpi('Bestellungen') else 0",
                     'unit': 'EUR', 'color': '#F0FFF4', 'show_comparison': False},
                    {'name': 'Retouren', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'stock.picking',
                     'domain': "[('picking_type_code', '=', 'incoming'), ('origin', 'like', 'Return')]",
                     'measure_field': 'id', 'aggregate': 'count', 'color': '#FFF7ED',
                     'date_field': 'date_done'},
                    {'name': 'Neue Kunden', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'res.partner', 'domain': "[('customer_rank', '>', 0)]",
                     'measure_field': 'id', 'aggregate': 'count', 'color': '#F0FFF4',
                     'date_field': 'create_date'},
                    {'name': 'Umsatz pro Monat', 'display_type': 'chart_bar', 'source_type': 'model',
                     'model_name': 'sale.report', 'domain': "[('state', 'not in', ['draft', 'cancel', 'sent'])]",
                     'measure_field': 'price_subtotal', 'aggregate': 'sum', 'group_by': 'date:month',
                     'width': 'full', 'date_field': 'date', 'show_comparison': False},
                    {'name': 'Top-Produkte', 'display_type': 'chart_bar_h', 'source_type': 'model',
                     'model_name': 'sale.report', 'domain': "[('state', 'not in', ['draft', 'cancel', 'sent'])]",
                     'measure_field': 'price_subtotal', 'aggregate': 'sum', 'group_by': 'product_id',
                     'width': 'full', 'date_field': 'date', 'show_comparison': False},
                    {'name': 'Umsatz nach Land', 'display_type': 'chart_pie', 'source_type': 'model',
                     'model_name': 'sale.report', 'domain': "[('state', 'not in', ['draft', 'cancel', 'sent'])]",
                     'measure_field': 'price_subtotal', 'aggregate': 'sum', 'group_by': 'country_id',
                     'date_field': 'date', 'show_comparison': False},
                ],
            },
            {
                'key': 'dienstleistung',
                'name': 'Dienstleistung & Beratung',
                'description': 'Projektbasierte KPIs: Auslastung, Umsatz/MA, Projektmarge',
                'icon': 'fa-briefcase',
                'role': 'custom',
                'default_period': 'last_30_days',
                'kpis': [
                    {'name': 'Umsatz', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'sale.report', 'domain': "[('state', 'not in', ['draft', 'cancel', 'sent'])]",
                     'measure_field': 'price_subtotal', 'aggregate': 'sum', 'unit': 'EUR', 'color': '#EFF6FF',
                     'date_field': 'date'},
                    {'name': 'Aktive Projekte', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'project.project', 'domain': "[]",
                     'measure_field': 'id', 'aggregate': 'count', 'color': '#F0FFF4',
                     'apply_date_filter': False, 'show_comparison': False},
                    {'name': 'Offene Aufgaben', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'project.task', 'domain': "[('stage_id.fold', '=', False)]",
                     'measure_field': 'id', 'aggregate': 'count', 'color': '#FFF7ED',
                     'date_field': 'create_date'},
                    {'name': 'Mitarbeiter', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'hr.employee', 'domain': "[('departure_date', '=', False)]",
                     'measure_field': 'id', 'aggregate': 'count', 'color': '#EFF6FF',
                     'apply_date_filter': False, 'show_comparison': False},
                    {'name': 'Pipeline-Wert', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'crm.lead', 'domain': "[('type', '=', 'opportunity')]",
                     'measure_field': 'prorated_revenue', 'aggregate': 'sum', 'unit': 'EUR', 'color': '#FFF7ED',
                     'date_field': 'create_date'},
                    {'name': 'Fakturierung pro Monat', 'display_type': 'chart_bar', 'source_type': 'model',
                     'model_name': 'account.invoice.report',
                     'domain': "[('move_type', 'in', ['out_invoice', 'out_refund']), ('state', '=', 'posted')]",
                     'measure_field': 'price_subtotal', 'aggregate': 'sum', 'group_by': 'invoice_date:month',
                     'width': 'full', 'date_field': 'invoice_date', 'show_comparison': False},
                    {'name': 'Aufgaben nach Projekt', 'display_type': 'chart_pie', 'source_type': 'model',
                     'model_name': 'project.task', 'domain': "[]",
                     'measure_field': 'id', 'aggregate': 'count', 'group_by': 'project_id',
                     'date_field': 'create_date', 'show_comparison': False},
                    {'name': 'Team nach Abteilung', 'display_type': 'chart_doughnut', 'source_type': 'model',
                     'model_name': 'hr.employee', 'domain': "[('departure_date', '=', False)]",
                     'measure_field': 'id', 'aggregate': 'count', 'group_by': 'department_id',
                     'apply_date_filter': False, 'show_comparison': False},
                ],
            },
            {
                'key': 'produktion',
                'name': 'Produktion & Fertigung',
                'description': 'Lager, Einkauf, Lieferungen, Durchlaufzeiten',
                'icon': 'fa-industry',
                'role': 'custom',
                'default_period': 'last_30_days',
                'kpis': [
                    {'name': 'Einkaufsvolumen', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'purchase.report', 'domain': "[('state', 'in', ['purchase', 'done'])]",
                     'measure_field': 'price_total', 'aggregate': 'sum', 'unit': 'EUR', 'color': '#EFF6FF',
                     'date_field': 'date_order'},
                    {'name': 'Lieferungen', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'stock.picking',
                     'domain': "[('picking_type_code', '=', 'outgoing'), ('state', '=', 'done')]",
                     'measure_field': 'id', 'aggregate': 'count', 'color': '#F0FFF4',
                     'date_field': 'date_done'},
                    {'name': 'Wareneingänge', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'stock.picking',
                     'domain': "[('picking_type_code', '=', 'incoming'), ('state', '=', 'done')]",
                     'measure_field': 'id', 'aggregate': 'count', 'color': '#FFF7ED',
                     'date_field': 'date_done'},
                    {'name': 'Offene Bestellungen', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'purchase.order', 'domain': "[('state', '=', 'purchase')]",
                     'measure_field': 'id', 'aggregate': 'count', 'color': '#EFF6FF',
                     'apply_date_filter': False, 'show_comparison': False},
                    {'name': 'Einkauf pro Monat', 'display_type': 'chart_bar', 'source_type': 'model',
                     'model_name': 'purchase.report', 'domain': "[('state', 'in', ['purchase', 'done'])]",
                     'measure_field': 'price_total', 'aggregate': 'sum', 'group_by': 'date_order:month',
                     'width': 'full', 'unit': 'EUR', 'date_field': 'date_order', 'show_comparison': False},
                    {'name': 'Lieferungen pro Monat', 'display_type': 'chart_bar', 'source_type': 'model',
                     'model_name': 'stock.picking',
                     'domain': "[('picking_type_code', '=', 'outgoing'), ('state', '=', 'done')]",
                     'measure_field': 'id', 'aggregate': 'count', 'group_by': 'date_done:month',
                     'width': 'full', 'date_field': 'date_done', 'show_comparison': False},
                    {'name': 'Einkauf nach Lieferant', 'display_type': 'chart_pie', 'source_type': 'model',
                     'model_name': 'purchase.report', 'domain': "[('state', 'in', ['purchase', 'done'])]",
                     'measure_field': 'price_total', 'aggregate': 'sum', 'group_by': 'partner_id',
                     'date_field': 'date_order', 'show_comparison': False},
                ],
            },
            {
                'key': 'handel',
                'name': 'Handel & Retail',
                'description': 'Verkauf, Lager, Marge, Kundenstamm',
                'icon': 'fa-shopping-bag',
                'role': 'custom',
                'default_period': 'last_30_days',
                'kpis': [
                    {'name': 'Umsatz', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'sale.report', 'domain': "[('state', 'not in', ['draft', 'cancel', 'sent'])]",
                     'measure_field': 'price_subtotal', 'aggregate': 'sum', 'unit': 'EUR', 'color': '#EFF6FF',
                     'date_field': 'date'},
                    {'name': 'Bestellungen', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'sale.report', 'domain': "[('state', 'not in', ['draft', 'cancel', 'sent'])]",
                     'measure_field': 'price_subtotal', 'aggregate': 'count', 'color': '#EFF6FF',
                     'date_field': 'date'},
                    {'name': 'Marge', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'account.invoice.report',
                     'domain': "[('move_type', 'in', ['out_invoice', 'out_refund']), ('state', '=', 'posted')]",
                     'measure_field': 'price_margin', 'aggregate': 'sum', 'unit': 'EUR', 'color': '#F0FFF4',
                     'date_field': 'invoice_date'},
                    {'name': 'Offene Forderungen', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'account.move',
                     'domain': "[('move_type', '=', 'out_invoice'), ('state', '=', 'posted'), ('payment_state', 'in', ['not_paid', 'partial'])]",
                     'measure_field': 'amount_residual', 'aggregate': 'sum', 'unit': 'EUR', 'color': '#FFF7ED',
                     'apply_date_filter': False, 'show_comparison': False},
                    {'name': 'Kunden', 'display_type': 'scorecard', 'source_type': 'model',
                     'model_name': 'res.partner', 'domain': "[('customer_rank', '>', 0)]",
                     'measure_field': 'id', 'aggregate': 'count', 'color': '#F0FFF4',
                     'apply_date_filter': False, 'show_comparison': False},
                    {'name': 'Umsatz pro Monat', 'display_type': 'chart_bar', 'source_type': 'model',
                     'model_name': 'sale.report', 'domain': "[('state', 'not in', ['draft', 'cancel', 'sent'])]",
                     'measure_field': 'price_subtotal', 'aggregate': 'sum', 'group_by': 'date:month',
                     'width': 'full', 'date_field': 'date', 'show_comparison': False},
                    {'name': 'Umsatz nach Produktkategorie', 'display_type': 'chart_doughnut',
                     'source_type': 'model', 'model_name': 'sale.report',
                     'domain': "[('state', 'not in', ['draft', 'cancel', 'sent'])]",
                     'measure_field': 'price_subtotal', 'aggregate': 'sum', 'group_by': 'categ_id',
                     'date_field': 'date', 'show_comparison': False},
                    {'name': 'Zahlungsstatus', 'display_type': 'chart_pie', 'source_type': 'model',
                     'model_name': 'account.move',
                     'domain': "[('move_type', '=', 'out_invoice'), ('state', '=', 'posted')]",
                     'measure_field': 'id', 'aggregate': 'count', 'group_by': 'payment_state',
                     'date_field': 'invoice_date', 'show_comparison': False},
                ],
            },
        ]
