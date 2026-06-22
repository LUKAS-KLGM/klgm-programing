/** @odoo-module **/

import { Component, useRef, useState, onMounted, onWillUnmount, onPatched } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

const COLORS = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
    "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
];
function getColor(i) { return COLORS[i % COLORS.length]; }

function fmtValue(v) {
    if (v === null || v === undefined) return "";
    const abs = Math.abs(v);
    const sign = v < 0 ? "-" : "";
    if (abs >= 1e6) return sign + (abs / 1e6).toFixed(1) + "M";
    if (abs >= 1e4) return sign + (abs / 1e3).toFixed(0) + "k";
    if (abs >= 1e3) return sign + (abs / 1e3).toFixed(1) + "k";
    if (Number.isInteger(v)) return v.toLocaleString("de-DE");
    return v.toLocaleString("de-DE", { maximumFractionDigits: 1 });
}

function isDarkMode() {
    return document.querySelector(".ed-container.ed-dark") !== null ||
           document.documentElement.getAttribute("data-bs-theme") === "dark";
}

export class DashboardChart extends Component {
    static template = "executive_dashboard.DashboardChart";
    static props = {
        kpi: Object,
        isDark: { type: Boolean, optional: true },
        onDrillDown: { type: Function, optional: true },
        onKpiUpdated: { type: Function, optional: true },
        activityState: { type: String, optional: true },
        onActivityStateChange: { type: Function, optional: true },
        // Drag & Drop callbacks
        onDragStart: { type: Function, optional: true },
        onDragEnd: { type: Function, optional: true },
        onDragOver: { type: Function, optional: true },
        onDrop: { type: Function, optional: true },
    };

    get isActivityKpi() {
        return this.props.kpi.model_name === 'mail.activity' ||
               (this.props.kpi.name || '').toLowerCase().includes('aktivit') ||
               (this.props.kpi.name || '').toLowerCase().includes('anruf') ||
               (this.props.kpi.name || '').toLowerCase().includes('e-mail') ||
               (this.props.kpi.name || '').toLowerCase().includes('meeting') ||
               (this.props.kpi.name || '').toLowerCase().includes('to-do');
    }

    get activityStateOptions() {
        return [
            { value: "all", label: _t("All"), icon: "fa-list" },
            { value: "planned", label: _t("Planned"), icon: "fa-clock-o" },
            { value: "done", label: _t("Done"), icon: "fa-check" },
        ];
    }

    setup() {
        this._t = _t;
        this.canvasRef = useRef("canvas");
        this.chart = null;
        this.state = useState({ showMenu: false, sortField: "value", sortAsc: false });
        this._onDocClick = this.onDocClick.bind(this);
        onMounted(() => {
            this.renderChart();
            document.addEventListener("click", this._onDocClick);
        });
        onPatched(() => this.renderChart());
        onWillUnmount(() => {
            this.destroyChart();
            document.removeEventListener("click", this._onDocClick);
        });
    }

    onDocClick() {
        if (this.state.showMenu) this.state.showMenu = false;
    }

    toggleMenu() { this.state.showMenu = !this.state.showMenu; }

    get displayOptions() {
        return [
            { value: "scorecard", label: _t("Scorecard"), icon: "fa-tachometer" },
            { value: "chart_bar", label: _t("Bar"), icon: "fa-bar-chart" },
            { value: "chart_bar_h", label: _t("Bar (H)"), icon: "fa-align-left" },
            { value: "chart_line", label: _t("Line"), icon: "fa-line-chart" },
            { value: "chart_pie", label: _t("Pie"), icon: "fa-pie-chart" },
            { value: "chart_doughnut", label: _t("Donut"), icon: "fa-circle-o" },
            { value: "chart_gauge", label: _t("Gauge"), icon: "fa-dashboard" },
            { value: "chart_table", label: _t("Table"), icon: "fa-table" },
        ];
    }

    get widthOptions() {
        return [
            { value: "third", label: "\u2153 " + _t("Width"), icon: "fa-columns" },
            { value: "half", label: "\u00BD " + _t("Width"), icon: "fa-columns" },
            { value: "two_thirds", label: "\u2154 " + _t("Width"), icon: "fa-columns" },
            { value: "full", label: _t("Full Width"), icon: "fa-arrows-h" },
        ];
    }

    async setDisplayType(value) {
        this.state.showMenu = false;
        await rpc("/executive_dashboard/update_kpi", {
            kpi_id: this.props.kpi.id, values: { display_type: value },
        });
        if (this.props.onKpiUpdated) this.props.onKpiUpdated();
    }

    async setWidth(value) {
        this.state.showMenu = false;
        await rpc("/executive_dashboard/update_kpi", {
            kpi_id: this.props.kpi.id, values: { width: value },
        });
        if (this.props.onKpiUpdated) this.props.onKpiUpdated();
    }

    async saveTarget(ev) {
        const val = parseFloat(ev.target.value) || 0;
        await rpc("/executive_dashboard/update_kpi", {
            kpi_id: this.props.kpi.id, values: { target_value: val },
        });
        if (this.props.onKpiUpdated) this.props.onKpiUpdated();
    }

