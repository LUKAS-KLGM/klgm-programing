/** @odoo-module **/

import { Component, useState, useRef, onMounted, onPatched, onWillUnmount } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";

const DARK_COLORS = {
    "#EFF6FF": "#1e2a3d", "#eff6ff": "#1e2a3d",
    "#F0FFF4": "#1a2e22", "#f0fff4": "#1a2e22",
    "#FFF7ED": "#2e2518", "#fff7ed": "#2e2518",
    "#EFF6EF": "#1c2e1c", "#eff6ef": "#1c2e1c",
};

export class KpiCard extends Component {
    static template = "executive_dashboard.KpiCard";
    static props = {
        kpi: Object,
        isDark: { type: Boolean, optional: true },
        onDrillDown: { type: Function, optional: true },
        onKpiUpdated: { type: Function, optional: true },
        activityState: { type: String, optional: true },
        onActivityStateChange: { type: Function, optional: true },
    };

    setup() {
        this.state = useState({
            showMenu: false,
            showNotes: false,
            showEditor: false,
            editForm: {},
            notes: [],
            noteText: "",
            notesLoading: false,
        });
        this.sparkRef = useRef("sparkline");
        this._onDocClick = this.onDocClick.bind(this);
        onMounted(() => {
            this.renderSparkline();
            document.addEventListener("click", this._onDocClick);
        });
        onPatched(() => this.renderSparkline());
        onWillUnmount(() => {
            document.removeEventListener("click", this._onDocClick);
        });
    }

    onDocClick() {
        if (this.state.showMenu) this.state.showMenu = false;
    }

    renderSparkline() {
        const canvas = this.sparkRef.el;
        if (!canvas) return;
        const data = this.props.kpi.sparkline || [];
        if (data.length < 2) { canvas.style.display = "none"; return; }
        canvas.style.display = "block";

        const ctx = canvas.getContext("2d");
        const w = canvas.width = canvas.offsetWidth * 2;
        const h = canvas.height = canvas.offsetHeight * 2;
        ctx.clearRect(0, 0, w, h);

        const max = Math.max(...data);
        const min = Math.min(...data);
        const range = max - min || 1;
        const pad = 4;

        const trending = data[data.length - 1] >= data[0];
        const color = trending ? "#34d399" : "#f87171";

        const labelPad = 28;
        const drawW = w - labelPad * 2;

        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        const points = [];
        for (let i = 0; i < data.length; i++) {
            const x = labelPad + (i / (data.length - 1)) * drawW;
            const y = h - pad - ((data[i] - min) / range) * (h - pad * 2);
            points.push({ x, y });
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        }
        ctx.stroke();
        ctx.lineTo(labelPad + drawW, h);
        ctx.lineTo(labelPad, h);
        ctx.closePath();
        ctx.fillStyle = color + "18";
        ctx.fill();

        // Labels: first and last value
        const fmtSpark = (v) => {
            if (v >= 1e6) return (v / 1e6).toFixed(1) + "M";
            if (v >= 1e3) return (v / 1e3).toFixed(0) + "k";
            return Number.isInteger(v) ? String(v) : v.toFixed(1);
        };
        ctx.font = "bold 16px -apple-system, sans-serif";
        ctx.fillStyle = this.props.isDark ? "#999" : "#888";
        ctx.textBaseline = "middle";
        // First
        ctx.textAlign = "left";
        ctx.fillText(fmtSpark(data[0]), 2, points[0].y);
        // Last
        ctx.textAlign = "right";
        ctx.fillText(fmtSpark(data[data.length - 1]), w - 2, points[points.length - 1].y);
    }

    get changeClass() {
        const pct = this.props.kpi.change_pct || 0;
        return pct > 0 ? "ed-change-up" : pct < 0 ? "ed-change-down" : "ed-change-neutral";
    }
    get changeIcon() {
        const pct = this.props.kpi.change_pct || 0;
        return pct > 0 ? "fa-arrow-up" : pct < 0 ? "fa-arrow-down" : "fa-minus";
    }
    get changeText() {
        const pct = this.props.kpi.change_pct || 0;
        return `${pct > 0 ? "+" : ""}${pct}%`;
    }
    get comparisonLabel() {
        return this.props.kpi.comparison_label || "vs. Vorperiode";
    }
    get hasTarget() { return this.props.kpi.target_value > 0; }
    get targetClass() {
        const s = this.props.kpi.target_status;
        return s === "green" ? "ed-target-green" : s === "yellow" ? "ed-target-yellow" : s === "red" ? "ed-target-red" : "";
    }
    get targetProgress() {
        if (!this.props.kpi.target_value) return 0;
        return Math.min(100, Math.round(this.props.kpi.value / this.props.kpi.target_value * 100));
    }
    get cardColor() {
        const c = this.props.kpi.color || "#EFF6FF";
        return this.props.isDark ? (DARK_COLORS[c] || "#242736") : c;
    }
    get hasSparkline() { return (this.props.kpi.sparkline || []).length >= 2; }
    get hasNotes() { return (this.props.kpi.note_count || 0) > 0; }

