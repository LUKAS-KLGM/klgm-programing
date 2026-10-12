/**
 * KJR Zuschussantrag (19.0.17.0.0): Live-Summen der Kostenaufstellung und
 * Abgleich mit der digitalen Belegliste.
 *
 * B15: Gesamteinnahmen, förderfähige Gesamtkosten und Fehlbetrag (Defizit)
 *      werden beim Tippen unter Punkt 6 angezeigt. Formel wie im Modell
 *      (kjr.grant.application._compute_deficit): Kosten minus Einnahmen,
 *      nicht unter 0.
 * B33: Ist "Belegliste hier digital ausfüllen" angehakt und enthält die
 *      Belegliste mindestens einen Betrag, werden die Belegsummen je Art
 *      (Einnahme/Ausgabe) mit den Summen aus Punkt 6 verglichen. Die Art
 *      eines Belegs wird wie im Controller bestimmt (_parse_receipt_rows):
 *      Ist eine Position gewählt, entscheidet sie; nur ohne Position zählt
 *      das Feld "Art". Die Einnahme-Positionen liefert der Server im
 *      Attribut data-kjr-income-categories an #rc_wrapper.
 *      Barrierefreiheit: Die sichtbaren Hinweisboxen sind keine
 *      Live-Regionen. Vorgelesen wird über [data-kjr-receipt-check-live],
 *      und zwar nur, wenn sich der Zustand (abweichend/übereinstimmend/
 *      inaktiv) ändert, entprellt statt bei jedem Tastendruck.
 *
 * Nur Anzeige: massgeblich sind die Berechnung im Modell und der Abgleich im
 * Backend. Die Belegzeilen werden vom Inline-Skript der Vorlage angehängt und
 * entfernt; deshalb hört die Interaction auf Ereignisse am Formular selbst
 * (Bubbling) statt an einzelnen Feldern.
 */
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

const EUR = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });

function toAmount(value) {
    const number = parseFloat(String(value || "").replace(",", "."));
    return Number.isFinite(number) && number > 0 ? number : 0;
}

function cents(value) {
    return Math.round(value * 100);
}

// Rückfall, falls das Attribut fehlt; Quelle ist kjr.grant.receipt.INCOME_CATEGORIES.
const FALLBACK_INCOME_CATEGORIES = ["tn_fees", "municipality", "association", "bjr", "income_other"];
// Wartezeit nach der letzten Eingabe, bevor eine Zustandsänderung vorgelesen wird.
const ANNOUNCE_DELAY = 1000;
const ANNOUNCEMENTS = {
    mismatch: "Hinweis: Belegliste und Kostenaufstellung weichen ab.",
    match: "Die Summen der Belegliste stimmen mit der Kostenaufstellung überein.",
    inactive: "",
};

export class KjrApplyTotals extends Interaction {
    static selector = "form.o_kjr_apply_form";
    dynamicContent = {
        _root: {
            "t-on-input": this.update,
            "t-on-change": this.update,
            // Zeile hinzufügen/entfernen: Die Inline-Handler der Schaltflächen
            // laufen vor dem Bubbling zum Formular, die Zeilen sind dann schon
            // angehängt bzw. entfernt.
            "t-on-click": this.onClick,
        },
    };

    setup() {
        const raw = this.el.querySelector("#rc_wrapper")?.dataset.kjrIncomeCategories || "";
        const categories = raw.split(" ").filter(Boolean);
        this.incomeCategories = categories.length ? categories : FALLBACK_INCOME_CATEGORIES;
        // Zustand, der zuletzt vorgelesen wurde bzw. beim Laden bestand.
        this.receiptState = null;
        this.announcedState = null;
        this.announceReceiptState = this.debounced(() => this.announce(), ANNOUNCE_DELAY);
    }

    start() {
        this.update();
        // Den Zustand beim Laden nicht vorlesen: Er ist sichtbar, und der
        // Nutzer hat noch nichts geändert.
        this.announcedState = this.receiptState;
    }

    onClick(ev) {
        if (ev.target.closest("button")) {
            this.update();
        }
    }

    sum(selector) {
        let total = 0;
        for (const input of this.el.querySelectorAll(selector)) {
            total += toAmount(input.value);
        }
        return total;
    }

    setText(selector, text) {
        const node = this.el.querySelector(selector);
        if (node) {
            node.textContent = text;
        }
    }

    update() {
        const income = this.sum("input[data-kjr-sum='income']");
        const cost = this.sum("input[data-kjr-sum='cost']");
        const deficit = Math.max(cost - income, 0);
        this.setText("[data-kjr-total='income']", EUR.format(income));
        this.setText("[data-kjr-total='cost']", EUR.format(cost));
        this.setText("[data-kjr-total='deficit']", EUR.format(deficit));
        this.updateReceiptCheck(income, cost);
    }

    updateReceiptCheck(income, cost) {
        const mismatchBox = this.el.querySelector("[data-kjr-receipt-check='mismatch']");
        const matchBox = this.el.querySelector("[data-kjr-receipt-check='match']");
        if (!mismatchBox || !matchBox) {
            return;
        }
        const digital = this.el.querySelector("#use_digital_receipts");
        let receiptIncome = 0;
        let receiptExpense = 0;
        let hasAmount = false;
        for (const row of this.el.querySelectorAll("#rc_rows .rc-row")) {
            const amount = toAmount(row.querySelector("input[name^='rc_amount_']")?.value);
            if (!amount) {
                continue;
            }
            hasAmount = true;
            if (this.receiptDirection(row) === "income") {
                receiptIncome += amount;
            } else {
                receiptExpense += amount;
            }
        }
        const active = Boolean(digital?.checked) && hasAmount;
        const parts = [];
        if (cents(receiptIncome) !== cents(income)) {
            parts.push(
                `Einnahmen: Belege ${EUR.format(receiptIncome)}, Kostenaufstellung ${EUR.format(income)}.`
            );
        }
        if (cents(receiptExpense) !== cents(cost)) {
            parts.push(
                `Ausgaben: Belege ${EUR.format(receiptExpense)}, Kostenaufstellung ${EUR.format(cost)}.`
            );
        }
        const mismatch = active && parts.length > 0;
        mismatchBox.classList.toggle("d-none", !mismatch);
        matchBox.classList.toggle("d-none", !active || mismatch);
        this.setText("[data-kjr-receipt-check-text]", parts.join(" "));
        this.receiptState = !active ? "inactive" : mismatch ? "mismatch" : "match";
        if (this.announcedState !== null && this.receiptState !== this.announcedState) {
            this.announceReceiptState();
        }
    }

    /**
     * Art eines Belegs wie im Controller (_parse_receipt_rows): Eine gewählte
     * Position bestimmt die Art; nur ohne Position gilt das Feld "Art".
     */
    receiptDirection(row) {
        const category = row.querySelector("select[name^='rc_category_']")?.value;
        if (category) {
            return this.incomeCategories.includes(category) ? "income" : "expense";
        }
        return row.querySelector("select[name^='rc_direction_']")?.value === "income"
            ? "income"
            : "expense";
    }

    /**
     * Schreibt eine kurze Zusammenfassung in die Live-Region, wenn sich der
     * Zustand seit der letzten Ansage geändert hat (entprellt aufgerufen).
     */
    announce() {
        if (this.receiptState === this.announcedState) {
            return;
        }
        this.announcedState = this.receiptState;
        this.setText("[data-kjr-receipt-check-live]", ANNOUNCEMENTS[this.receiptState] || "");
    }
}

registry.category("public.interactions").add("kjr_grant.apply_totals", KjrApplyTotals);