    async saveBudget(ev) {
        const val = parseFloat(ev.target.value) || 0;
        await rpc("/executive_dashboard/update_kpi", {
            kpi_id: this.props.kpi.id, values: { budget_value: val },
        });
        if (this.props.onKpiUpdated) this.props.onKpiUpdated();
    }

    setActivityFilter(value) {
        this.state.showMenu = false;
        if (this.props.onActivityStateChange) {
            this.props.onActivityStateChange(value);
        }
    }

    destroyChart() {
        if (this.chart) { this.chart.destroy(); this.chart = null; }
    }

    get chartType() {
        const t = this.props.kpi.display_type;
        if (t === "chart_bar_h") return "bar";
        if (t === "chart_table") return "table";
        if (t === "chart_gauge") return "gauge";
        return { chart_bar: "bar", chart_line: "line", chart_pie: "pie", chart_doughnut: "doughnut" }[t] || "bar";
    }
    get isHorizontal() { return this.props.kpi.display_type === "chart_bar_h"; }
    get isCircular() { return ["pie", "doughnut"].includes(this.chartType); }
    get isTable() { return this.props.kpi.display_type === "chart_table"; }
    get isGauge() { return this.props.kpi.display_type === "chart_gauge"; }

    get widthClass() {
        const w = this.props.kpi.width || "half";
        return { third: "ed-chart-third", half: "ed-chart-half", two_thirds: "ed-chart-twothirds", full: "ed-chart-full" }[w] || "ed-chart-half";
    }

    fmtVal(v) { return fmtValue(v); }

    sortTable(field) {
        if (this.state.sortField === field) {
            this.state.sortAsc = !this.state.sortAsc;
        } else {
            this.state.sortField = field;
            this.state.sortAsc = field === "label";
        }
    }

    get sortedTableData() {
        const data = [...(this.props.kpi.chart_data || [])];
        const field = this.state.sortField;
        const asc = this.state.sortAsc;
        data.sort((a, b) => {
            let va = a[field], vb = b[field];
            if (typeof va === "string") va = va.toLowerCase();
            if (typeof vb === "string") vb = vb.toLowerCase();
            if (va < vb) return asc ? -1 : 1;
            if (va > vb) return asc ? 1 : -1;
            return 0;
        });
        return data;
    }

    // ── Gauge helpers ──
    get gaugeValue() { return this.props.kpi.value || 0; }
    get gaugeTarget() { return this.props.kpi.target_value || 100; }
    get gaugePct() {
        return Math.min(100, Math.max(0, Math.round(this.gaugeValue / this.gaugeTarget * 100)));
    }
    get gaugeColor() {
        const s = this.props.kpi.target_status;
        if (s === "green") return "#059669";
        if (s === "red") return "#dc2626";
        return "#d97706";
    }
    get gaugeDisplayValue() { return fmtValue(this.gaugeValue); }

    renderChart() {
        if (this.isTable || this.isGauge) {
            if (this.isGauge) this.renderGauge();
            return;
        }
        const el = this.canvasRef.el;
        if (!el || typeof Chart === "undefined") return;
        this.destroyChart();

        const data = this.props.kpi.chart_data || [];
        if (!data.length) return;

        const dark = this.props.isDark || false;
        const textColor = dark ? "#ccc" : "#555";
        const gridColor = dark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.04)";

        const labels = data.map(d => d.label);
        const values = data.map(d => d.value);
        const colors = data.map((_, i) => getColor(i));

        const barColors = this.chartType === "bar"
            ? values.map((_, i) => getColor(i % 5))
            : getColor(0);

        const datasets = [{
            label: this.props.kpi.name,
            data: values,
            backgroundColor: this.isCircular ? colors : barColors,
            borderColor: this.chartType === "line" ? getColor(0) : "transparent",
            borderWidth: this.chartType === "line" ? 2 : 0,
            borderRadius: this.chartType === "bar" ? 4 : 0,
            fill: this.chartType === "line" ? { target: "origin", above: dark ? "rgba(78,121,167,0.15)" : "rgba(78,121,167,0.08)" } : false,
            tension: 0.3,
            pointRadius: this.chartType === "line" ? 3 : 0,
            pointBackgroundColor: this.chartType === "line" ? getColor(0) : undefined,
        }];