    get displayOptions() {
        return [
            { value: "scorecard", label: "Scorecard", icon: "fa-tachometer" },
            { value: "chart_bar", label: "Balken", icon: "fa-bar-chart" },
            { value: "chart_line", label: "Linie", icon: "fa-line-chart" },
            { value: "chart_pie", label: "Torte", icon: "fa-pie-chart" },
            { value: "chart_doughnut", label: "Ring", icon: "fa-circle-o" },
            { value: "chart_gauge", label: "Gauge", icon: "fa-dashboard" },
            { value: "chart_table", label: "Tabelle", icon: "fa-table" },
        ];
    }

    get isActivityKpi() {
        const n = (this.props.kpi.name || '').toLowerCase();
        return n.includes('aktivit') || n.includes('anruf') || n.includes('e-mail') || n.includes('meeting') || n.includes('to-do');
    }

    get activityStateOptions() {
        return [
            { value: "all", label: "Alle", icon: "fa-list" },
            { value: "planned", label: "Geplant", icon: "fa-clock-o" },
            { value: "done", label: "Erledigt", icon: "fa-check" },
        ];
    }

    setActivityFilter(value) {
        this.state.showMenu = false;
        if (this.props.onActivityStateChange) this.props.onActivityStateChange(value);
    }

    toggleMenu() {
        this.state.showNotes = false;
        this.state.showMenu = !this.state.showMenu;
    }
    async setDisplayType(value) {
        this.state.showMenu = false;
        await rpc("/executive_dashboard/update_kpi", { kpi_id: this.props.kpi.id, values: { display_type: value } });
        if (this.props.onKpiUpdated) this.props.onKpiUpdated();
    }
    onClick() {
        if (this.state.showMenu || this.state.showNotes || this.state.showEditor) return;
        if (this.props.onDrillDown) this.props.onDrillDown(this.props.kpi);
    }

    // ── Notes ──
    async toggleNotes() {
        this.state.showMenu = false;
        if (this.state.showNotes) {
            this.state.showNotes = false;
            return;
        }
        this.state.notesLoading = true;
        this.state.showNotes = true;
        this.state.notes = await rpc("/executive_dashboard/notes/get", {
            kpi_id: this.props.kpi.id,
        });
        this.state.notesLoading = false;
    }

    onNoteInput(ev) {
        this.state.noteText = ev.target.value;
    }

    onNoteKeydown(ev) {
        if (ev.key === "Enter") this.submitNote();
    }

    async submitNote() {
        const text = this.state.noteText.trim();
        if (!text) return;
        const note = await rpc("/executive_dashboard/notes/create", {
            kpi_id: this.props.kpi.id, text,
        });
        this.state.notes.unshift(note);
        this.state.noteText = "";
    }

    // ── KPI Editor Modal ──
    openEditor() {
        this.state.showMenu = false;
        const k = this.props.kpi;
        this.state.editForm = {
            name: k.name || "",
            description: k.description || "",
            unit: k.unit || "",
            color: k.color || "#EFF6FF",
            target_value: k.target_value || 0,
            budget_value: k.budget_value || 0,
        };
        this.state.showEditor = true;
    }

    closeEditor() { this.state.showEditor = false; }

    async submitEditor() {
        const f = this.state.editForm;
        await rpc("/executive_dashboard/update_kpi", {
            kpi_id: this.props.kpi.id,
            values: {
                name: f.name,
                description: f.description,
                unit: f.unit,
                color: f.color,
                target_value: parseFloat(f.target_value) || 0,
                budget_value: parseFloat(f.budget_value) || 0,
            },
        });
        this.state.showEditor = false;
        if (this.props.onKpiUpdated) this.props.onKpiUpdated();
    }

    // ── Ziel & Budget ──
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

    async deleteNote(noteId) {
        await rpc("/executive_dashboard/notes/delete", { note_id: noteId });
        this.state.notes = this.state.notes.filter(n => n.id !== noteId);
    }
}
