{
    "name": "Controlling",
    "version": "19.0.6.5.6",
    "category": "Productivity",
    "summary": "Configurable executive dashboards with KPIs, charts, AI insights and industry templates",
    "description": """
Controlling — Executive Dashboards for Odoo 19
================================================
- KPI cards with live data and period-over-period comparison
- Calculated KPIs (AOV, margin %, delivery rate, etc.)
- Native charts (bar, line, pie, gauge)
- Drill-down on click
- Role-based: CEO, CFO, COO, CTO, CSO
- Time filters (30 days, quarter, year, custom)
- Comparison periods: previous period, previous year, budget
- AI Insights: rule-based KPI analysis with recommendations
- Drag & drop ordering
- KPI comments and notes
- Multi-company support
- Custom KPI builder
- 4 industry templates (e-commerce, services, manufacturing, retail)
- Scheduled email reports
- CSV/PNG export, dark mode, fullscreen
    """,
    "author": "KLGM UG (haftungsbeschränkt) i.G.",
    "website": "https://klgm-consulting.de",
    "price": 199.0,
    "currency": "EUR",
    "depends": [
        "base",
        "web",
        "mail",
        "sale",
        "account",
        "stock",
        "purchase",
        "crm",
        "project",
        "hr",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/dashboard_security.xml",
        "views/dashboard_views.xml",
        "views/dashboard_menu.xml",
        "views/res_config_settings_views.xml",
        "data/dashboard_defaults.xml",
        "data/dashboard_extra_kpis.xml",
        "data/dashboard_sprint1_kpis.xml",
        "data/dashboard_productivity_kpis.xml",
        "data/dashboard_cso.xml",
        "data/dashboard_cron.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "executive_dashboard/static/src/scss/dashboard.scss",
            "executive_dashboard/static/src/components/kpi_card/kpi_card.js",
            "executive_dashboard/static/src/components/kpi_card/kpi_card.xml",
            "executive_dashboard/static/src/components/dashboard_chart/dashboard_chart.js",
            "executive_dashboard/static/src/components/dashboard_chart/dashboard_chart.xml",
            "executive_dashboard/static/src/components/dashboard/dashboard.js",
            "executive_dashboard/static/src/components/dashboard/dashboard.xml",
        ],
        "web.assets_tests": [
            "executive_dashboard/static/src/tours/executive_dashboard_tour.js",
        ],
    },
    "demo": [
        "data/demo_data.xml",
    ],
    "installable": True,
    "application": True,
    "license": "OPL-1",
}