        const options = {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 350 },
            indexAxis: this.isHorizontal ? "y" : "x",
            layout: { padding: { top: this.isCircular ? 0 : 20 } },
            plugins: {
                legend: {
                    display: this.isCircular,
                    position: "right",
                    labels: {
                        color: textColor,
                        font: { size: 13 },
                        padding: 10,
                        boxWidth: 14,
                        generateLabels: this.isCircular ? (chart) => {
                            const ds = chart.data.datasets[0];
                            return chart.data.labels.map((label, i) => ({
                                text: `${label}: ${fmtValue(ds.data[i])}`,
                                fillStyle: colors[i],
                                fontColor: textColor,
                                strokeStyle: "transparent",
                                hidden: false,
                                index: i,
                            }));
                        } : undefined,
                    },
                },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            const val = ctx.parsed.y ?? ctx.parsed.x ?? ctx.parsed;
                            const fmt = typeof val === "number" ? val.toLocaleString("de-DE", { maximumFractionDigits: 0 }) : val;
                            const unit = this.props.kpi.unit || "";
                            return `${ctx.label}: ${fmt} ${unit}`.trim();
                        },
                    },
                },
            },
            onClick: (event, elements) => {
                if (elements.length && this.props.onDrillDown && this.props.kpi.action_xmlid) {
                    this.props.onDrillDown(this.props.kpi.action_xmlid);
                }
            },
        };

        if (!this.isCircular) {
            const valAxis = {
                grid: { color: gridColor },
                ticks: { color: textColor, font: { size: 10 }, callback: (v) => fmtValue(v) },
                beginAtZero: true,
            };
            const labelAxis = {
                grid: { display: false },
                ticks: { color: textColor, font: { size: 10 }, maxRotation: 45, autoSkip: true, maxTicksLimit: 15 },
            };
            options.scales = this.isHorizontal
                ? { x: valAxis, y: labelAxis }
                : { x: labelAxis, y: valAxis };
        }

        this.chart = new Chart(el, { type: this.chartType, data: { labels, datasets }, options });
    }

    // ── Gauge Rendering (Canvas 2D, no Chart.js needed) ──
    renderGauge() {
        const el = this.canvasRef.el;
        if (!el) return;

        const ctx = el.getContext("2d");
        const w = el.width = el.offsetWidth * 2;
        const h = el.height = el.offsetHeight * 2;
        ctx.clearRect(0, 0, w, h);

        const cx = w / 2;
        const cy = h * 0.72;
        const radius = Math.min(cx, cy) * 0.8;
        const lineWidth = radius * 0.22;

        const startAngle = Math.PI;
        const endAngle = 2 * Math.PI;
        const pct = this.gaugePct / 100;
        const valueAngle = startAngle + pct * Math.PI;

        const dark = this.props.isDark || false;

        // Background arc
        ctx.beginPath();
        ctx.arc(cx, cy, radius, startAngle, endAngle);
        ctx.lineWidth = lineWidth;
        ctx.strokeStyle = dark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.06)";
        ctx.lineCap = "round";
        ctx.stroke();

        // Value arc
        if (pct > 0) {
            ctx.beginPath();
            ctx.arc(cx, cy, radius, startAngle, valueAngle);
            ctx.lineWidth = lineWidth;
            ctx.strokeStyle = this.gaugeColor;
            ctx.lineCap = "round";
            ctx.stroke();
        }

        // Center value text
        ctx.fillStyle = dark ? "#eee" : "#2d2d2d";
        ctx.font = `bold ${radius * 0.38}px -apple-system, BlinkMacSystemFont, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(this.gaugeDisplayValue, cx, cy - radius * 0.1);

        // Unit
        const unit = this.props.kpi.unit || "";
        if (unit) {
            ctx.fillStyle = dark ? "#999" : "#888";
            ctx.font = `${radius * 0.18}px -apple-system, sans-serif`;
            ctx.fillText(unit, cx, cy + radius * 0.18);
        }

        // Percentage below
        ctx.fillStyle = this.gaugeColor;
        ctx.font = `bold ${radius * 0.22}px -apple-system, sans-serif`;
        ctx.fillText(`${this.gaugePct}%`, cx, cy + radius * 0.48);

        // Target label
        ctx.fillStyle = dark ? "#666" : "#aaa";
        ctx.font = `${radius * 0.14}px -apple-system, sans-serif`;
        ctx.fillText(`${_t("Target")}: ${fmtValue(this.gaugeTarget)}`, cx, cy + radius * 0.72);
    }

    _getDataLabelsConfig(dark, textColor) {
        return {};
    }
}

// Chart.js plugin: value labels on bars/lines
if (typeof Chart !== "undefined") {
    Chart.register({
        id: "edValueLabels",
        afterDatasetsDraw(chart) {
            const type = chart.config.type;
            if (type === "pie" || type === "doughnut") return;

            const ctx = chart.ctx;
            const dark = isDarkMode();
            ctx.save();
            ctx.font = "bold 10px -apple-system, BlinkMacSystemFont, sans-serif";
            ctx.fillStyle = dark ? "#ccc" : "#555";
            ctx.textAlign = "center";

            chart.data.datasets.forEach((ds, dsi) => {
                const meta = chart.getDatasetMeta(dsi);
                meta.data.forEach((element, i) => {
                    const val = ds.data[i];
                    if (val === 0 || val === null || val === undefined) return;
                    const text = fmtValue(val);

                    if (chart.config.options.indexAxis === "y") {
                        ctx.textAlign = "left";
                        ctx.fillText(text, element.x + 6, element.y + 4);
                    } else if (type === "line") {
                        ctx.fillText(text, element.x, element.y - 10);
                    } else {
                        ctx.fillText(text, element.x, element.y - 6);
                    }
                });
            });
            ctx.restore();
        },
    });
}
