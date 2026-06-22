import logging
from datetime import date, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class DashboardKPI(models.Model):
    _name = 'executive.dashboard.kpi'
    _description = 'Dashboard KPI'
    _order = 'sequence, id'

    dashboard_id = fields.Many2one('executive.dashboard', required=True, ondelete='cascade')
    name = fields.Char(required=True)
    description = fields.Char(help='Kurze Erklärung des KPIs für Tooltip')
    sequence = fields.Integer(default=10)

    # Display
    display_type = fields.Selection([
        ('scorecard', 'Scorecard (KPI-Karte)'),
        ('chart_bar', 'Balkendiagramm'),
        ('chart_bar_h', 'Balkendiagramm (horizontal)'),
        ('chart_line', 'Liniendiagramm'),
        ('chart_pie', 'Tortendiagramm'),
        ('chart_doughnut', 'Ringdiagramm'),
        ('chart_table', 'Tabelle'),
        ('chart_gauge', 'Gauge (Tacho)'),
    ], required=True, default='scorecard')
    unit = fields.Char(help='z.B. EUR, %, Stk.')
    color = fields.Char(default='#EFF6FF', help='Hintergrundfarbe der Scorecard')
    width = fields.Selection([
        ('third', 'Drittel'),
        ('half', 'Halbe Breite'),
        ('two_thirds', 'Zwei Drittel'),
        ('full', 'Volle Breite'),
    ], default='half')

    # Data source
    source_type = fields.Selection([
        ('model', 'Odoo Model (Aggregation)'),
        ('formula', 'Berechnet (Formel)'),
        ('sql', 'SQL Query'),
        ('bank_balance', 'Kontostand (Bankjournal)'),
    ], required=True, default='model')

    # For source_type = 'model'
    model_name = fields.Char(help='z.B. sale.report, account.move')
    domain = fields.Text(default='[]', help='Odoo Domain als Python-Liste')
    measure_field = fields.Char(help='Feld zum Aggregieren, z.B. price_subtotal')
    aggregate = fields.Selection([
        ('sum', 'Summe'),
        ('avg', 'Durchschnitt'),
        ('count', 'Anzahl'),
        ('min', 'Minimum'),
        ('max', 'Maximum'),
    ], default='sum')
    group_by = fields.Char(help='Gruppierung für Charts, z.B. date:month')

    # For source_type = 'formula'
    formula = fields.Text(help='Python-Ausdruck. Verfügbar: kpi(name) für andere KPI-Werte.')

    # For source_type = 'sql'
    sql_query = fields.Text(help='SQL SELECT der einen einzelnen Wert liefert. '
                                 'Platzhalter: {date_from}, {date_to} für Zeitfilter.')

    # For source_type = 'bank_balance'
    journal_id = fields.Many2one('account.journal', string='Bankjournal',
        domain="[('type', '=', 'bank')]",
        help='Bankjournal für Kontostand. Leer = erstes Bankjournal.')

    # Comparison
    show_comparison = fields.Boolean(default=True)

    # Drill-down
    action_xmlid = fields.Char(help='z.B. sale.action_order_report_all')

    # Date field for filtering
    date_field = fields.Char(default='date', help='Datumsfeld für Zeitfilter')
    apply_date_filter = fields.Boolean(default=True, help='False für Bestandswerte wie Mitarbeiter.')

    # Target / Ampel (v3)
    target_value = fields.Float(help='Zielwert für Ampel-Anzeige')
    target_warning = fields.Float(help='Schwelle für Gelb (z.B. 80% des Ziels)')
    target_critical = fields.Float(help='Schwelle für Rot (z.B. 50% des Ziels)')

    # Budget (v6)
    budget_value = fields.Float(help='Budget-Wert für Vergleich')

    # Notes (v6)
    note_ids = fields.One2many('executive.dashboard.kpi.note', 'kpi_id', string='Notizen')

    # ═══════════════════════════════════════════
    # Date Ranges
    # ═══════════════════════════════════════════

    def _get_date_range(self, period):
        today = date.today()
        if period == 'all_time':
            # Ältesten Eintrag der DB ermitteln (res.company create_date)
            oldest = self.env['res.company'].sudo().search([], order='create_date asc', limit=1)
            start = oldest.create_date.date() if oldest and oldest.create_date else date(2000, 1, 1)
            return (start, today)
        if period and period.startswith('custom:'):
            try:
                parts = period.split(':')[1].split(',')
                return (date.fromisoformat(parts[0]), date.fromisoformat(parts[1]))
            except (IndexError, ValueError):
                pass
        ranges = {
            'last_7_days': (today - timedelta(days=7), today),
            'last_30_days': (today - timedelta(days=30), today),
            'last_90_days': (today - timedelta(days=90), today),
            'this_month': (today.replace(day=1), today),
            'this_quarter': (today.replace(month=((today.month - 1) // 3) * 3 + 1, day=1), today),
            'this_year': (today.replace(month=1, day=1), today),
            'last_year': (today.replace(year=today.year - 1, month=1, day=1),
                          today.replace(year=today.year - 1, month=12, day=31)),
        }
        return ranges.get(period, (today - timedelta(days=30), today))

    def _get_previous_range(self, date_from, date_to):
        delta = date_to - date_from
        return date_from - delta - timedelta(days=1), date_from - timedelta(days=1)

    def _get_previous_year_range(self, date_from, date_to):
        return (date_from.replace(year=date_from.year - 1),
                date_to.replace(year=date_to.year - 1))

    # ═══════════════════════════════════════════
    # Model Aggregation
    # ═══════════════════════════════════════════

    # ═══════════════════════════════════════════
    # Activity Summary Integration
    # ═══════════════════════════════════════════

    def _use_activity_summary(self):
        """Check if partner_activity_history module is installed."""
        return 'activity.summary' in self.env

    def _map_activity_domain(self, domain):
        """Map mail.activity domain fields to activity.summary fields."""
        mapped = []
        for leaf in domain:
            if isinstance(leaf, str):
                mapped.append(leaf)
                continue
            field, op, val = leaf
            if field == 'activity_type_id.category':
                # category phonecall → activity_type ilike 'Anruf' or 'Call'
                if val == 'phonecall':
                    mapped.append('|')
                    mapped.append(('activity_type', 'ilike', 'Anruf'))
                    mapped.append(('activity_type', 'ilike', 'Call'))
                elif val == 'meeting':
                    mapped.append('|')
                    mapped.append(('activity_type', 'ilike', 'Meeting'))
                    mapped.append(('activity_type', 'ilike', 'Besprechung'))
                else:
                    mapped.append(('activity_type', 'ilike', val))
            elif field == 'activity_type_id.name':
                mapped.append(('activity_type', op, val))
            elif field == 'user_id':
                mapped.append(('user_name', op, val))
            elif field == 'date_deadline':
                mapped.append(('activity_date', op, val))
            else:
                mapped.append(leaf)
        return mapped

    # ═══════════════════════════════════════════
    # Model Aggregation
    # ═══════════════════════════════════════════

    def _aggregate_model(self, period, activity_state='all', comparison_mode='previous_period'):
        self.ensure_one()
        if not self.model_name or not self.measure_field:
            return {'value': 0, 'previous': 0, 'chart_data': [], 'sparkline': []}

        # Transparent upgrade: use activity.summary if available
        effective_model = self.model_name
        effective_date_field = self.date_field
        effective_group_by = self.group_by
        if self.model_name == 'mail.activity' and self._use_activity_summary():
            effective_model = 'activity.summary'
            effective_date_field = 'activity_date'
            if self.group_by == 'user_id':
                effective_group_by = 'user_name'
            elif self.group_by == 'activity_type_id':
                effective_group_by = 'activity_type'

        try:
            Model = self.env[effective_model]
        except KeyError:
            _logger.warning("Model %s not found for KPI %s", effective_model, self.name)
            return {'value': 0, 'previous': 0, 'chart_data': [], 'sparkline': []}

        base_domain = eval(self.domain or '[]')

        # Map domain fields if using activity.summary
        if effective_model == 'activity.summary':
            base_domain = self._map_activity_domain(base_domain)

        # Activity state filter
        if effective_model == 'activity.summary' and activity_state != 'all':
            if activity_state == 'done':
                base_domain = base_domain + [('state', '=', 'done')]
            elif activity_state == 'planned':
                base_domain = base_domain + [('state', 'in', ['planned', 'today', 'overdue'])]
        elif self.model_name == 'mail.activity' and activity_state != 'all':
            if activity_state == 'done':
                base_domain = base_domain + [('date_done', '!=', False)]
            elif activity_state == 'planned':
                base_domain = base_domain + [('date_done', '=', False)]

        date_from, date_to = self._get_date_range(period)

        # Current period
        current_domain = list(base_domain)
        # hr.employee: count staff active during the period
        # Prefer contract_date_start (Einstelldatum), fallback chain
        if self.model_name == 'hr.employee':
            emp_start = 'create_date'
            for f in ('contract_date_start', 'first_contract_date'):
                if f in Model._fields:
                    emp_start = f
                    break
            current_domain = [
                '|', (emp_start, '=', False), (emp_start, '<=', str(date_to)),
                '|', ('departure_date', '=', False), ('departure_date', '>=', str(date_from)),
            ]
        elif self.apply_date_filter and effective_date_field:
            current_domain += [
                (effective_date_field, '>=', str(date_from)),
                (effective_date_field, '<=', str(date_to)),
            ]

        if self.aggregate == 'count':
            value = Model.search_count(current_domain)
        else:
            results = Model.read_group(current_domain, [self.measure_field], [], limit=1)
            value = (results[0].get(self.measure_field, 0) or 0) if results else 0

        # Previous period (depending on comparison mode)
        # Skip comparison for all_time — no meaningful previous period
        previous = 0
        can_compare = (self.apply_date_filter or self.model_name == 'hr.employee')
        if self.show_comparison and can_compare and period != 'all_time':
            if comparison_mode == 'budget' and self.budget_value:
                previous = self.budget_value
            else:
                if comparison_mode == 'previous_year':
                    prev_from, prev_to = self._get_previous_year_range(date_from, date_to)
                else:
                    prev_from, prev_to = self._get_previous_range(date_from, date_to)

                prev_domain = list(base_domain)
                if self.model_name == 'hr.employee':
                    emp_start = 'create_date'
                    for f in ('contract_date_start', 'first_contract_date'):
                        if f in Model._fields:
                            emp_start = f
                            break
                    prev_domain = [
                        '|', (emp_start, '=', False), (emp_start, '<=', str(prev_to)),
                        '|', ('departure_date', '=', False), ('departure_date', '>=', str(prev_from)),
                    ]
                elif effective_date_field:
                    prev_domain += [
                        (effective_date_field, '>=', str(prev_from)),
                        (effective_date_field, '<=', str(prev_to)),
                    ]
                if self.aggregate == 'count':
                    previous = Model.search_count(prev_domain)
                else:
                    results = Model.read_group(prev_domain, [self.measure_field], [], limit=1)
                    previous = (results[0].get(self.measure_field, 0) or 0) if results else 0

        # Chart data (grouped) — limit 10 for top charts, sort by value desc for bar/pie
        chart_data = []
        chart_group = effective_group_by or self.group_by
        is_time_group = ':' in (chart_group or '')
        if self.display_type.startswith('chart_') and self.display_type != 'chart_gauge' and chart_group:
            try:
                # For all_time with monthly grouping, switch to quarterly
                if period == 'all_time' and chart_group.endswith(':month'):
                    chart_group = chart_group.replace(':month', ':quarter')
                order = chart_group if is_time_group else f'{self.measure_field} desc'
                time_limit = 60 if period == 'all_time' else 30
                group_results = Model.read_group(
                    current_domain, [self.measure_field], [chart_group],
                    orderby=order, limit=10 if not is_time_group else time_limit,
                )
                for r in group_results:
                    label = r.get(chart_group, 'Sonstige')
                    if isinstance(label, (list, tuple)):
                        label = label[1] if len(label) > 1 else label[0]
                    elif label is False:
                        label = 'Sonstige'
                    val = r.get(self.measure_field, 0) or 0
                    count = r.get(f'{chart_group}_count', r.get('__count', 0))
                    chart_data.append({
                        'label': str(label),
                        'value': val if self.aggregate != 'count' else count,
                    })
            except Exception as e:
                _logger.warning("Chart group_by error for KPI %s: %s", self.name, e)

        # Sparkline data
        sparkline = []
        if self.display_type == 'scorecard':
            try:
                if self.model_name == 'hr.employee':
                    # Monthly headcount snapshots
                    from dateutil.relativedelta import relativedelta
                    emp_start = 'create_date'
                    for f in ('contract_date_start', 'first_contract_date'):
                        if f in Model._fields:
                            emp_start = f
                            break
                    cur = date_from.replace(day=1)
                    while cur <= date_to:
                        month_end = (cur + relativedelta(months=1)) - timedelta(days=1)
                        cnt = Model.search_count([
                            '|', (emp_start, '=', False), (emp_start, '<=', str(month_end)),
                            '|', ('departure_date', '=', False), ('departure_date', '>=', str(cur)),
                        ])
                        sparkline.append(cnt)
                        cur += relativedelta(months=1)
                    sparkline = sparkline[-14:]
                elif self.apply_date_filter and effective_date_field:
                    delta = (date_to - date_from).days
                    spark_group = effective_date_field + (':week' if delta > 14 else ':day')
                    spark_results = Model.read_group(
                        current_domain, [self.measure_field], [spark_group],
                        orderby=spark_group, limit=30,
                    )
                    for r in spark_results:
                        val = r.get(self.measure_field, 0) or 0
                        count = r.get(f'{spark_group}_count', r.get('__count', 0))
                        sparkline.append(val if self.aggregate != 'count' else count)
                    sparkline = sparkline[-14:]
            except Exception:
                sparkline = []

        return {'value': value, 'previous': previous, 'chart_data': chart_data, 'sparkline': sparkline}

    # ═══════════════════════════════════════════
    # Bank Balance
    # ═══════════════════════════════════════════

    def _compute_bank_balance(self):
        """Get the posted balance of a bank journal from account.move.line."""
        self.ensure_one()
        journal = None

        # 1. KPI-level journal_id
        if self.journal_id:
            journal = self.journal_id

        # 2. Global setting from Controlling → Einstellungen
        if not journal:
            ICP = self.env['ir.config_parameter'].sudo()
            j_str = ICP.get_param('executive_dashboard.bank_journal_id', '0') or '0'
            try:
                j_id = int(j_str)
            except (ValueError, TypeError):
                j_id = 0
            if j_id:
                j = self.env['account.journal'].sudo().browse(j_id)
                if j.exists():
                    journal = j

        # 3. Fallback: first bank journal
        if not journal:
            journal = self.env['account.journal'].sudo().search(
                [('type', '=', 'bank')], order='sequence, id', limit=1)

        if not journal:
            _logger.warning("Kontostand KPI: Kein Bankjournal gefunden")
            return 0

        _logger.info("Kontostand KPI: Verwende Journal %s (ID %s)", journal.name, journal.id)
        self.env.cr.execute("""
            SELECT COALESCE(SUM(aml.balance), 0)
            FROM account_move_line aml
            JOIN account_move am ON am.id = aml.move_id
            WHERE aml.journal_id = %s
              AND am.state = 'posted'
        """, (journal.id,))
        row = self.env.cr.fetchone()
        val = row[0] if row else 0
        _logger.info("Kontostand KPI: Saldo = %s", val)
        return val

    # ═══════════════════════════════════════════
    # SQL Query
    # ═══════════════════════════════════════════

    def _execute_sql(self, period):
        """Execute a raw SQL query with date placeholders."""
        self.ensure_one()
        if not self.sql_query:
            return 0
        date_from, date_to = self._get_date_range(period)
        query = self.sql_query.format(
            date_from=str(date_from),
            date_to=str(date_to),
        )
        try:
            self.env.cr.execute(query)
            row = self.env.cr.fetchone()
            return row[0] if row and row[0] is not None else 0
        except Exception as e:
            _logger.warning("SQL KPI error for %s: %s", self.name, e)
            return 0

    # ═══════════════════════════════════════════
    # Compute Value
    # ═══════════════════════════════════════════

    def _compute_value(self, period, kpi_cache=None, activity_state='all',
                       comparison_mode='previous_period'):
        self.ensure_one()
        result = {
            'id': self.id,
            'name': self.name,
            'display_type': self.display_type,
            'unit': self.unit or '',
            'color': self.color or '#EFF6FF',
            'width': self.width or 'half',
            'show_comparison': self.show_comparison,
            'action_xmlid': self.action_xmlid or '',
            'value': 0,
            'previous': 0,
            'change_pct': 0,
            'chart_data': [],
            'sparkline': [],
            'target_value': self.target_value or 0,
            'target_status': '',
            'budget_value': self.budget_value or 0,
            'description': self.description or '',
            'note_count': len(self.note_ids),
            'comparison_mode': comparison_mode,
        }

        # Auto-redirect: old bank statement KPIs → bank_balance logic
        effective_source = self.source_type
        if self.source_type == 'model' and self.model_name == 'account.bank.statement.line':
            effective_source = 'bank_balance'

        if effective_source == 'model':
            data = self._aggregate_model(period, activity_state=activity_state,
                                         comparison_mode=comparison_mode)
            result['value'] = data['value']
            result['previous'] = data['previous']
            result['chart_data'] = data['chart_data']
            result['sparkline'] = data.get('sparkline', [])

        elif effective_source == 'sql':
            result['value'] = self._execute_sql(period)

        elif effective_source == 'bank_balance':
            result['value'] = self._compute_bank_balance()

        elif effective_source == 'formula':
            if kpi_cache is None:
                kpi_cache = {}
                for other in self.dashboard_id.kpi_ids:
                    if other.id != self.id and other.source_type == 'model':
                        kpi_cache[other.name] = other._aggregate_model(period)['value']

            def kpi(name):
                return kpi_cache.get(name, 0)

            try:
                result['value'] = eval(self.formula, {'kpi': kpi, '__builtins__': {}})
            except Exception as e:
                _logger.warning("KPI formula error for %s: %s", self.name, e)
                result['value'] = 0

        # Change percentage (capped at +/-999%)
        prev = result['previous']
        if comparison_mode == 'budget' and self.budget_value:
            prev = self.budget_value
            result['previous'] = prev

        if prev and prev != 0:
            pct = (result['value'] - prev) / abs(prev) * 100
            result['change_pct'] = round(max(-999, min(999, pct)), 1)

        # Comparison label
        labels = {
            'previous_period': 'vs. Vorperiode',
            'previous_year': 'vs. Vorjahr',
            'budget': 'vs. Budget',
        }
        result['comparison_label'] = labels.get(comparison_mode, 'vs. Vorperiode')

        # Target / Ampel
        if self.target_value:
            val = result['value']
            if val >= self.target_value:
                result['target_status'] = 'green'
            elif self.target_warning and val >= self.target_warning:
                result['target_status'] = 'yellow'
            elif self.target_critical and val < self.target_critical:
                result['target_status'] = 'red'
            else:
                result['target_status'] = 'yellow'

        # Format
        result['display_value'] = self._format_value(result['value'])
        result['display_previous'] = self._format_value(result['previous'])

        return result

    def _format_value(self, value):
        if not value:
            return '0'
        if isinstance(value, float) and value == int(value):
            value = int(value)

        abs_val = abs(value)
        sign = '-' if value < 0 else ''

        if abs_val >= 1_000_000:
            return f'{sign}{abs_val / 1_000_000:.1f}M'
        elif abs_val >= 10_000:
            return f'{sign}{abs_val / 1_000:.0f}k'
        elif abs_val >= 1_000:
            return f'{sign}{abs_val / 1_000:.1f}k'
        elif isinstance(value, int):
            return f'{sign}{abs_val}'
        elif abs_val >= 100:
            return f'{sign}{abs_val:.0f}'
        elif abs_val >= 1:
            return f'{sign}{abs_val:.1f}'
        else:
            return f'{sign}{abs_val:.2f}'
