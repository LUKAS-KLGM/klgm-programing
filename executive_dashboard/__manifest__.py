{
    "name": "Controlling",
    "version": "19.0.6.3.0",
    "category": "Productivity",
    "summary": "Konfigurierbare Executive Dashboards mit KPIs, Charts, AI Insights und Branchen-Templates",
    "description": """
Controlling — Executive Dashboards für Odoo 19
================================================
- KPI-Karten mit Live-Daten und Vorperiodenvergleich
- Berechnete KPIs (AOV, Marge %, Lieferquote, etc.)
- Native Charts (Bar, Line, Pie, Gauge)
- Drill-Down per Klick
- Rollenbasiert: CEO, CFO, COO, CTO, CSO
- Zeitfilter (30 Tage, Quartal, Jahr, Custom)
- Vergleichsperioden: Vorperiode, Vorjahr, Budget
- AI Insights: Regelbasierte KPI-Analyse mit Empfehlungen
- Drag & Drop Reihenfolge
- KPI-Kommentare und Notizen
- Multi-Company Support
- Custom KPI Builder
- 4 Branchen-Templates (E-Commerce, Dienstleistung, Produktion, Handel)
- Scheduled E-Mail Reports
- CSV/PNG Export, Dark Mode, Fullscreen
    """,
    "author": "KLGM UG (haftungsbeschränkt) i.G.",
    "website": "https://klgm-consulting.de",
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
    },
    "demo": [
        "data/demo_data.xml",
    ],
    "installable": True,
    "application": True,
    "license": "LGPL-3",
}
