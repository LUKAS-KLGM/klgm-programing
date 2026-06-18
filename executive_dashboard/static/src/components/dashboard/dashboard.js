/** @odoo-module **/

import { Component, useState, useRef, onWillStart, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";
import { rpc } from "@web/core/network/rpc";
import { KpiCard } from "../kpi_card/kpi_card";
import { DashboardChart } from "../dashboard_chart/dashboard_chart";

export class ExecutiveDashboard extends Component {
    static template = "executive_dashboard.Dashboard";
    static components = { KpiCard, DashboardChart };

    setup() {
        this.action = useService("action");
        this.refreshTimer = null;
        this.contentRef = useRef("content");

        this.state = useState({
            dashboards: [],
            activeDashboard: null,
            dashboardData: null,
            period: "last_30_days",
            loading: true,
            chartReady: false,
            isDark: localStorage.getItem("ed_dark_mode") === "1" ||
                   document.documentElement.getAttribute("data-bs-theme") === "dark",
            isFullscreen: false,
            activityState: "all",
            showExportMenu: false,
            comparisonMode: "previous_period",
            // Insights
            showInsights: false,
            insightsTab: "summary", // summary | ai
            summaryInsights: [],
            aiInsights: [],
            insightsLoading: false,
            hasAiKey: false,
            // Templates
            showTemplates: false,
            templates: [],
            // KPI Builder
            showBuilder: false,
            builderModels: [],
            builderFields: [],
            builderDateFields: [],
            builderForm: {
                name: "", display_type: "scorecard", source_type: "model",
                model_name: "", measure_field: "", aggregate: "sum",
                group_by: "", unit: "", date_field: "date", domain: "[]",
                apply_date_filter: true, show_comparison: true,
                target_value: 0, budget_value: 0,
            },
            // Dashboard Creator
            showCreator: false,
            creatorName: "",
            creatorIcon: "fa-tachometer",
            creatorError: "",
            allKpis: [],
            selectedKpiIds: new Set(),
            // Custom Date
            showCustomDate: false,
            customDateFrom: "",
            customDateTo: "",
            // Favorite
            favoriteDashboardId: Number(localStorage.getItem("ed_favorite_dashboard") || 0),
            // Module status
            hasActivityHistory: true,
            // Config menu
            showConfigMenu: false,
            // Drag & Drop
            dragId: null,
            dragType: null,
        });

        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            this.state.chartReady = true;
            this.state.hasAiKey = await rpc("/executive_dashboard/has_ai_key");
            const modStatus = await rpc("/executive_dashboard/module_status");
            this.state.hasActivityHistory = modStatus.activity_history || false;
            await this.loadDashboards();
        });

        onWillUnmount(() => {
            this.clearAutoRefresh();
        });
    }

    clearAutoRefresh() {
        if (this.refreshTimer) { clearInterval(this.refreshTimer); this.refreshTimer = null; }
    }

    setupAutoRefresh(seconds) {
        this.clearAutoRefresh();
        if (seconds > 0) {
            this.refreshTimer = setInterval(() => {
                if (this.state.activeDashboard && !this.state.loading) {
                    this.selectDashboard(this.state.activeDashboard);
                }
            }, seconds * 1000);
        }
    }

    async loadDashboards() {
        this.state.loading = true;
        const dashboards = await rpc("/executive_dashboard/list");
        this.state.dashboards = dashboards;
        const params = this.props.action?.params || {};
        const favId = this.state.favoriteDashboardId;
        const targetId = params.dashboard_id
            || (favId && dashboards.find(d => d.id === favId) ? favId : null)
            || (dashboards.length ? dashboards[0].id : null);
        if (targetId) {
            const match = dashboards.find(d => d.id === targetId);
            if (match) {
                this.state.period = match.default_period || "last_30_days";
                this.state.comparisonMode = match.comparison_mode || "previous_period";
                await this.selectDashboard(targetId);
                return;
            }
        }
        this.state.loading = false;
    }

    async selectDashboard(id) {
        this.state.loading = true;
        this.state.activeDashboard = id;
        this.state.showExportMenu = false;
        this.state.showInsights = false;
        const data = await rpc("/executive_dashboard/data", {
            dashboard_id: id,
            period: this.state.period,
            activity_state: this.state.activityState,
        });
        this.state.dashboardData = data;
        this.state.comparisonMode = data.comparison_mode || "previous_period";
        this.state.loading = false;
        this.setupAutoRefresh(data.auto_refresh || 0);
    }

    async onPeriodChange(ev) {
        const val = ev.target.value;
        if (val === "custom") {
            this.state.showCustomDate = true;
            return;
        }
        this.state.period = val;
        this.state.showCustomDate = false;
        if (this.state.activeDashboard) await this.selectDashboard(this.state.activeDashboard);
    }

    async applyCustomDate() {
        const from = this.state.customDateFrom;
        const to = this.state.customDateTo;
        if (!from || !to) return;
        this.state.period = `custom:${from},${to}`;
        this.state.showCustomDate = false;
        if (this.state.activeDashboard) await this.selectDashboard(this.state.activeDashboard);
    }

    onCustomDateFrom(ev) { this.state.customDateFrom = ev.target.value; }
    onCustomDateTo(ev) { this.state.customDateTo = ev.target.value; }

    async onTabClick(id) { await this.selectDashboard(id); }

    async onDashboardChange(ev) {
        const val = ev.target.value;
        if (val === "__new__") {
            ev.target.value = this.state.activeDashboard;
            this.openCreator();
            return;
        }
        await this.selectDashboard(Number(val));
    }

    async onRefresh() {
        if (this.state.activeDashboard) await this.selectDashboard(this.state.activeDashboard);
    }

    toggleDark() {
        this.state.isDark = !this.state.isDark;
        localStorage.setItem("ed_dark_mode", this.state.isDark ? "1" : "0");
    }

    async setActivityState(state) {
        this.state.activityState = state;
        if (this.state.activeDashboard) await this.selectDashboard(this.state.activeDashboard);
    }

    get isCSO() {
        return this.state.dashboardData?.role === 'cso';
    }

    toggleFullscreen() {
        this.state.isFullscreen = !this.state.isFullscreen;
    }

    toggleExportMenu() {
        this.state.showExportMenu = !this.state.showExportMenu;
    }

    // ── Comparison Mode ──

    async setComparisonMode(mode) {
        this.state.comparisonMode = mode;
        await rpc("/executive_dashboard/set_comparison", {
            dashboard_id: this.state.activeDashboard, mode,
        });
        if (this.state.activeDashboard) await this.selectDashboard(this.state.activeDashboard);
    }

    get comparisonOptions() {
        return [
            { value: "previous_period", label: "Vorperiode" },
            { value: "previous_year", label: "Vorjahr" },
            { value: "budget", label: "Budget" },
        ];
    }

    // ── Insights ──

    async toggleInsights() {
        if (this.state.showInsights) {
            this.state.showInsights = false;
            return;
        }
        this.state.insightsLoading = true;
        this.state.showInsights = true;
        this.state.insightsTab = "summary";
        const result = await rpc("/executive_dashboard/ai_insights", {
            dashboard_id: this.state.activeDashboard,
            period: this.state.period,
        });
        this.state.summaryInsights = result.summary || [];
        this.state.insightsLoading = false;
    }

    async switchInsightsTab(tab) {
        this.state.insightsTab = tab;
        if (tab === "ai" && this.state.aiInsights.length === 0) {
            this.state.insightsLoading = true;
            this.state.aiInsights = await rpc("/executive_dashboard/ai_insights_real", {
                dashboard_id: this.state.activeDashboard,
                period: this.state.period,
            });
            this.state.insightsLoading = false;
        }
    }

    get activeInsights() {
        return this.state.insightsTab === "ai" ? this.state.aiInsights : this.state.summaryInsights;
    }

    toggleConfigMenu() {
        this.state.showConfigMenu = !this.state.showConfigMenu;
        this.state.showExportMenu = false;
    }

    // ── Templates ──

    async toggleTemplates() {
        this.state.showConfigMenu = false;
        if (this.state.showTemplates) {
            this.state.showTemplates = false;
            return;
        }
        this.state.templates = await rpc("/executive_dashboard/templates");
        this.state.showTemplates = true;
    }

    async createFromTemplate(key) {
        const result = await rpc("/executive_dashboard/create_from_template", {
            template_key: key,
        });
        if (result.id) {
            this.state.showTemplates = false;
            await this.loadDashboards();
            await this.selectDashboard(result.id);
        }
    }

    // ── Dashboard Creator ──

    async openCreator() {
        this.state.allKpis = await rpc("/executive_dashboard/all_kpis");
        this.state.selectedKpiIds = new Set();
        this.state.creatorName = "";
        this.state.creatorIcon = "fa-tachometer";
        this.state.creatorError = "";
        this.state.showCreator = true;
    }

    closeCreator() { this.state.showCreator = false; }

    toggleKpiSelection(id) {
        const s = this.state.selectedKpiIds;
        if (s.has(id)) { s.delete(id); } else { s.add(id); }
        this.state.creatorError = "";
    }

    async submitCreator() {
        const name = this.state.creatorName.trim();
        if (!name && !this.state.selectedKpiIds.size) {
            this.state.creatorError = "Bitte Name eingeben und mindestens einen KPI auswählen.";
            return;
        }
        if (!name) {
            this.state.creatorError = "Bitte einen Dashboard-Namen eingeben.";
            return;
        }
        if (!this.state.selectedKpiIds.size) {
            this.state.creatorError = "Bitte mindestens einen KPI auswählen.";
            return;
        }
        this.state.creatorError = "";
        const kpi_ids = [...this.state.selectedKpiIds].map(id => ({ id }));
        const result = await rpc("/executive_dashboard/create_dashboard", {
            name, icon: this.state.creatorIcon, kpi_ids,
        });
        if (result.id) {
            this.state.showCreator = false;
            await this.loadDashboards();
            await this.selectDashboard(result.id);
        }
    }

    get creatorIconOptions() {
        return [
            { value: "fa-tachometer", label: "Dashboard" },
            { value: "fa-building", label: "Unternehmen" },
            { value: "fa-money", label: "Finanzen" },
            { value: "fa-cogs", label: "Operations" },
            { value: "fa-code", label: "Technik" },
            { value: "fa-line-chart", label: "Vertrieb" },
            { value: "fa-users", label: "Team" },
            { value: "fa-shopping-cart", label: "E-Commerce" },
        ];
    }

    // ── KPI Builder ──

    async toggleBuilder() {
        this.state.showConfigMenu = false;
        if (this.state.showBuilder) {
            this.state.showBuilder = false;
            return;
        }
        this.state.builderModels = await rpc("/executive_dashboard/builder/models");
        this.state.showBuilder = true;
    }

    async onBuilderModelChange(ev) {
        const model = ev.target.value;
        this.state.builderForm.model_name = model;
        this.state.builderForm.measure_field = "";
        this.state.builderForm.date_field = "date";
        if (model) {
            const [fields, dateFields] = await Promise.all([
                rpc("/executive_dashboard/builder/fields", { model_name: model }),
                rpc("/executive_dashboard/builder/date_fields", { model_name: model }),
            ]);
            this.state.builderFields = fields;
            this.state.builderDateFields = dateFields;
        } else {
            this.state.builderFields = [];
            this.state.builderDateFields = [];
        }
    }

    onBuilderFieldChange(field, ev) {
        const val = ev.target.type === "checkbox" ? ev.target.checked :
                    ev.target.type === "number" ? parseFloat(ev.target.value) || 0 :
                    ev.target.value;
        this.state.builderForm[field] = val;
    }

    async submitBuilder() {
        const form = this.state.builderForm;
        if (!form.name || !form.model_name || !form.measure_field) return;
        await rpc("/executive_dashboard/builder/create", {
            dashboard_id: this.state.activeDashboard,
            values: { ...form },
        });
        this.state.showBuilder = false;
        // Reset form
        this.state.builderForm = {
            name: "", display_type: "scorecard", source_type: "model",
            model_name: "", measure_field: "", aggregate: "sum",
            group_by: "", unit: "", date_field: "date", domain: "[]",
            apply_date_filter: true, show_comparison: true,
            target_value: 0, budget_value: 0,
        };
        await this.onRefresh();
    }

    // ── Drag & Drop ──

    onDragStart(type, id, ev) {
        this.state.dragId = id;
        this.state.dragType = type;
        ev.dataTransfer.effectAllowed = "move";
        ev.target.classList.add("ed-dragging");
    }

    onDragEnd(ev) {
        ev.target.classList.remove("ed-dragging");
        this.state.dragId = null;
        this.state.dragType = null;
    }

    onDragOver(ev) {
        ev.preventDefault();
        ev.dataTransfer.dropEffect = "move";
    }

    async onDrop(type, targetId, ev) {
        ev.preventDefault();
        const sourceId = this.state.dragId;
        if (!sourceId || sourceId === targetId || this.state.dragType !== type) return;

        const items = type === "scorecard" ? this.scorecards : this.charts;
        const sourceIdx = items.findIndex(k => k.id === sourceId);
        const targetIdx = items.findIndex(k => k.id === targetId);
        if (sourceIdx === -1 || targetIdx === -1) return;

        // Reorder locally
        const moved = items.splice(sourceIdx, 1)[0];
        items.splice(targetIdx, 0, moved);

        // Build sequence updates
        const updates = items.map((k, i) => ({ id: k.id, sequence: (i + 1) * 10 }));
        await rpc("/executive_dashboard/update_sequence", { kpi_ids: updates });
        await this.onRefresh();
    }

    // ── Export PNG ──
    async exportPNG() {
        this.state.showExportMenu = false;
        const el = this.contentRef.el;
        if (!el) return;
        try {
            const canvases = el.querySelectorAll("canvas");
            if (canvases.length === 0) return;
            const canvas = canvases[0];
            const link = document.createElement("a");
            link.download = `${this.state.dashboardData?.name || "dashboard"}.png`;
            link.href = canvas.toDataURL("image/png");
            link.click();
        } catch (e) {
            console.warn("Export PNG failed:", e);
        }
    }

    // ── Export CSV ──
    exportCSV() {
        this.state.showExportMenu = false;
        const data = this.state.dashboardData;
        if (!data) return;

        const rows = [["KPI", "Wert", "Vorperiode", "Veränderung %", "Einheit"]];
        for (const kpi of data.kpis) {
            if (kpi.display_type === "scorecard") {
                rows.push([kpi.name, kpi.value, kpi.previous || "", kpi.change_pct || "", kpi.unit || ""]);
            }
        }
        for (const kpi of data.kpis) {
            if (kpi.display_type.startsWith("chart_") && kpi.chart_data) {
                rows.push([]);
                rows.push([kpi.name]);
                rows.push(["Label", "Wert"]);
                for (const d of kpi.chart_data) {
                    rows.push([d.label, d.value]);
                }
            }
        }
        const csv = rows.map(r => r.map(v => `"${v}"`).join(";")).join("\n");
        const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" });
        const link = document.createElement("a");
        link.download = `${data.name || "dashboard"}_${this.state.period}.csv`;
        link.href = URL.createObjectURL(blob);
        link.click();
        URL.revokeObjectURL(link.href);
    }

    async onDrillDown(kpi) {
        if (!kpi) return;
        // Legacy: string = action xmlid
        if (typeof kpi === 'string') {
            this.action.doAction(kpi);
            return;
        }
        const result = await rpc("/executive_dashboard/drilldown", {
            kpi_id: kpi.id,
            period: this.state.period,
        });
        if (result) this.action.doAction(result);
    }

    get scorecards() {
        if (!this.state.dashboardData) return [];
        return this.state.dashboardData.kpis.filter(k => k.display_type === "scorecard" && !k.name.startsWith("_"));
    }

    get charts() {
        if (!this.state.dashboardData) return [];
        return this.state.dashboardData.kpis.filter(k => k.display_type.startsWith("chart_") && !k.name.startsWith("_"));
    }

    get periodOptions() {
        return [
            { value: "last_7_days", label: "7 Tage" },
            { value: "last_30_days", label: "30 Tage" },
            { value: "last_90_days", label: "90 Tage" },
            { value: "this_month", label: "Dieser Monat" },
            { value: "this_quarter", label: "Dieses Quartal" },
            { value: "this_year", label: "Dieses Jahr" },
            { value: "last_year", label: "Letztes Jahr" },
            { value: "all_time", label: "Jemals" },
            { value: "custom", label: "Benutzerdefiniert..." },
        ];
    }

    get themeClass() {
        let cls = "";
        if (this.state.isDark) cls += "ed-dark";
        if (this.state.isFullscreen) cls += " ed-fullscreen";
        return cls;
    }

    get activeDashboardName() {
        const db = this.state.dashboards.find(d => d.id === this.state.activeDashboard);
        return db ? db.name : "";
    }

    get activeDashboardIcon() {
        const db = this.state.dashboards.find(d => d.id === this.state.activeDashboard);
        return db ? db.icon : "fa-tachometer";
    }

    get isFavorite() {
        return this.state.favoriteDashboardId === this.state.activeDashboard;
    }

    toggleFavorite() {
        if (this.isFavorite) {
            localStorage.removeItem("ed_favorite_dashboard");
            this.state.favoriteDashboardId = 0;
        } else {
            localStorage.setItem("ed_favorite_dashboard", String(this.state.activeDashboard));
            this.state.favoriteDashboardId = this.state.activeDashboard;
        }
    }

    get displayTypeOptions() {
        return [
            { value: "scorecard", label: "Scorecard" },
            { value: "chart_bar", label: "Balken" },
            { value: "chart_bar_h", label: "Balken (H)" },
            { value: "chart_line", label: "Linie" },
            { value: "chart_pie", label: "Torte" },
            { value: "chart_doughnut", label: "Ring" },
            { value: "chart_gauge", label: "Gauge" },
            { value: "chart_table", label: "Tabelle" },
        ];
    }

    get aggregateOptions() {
        return [
            { value: "sum", label: "Summe" },
            { value: "avg", label: "Durchschnitt" },
            { value: "count", label: "Anzahl" },
            { value: "min", label: "Minimum" },
            { value: "max", label: "Maximum" },
        ];
    }
}

registry.category("actions").add("executive_dashboard", ExecutiveDashboard);
