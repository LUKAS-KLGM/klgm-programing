/** @odoo-module **/

import { registry } from "@web/core/registry";

// Helper: select an option in a plain HTML <select> by option value and fire change
function selectByValue(sel, value) {
    sel.value = value;
    sel.dispatchEvent(new Event("change", { bubbles: true }));
}

registry.category("web_tour.tours").add("executive_dashboard_tour", {
    url: "/odoo",
    steps: () => [

        // ── 1. Open Controlling app ───────────────────────────────────────────
        {
            trigger: ".o_app[data-menu-xmlid='executive_dashboard.menu_executive_dashboard_root']",
            content: "Open the Controlling app",
            run: "click",
        },

        // ── 2. Dashboard loaded with KPI cards ────────────────────────────────
        {
            trigger: ".ed-kpi-card",
            content: "KPI cards are visible — app loaded without JS errors",
        },

        // ── 3. Change period to This Year ─────────────────────────────────────
        {
            trigger: ".ed-header-right > select.ed-period-select:last-of-type",
            content: "Change period filter to This Year",
            run(helpers) {
                selectByValue(helpers.anchor, "this_year");
            },
        },

        // ── 4. Data refreshes after period change ─────────────────────────────
        {
            trigger: ".ed-kpi-card",
            content: "KPI cards still visible after period change",
        },

        // ── 5. Change comparison mode to Previous Year ────────────────────────
        {
            trigger: ".ed-header-right > select.ed-period-select:first-of-type",
            content: "Change comparison mode to Previous Year",
            run(helpers) {
                selectByValue(helpers.anchor, "previous_year");
            },
        },

        {
            trigger: ".ed-kpi-card",
            content: "KPI cards visible after comparison change",
        },

        // ── 6. Refresh button ─────────────────────────────────────────────────
        {
            trigger: ".ed-refresh-btn .fa-refresh",
            content: "Click manual refresh button",
            run: "click",
        },

        {
            trigger: ".ed-kpi-card",
            content: "Data visible after manual refresh",
        },

        // ── 7. KPI card context menu — open ───────────────────────────────────
        {
            trigger: ".ed-kpi-card .ed-kpi-menu-btn",
            content: "Open KPI card context menu (⋮)",
            run: "click",
        },

        {
            trigger: ".ed-kpi-card .ed-chart-menu .ed-menu-item",
            content: "KPI context menu is open and has items",
        },

        // ── 8. Switch KPI display to Bar chart ────────────────────────────────
        {
            trigger: ".ed-kpi-card .ed-chart-menu .ed-menu-item .fa-bar-chart",
            content: "Switch this KPI to Bar chart display",
            run: "click",
        },

        // ── 9. Card is now a chart card ───────────────────────────────────────
        {
            trigger: ".ed-chart-card",
            content: "KPI is now displayed as a chart",
        },

        // ── 10. Chart card context menu — open ────────────────────────────────
        {
            trigger: ".ed-chart-card .ed-chart-menu-btn",
            content: "Open chart card context menu (⋮)",
            run: "click",
        },

        {
            trigger: ".ed-chart-card .ed-chart-menu",
            content: "Chart context menu is open",
        },

        // ── 11. Switch chart back to Scorecard ────────────────────────────────
        {
            trigger: ".ed-chart-card .ed-chart-menu .ed-menu-item .fa-credit-card",
            content: "Switch back to scorecard display",
            run: "click",
        },

        {
            trigger: ".ed-kpi-grid .ed-kpi-card",
            content: "KPI restored to scorecard",
        },

        // ── 12. Dark mode toggle ──────────────────────────────────────────────
        {
            trigger: ".ed-header-right .ed-refresh-btn .fa-moon-o",
            content: "Enable dark mode",
            run: "click",
        },

        {
            trigger: ".ed-container.ed-dark",
            content: "Dark mode is active",
        },

        {
            trigger: ".ed-header-right .ed-refresh-btn .fa-sun-o",
            content: "Disable dark mode",
            run: "click",
        },

        {
            trigger: ".ed-container:not(.ed-dark)",
            content: "Light mode restored",
        },

        // ── 13. Config menu → Industry Templates dialog ───────────────────────
        {
            trigger: ".ed-config-wrap .ed-refresh-btn",
            content: "Open configuration menu",
            run: "click",
        },

        {
            trigger: ".ed-config-wrap .ed-export-item .fa-magic",
            content: "Click Industry Templates",
            run: "click",
        },

        {
            trigger: ".ed-modal .ed-template-grid",
            content: "Industry Templates dialog is open with template cards",
        },

        {
            trigger: ".ed-modal-close",
            content: "Close Templates dialog",
            run: "click",
        },

        // ── 14. Config menu → KPI Builder ─────────────────────────────────────
        {
            trigger: ".ed-config-wrap .ed-refresh-btn",
            content: "Open configuration menu again",
            run: "click",
        },

        {
            trigger: ".ed-config-wrap .ed-export-item .fa-plus",
            content: "Click Add KPI to open KPI Builder",
            run: "click",
        },

        {
            trigger: ".ed-modal-builder",
            content: "KPI Builder dialog is open",
        },

        {
            trigger: ".ed-modal-builder .ed-btn-secondary",
            content: "Cancel KPI Builder without saving",
            run: "click",
        },

        // ── 15. Create Dashboard dialog ───────────────────────────────────────
        {
            trigger: "select.ed-dashboard-select",
            content: "Select '+ Create new...' from dashboard selector",
            run(helpers) {
                selectByValue(helpers.anchor, "__new__");
            },
        },

        {
            trigger: ".ed-modal-creator",
            content: "Dashboard Creator dialog is open",
        },

        {
            trigger: ".ed-modal-creator input[type='text']",
            content: "Type a test dashboard name",
            run: "fill Tour Test",
        },

        {
            trigger: ".ed-modal-creator .ed-creator-kpi-list .ed-creator-kpi-item:first-child",
            content: "Select the first KPI in the list",
            run: "click",
        },

        {
            trigger: ".ed-modal-creator .ed-btn-secondary",
            content: "Cancel — do not create the dashboard",
            run: "click",
        },

        // ── 16. Export menu ───────────────────────────────────────────────────
        {
            trigger: ".ed-export-wrap .ed-refresh-btn",
            content: "Open export menu",
            run: "click",
        },

        {
            trigger: ".ed-export-wrap .ed-export-menu",
            content: "Export menu is visible with CSV and PNG options",
        },

        {
            trigger: ".ed-export-wrap .ed-export-item .fa-file-text-o",
            content: "Export data as CSV",
            run: "click",
        },

        // ── 17. Favorite (default dashboard) toggle ───────────────────────────
        {
            trigger: ".ed-favorite-btn",
            content: "Toggle dashboard as default/favorite",
            run: "click",
        },

        {
            trigger: ".ed-favorite-btn.ed-fav-is-active",
            content: "Dashboard is now set as default (star filled)",
        },

        // Revert favorite
        {
            trigger: ".ed-favorite-btn.ed-fav-is-active",
            content: "Remove default dashboard setting",
            run: "click",
        },

        // ── 18. Final state: dashboard still operational ──────────────────────
        {
            trigger: ".ed-kpi-card",
            content: "Tour complete — dashboard is stable with KPI cards visible",
        },

    ],
});
