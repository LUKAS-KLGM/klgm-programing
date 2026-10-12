/**
 * B51: Client-Aktion "Scannen" im Verleih (Backend, OWL).
 *
 * Liest Inventaretiketten per Handykamera (QR-Code oder Code128), per
 * Handscanner (tippt den Code ins Eingabefeld und schickt Enter) oder per
 * Handeingabe. Zeigt den Gegenstand mit Lagerort und Lagerplatz ("wohin
 * zurückräumen?") und ordnet ihn im Modus "Rückgabe scannen" der ausgegebenen
 * Ausleihe zu (per Scan oder per Klick auf "Rückgabe zuordnen" in der Liste;
 * ein vom Artikel aus übergebener Gegenstand wird nur angezeigt, nie
 * automatisch zugeordnet). Die Rücknahme selbst schließt weiterhin der bestehende Schritt
 * "Rücknahme" im Vorgang ab (Checkliste, Rückgabevermerk, Kaution); der
 * Button "Ausleihe öffnen und Rücknahme abschließen" öffnet nur die Ausleihe.
 *
 * Barrierefreiheit: Die Rückmeldung steht in zwei dauerhaft vorhandenen
 * Live-Bereichen (role=status bzw. role=alert), in denen nur der Text wechselt.
 * Vor jeder Suche wird die Meldung geleert, damit auch eine gleichlautende
 * Meldung beim nächsten Scan erneut angesagt wird.
 *
 * Kamera: scanBarcode aus @web/core/barcode/barcode_dialog (Odoo-Community,
 * Teil von web._assets_core). Es nutzt die BarcodeDetector-API bzw. ZXing als
 * Rückfall und braucht weder stock_barcode noch Enterprise. Voraussetzung ist
 * HTTPS und die Kamerafreigabe im Browser bzw. in der Odoo-App.
 */
import { Component, onMounted, useRef, useState } from "@odoo/owl";
import { scanBarcode } from "@web/core/barcode/barcode_dialog";
import { isBarcodeScannerSupported } from "@web/core/barcode/barcode_video_scanner";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

export class KjrRentalScan extends Component {
    static template = "kjr_rental.RentalScan";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.inputRef = useRef("codeInput");

        const context = this.props.action.context || {};
        this.orderId = context.kjr_scan_order_id || false;
        this.orderName = context.kjr_scan_order_name || "";
        this.state = useState({
            mode: context.kjr_scan_mode || (this.orderId ? "return" : "show"),
            code: "",
            busy: false,
            result: null,
            feedback: null, // { type: "success" | "warning" | "danger", text }
            cameraSupported: isBarcodeScannerSupported(),
        });

        onMounted(async () => {
            if (context.kjr_scan_item_id) {
                // Vom Artikel aus geöffnet: nur anzeigen, NICHT automatisch
                // zuordnen. Die Client-Aktion wird mit demselben Kontext neu
                // aufgebaut (Breadcrumb zurück, Neuladen der Seite); eine
                // automatische Zuordnung würde dann jedes Mal ein weiteres
                // Stück als zurück zählen, ohne dass etwas gescannt wurde.
                await this.lookup({ itemId: context.kjr_scan_item_id, autoReturn: false });
                if (this.item && this.state.mode === "return" && !this.state.feedback) {
                    // Den Hinweis auf "Rückgabe zuordnen" nur geben, wenn es diesen
                    // Button unten auch gibt (ausgegebene Ausleihe mit offener
                    // Rückgabe); eine bloß reservierte Ausleihe hat ihn nicht.
                    const orders = this.state.result.orders || [];
                    this.state.feedback = orders.some((order) => order.can_return)
                        ? {
                              type: "info",
                              text: _t(
                                  "Zum Zuordnen unten bei der Ausleihe „Rückgabe zuordnen“ wählen oder das Etikett scannen."
                              ),
                          }
                        : this.noReturnFeedback(orders);
                }
            }
            this.focusInput();
        });
    }

    /** Fehler/Warnungen: role=alert (sofort angesagt). */
    isAlertFeedback(feedback) {
        return Boolean(feedback) && ["danger", "warning"].includes(feedback.type);
    }

    /** Meldung für den Live-Bereich role=alert (oder null). */
    get alertFeedback() {
        const feedback = this.state.feedback;
        return this.isAlertFeedback(feedback) ? feedback : null;
    }

    /** Erfolg/Info für den Live-Bereich role=status (oder null). */
    get statusFeedback() {
        const feedback = this.state.feedback;
        return feedback && !this.isAlertFeedback(feedback) ? feedback : null;
    }

    /** Zugänglicher Name je Ausleihe, damit die Buttons der Liste unterscheidbar sind. */
    returnButtonLabel(order) {
        return _t("Rückgabe zuordnen: %s", order.name);
    }

    openOrderButtonLabel(order) {
        return order.order_scan_complete
            ? _t("Ausleihe öffnen und Rücknahme abschließen: %s", order.name)
            : _t("Ausleihe öffnen: %s", order.name);
    }

    /** Gefundener Gegenstand des letzten Scans (oder null). */
    get item() {
        const result = this.state.result;
        return result && result.found ? result.item : null;
    }

    focusInput() {
        // Auf dem Handy öffnete der Fokus sofort die Bildschirmtastatur und
        // verdeckte den Kamera-Button; deshalb nur ohne Kamera fokussieren.
        if (this.inputRef.el && !this.state.cameraSupported) {
            this.inputRef.el.focus();
        }
    }

    setMode(mode) {
        this.state.mode = mode;
        this.state.feedback = null;
    }

    async onClickCamera() {
        let code = null;
        try {
            code = await scanBarcode(this.env, "environment");
        } catch (error) {
            this.notification.add(error.message || _t("Die Kamera konnte nicht gestartet werden."), {
                type: "danger",
            });
            return;
        }
        if (code) {
            if ("vibrate" in window.navigator) {
                window.navigator.vibrate(100);
            }
            await this.lookup({ raw: code });
        }
    }

    async onSubmit() {
        const code = (this.state.code || "").trim();
        if (!code) {
            return;
        }
        await this.lookup({ raw: code });
        this.state.code = "";
        if (this.inputRef.el) {
            this.inputRef.el.focus();
        }
    }

    onKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.onSubmit();
        }
    }

    async lookup({ raw = null, itemId = null, autoReturn = true, keepFeedback = false } = {}) {
        this.state.busy = true;
        if (!keepFeedback) {
            // Live-Bereich während der Suche leeren: so wird auch eine
            // gleichlautende Meldung des nächsten Scans wieder angesagt.
            this.state.feedback = null;
        }
        try {
            const result = await this.orm.call("kjr.rental.item", "kjr_scan_lookup", [], {
                raw,
                item_id: itemId,
                order_id: this.orderId,
            });
            this.state.result = result;
            if (!result.found) {
                this.state.feedback = { type: "warning", text: result.message };
                return;
            }
            if (autoReturn && this.state.mode === "return") {
                // Genau eine Ausleihe, in die das Stück zurückgehört: direkt
                // zuordnen. Bei mehreren entscheidet die Person in der Liste.
                const candidates = result.orders.filter((order) => order.can_return);
                if (candidates.length === 1) {
                    await this.registerReturn(candidates[0]);
                } else if (!candidates.length) {
                    this.state.feedback = this.noReturnFeedback(result.orders);
                } else {
                    this.state.feedback = {
                        type: "info",
                        text: _t("Mehrere Ausleihen möglich: bitte unten die richtige wählen."),
                    };
                }
            }
        } finally {
            this.state.busy = false;
        }
    }

    /**
     * Meldung, wenn sich der Gegenstand keiner Ausleihe als Rückgabe zuordnen
     * lässt. Ist die Ansicht auf eine Ausleihe beschränkt (Button "Rückgabe
     * scannen" in der Ausleihe), wird der Grund genannt: der Gegenstand gehört
     * nicht dazu, die Ausleihe ist nicht ausgegeben oder alle Stück sind schon
     * gescannt. Die Texte entsprechen kjr_scan_register_return im Server.
     */
    noReturnFeedback(orders) {
        orders = orders || [];
        if (this.orderId) {
            const order = orders.find((o) => o.id === Number(this.orderId));
            const orderName = (order && order.name) || this.orderName;
            if (!order) {
                return {
                    type: "warning",
                    text: _t("Der Gegenstand gehört nicht zur Ausleihe %s.", orderName),
                };
            }
            if (order.state !== "issued") {
                return {
                    type: "warning",
                    text: _t(
                        "Die Ausleihe %s ist nicht ausgegeben; eine Rückgabe kann nur für ausgegebene Ausleihen erfasst werden.",
                        orderName
                    ),
                };
            }
            if (order.scanned >= order.quantity) {
                return {
                    type: "warning",
                    text: _t(
                        "Alle %(qty)s Stück dieses Gegenstands sind für %(order)s bereits gescannt.",
                        { qty: order.quantity, order: orderName }
                    ),
                };
            }
        } else if (orders.some((o) => o.state === "issued")) {
            // Ausgegeben, aber alle Stück schon als zurück gescannt.
            return {
                type: "warning",
                text: _t(
                    "Alle ausgegebenen Stück dieses Gegenstands sind bereits als zurück gescannt."
                ),
            };
        }
        return {
            type: "warning",
            text: _t(
                "Für diesen Gegenstand ist keine ausgegebene Ausleihe mit offener Rückgabe vorhanden."
            ),
        };
    }

    async registerReturn(order) {
        const item = this.item;
        if (!item) {
            return;
        }
        this.state.busy = true;
        let response;
        try {
            response = await this.orm.call("kjr.rental.order", "kjr_scan_register_return", [
                [order.id],
            ], { item_id: item.id });
        } finally {
            this.state.busy = false;
        }
        // Meldung einmal setzen und beim Auffrischen stehen lassen: würde sie
        // zwischendurch geleert und neu gesetzt, sagte der Screenreader sie
        // unter Umständen nicht an (Scan ohne Blick aufs Display).
        this.state.feedback = {
            type: response.ok ? "success" : "danger",
            text: response.message,
        };
        // Anzeige mit dem neuen Scan-Stand auffrischen, ohne erneut zuzuordnen.
        await this.lookup({ itemId: item.id, autoReturn: false, keepFeedback: true });
    }

    openItem() {
        const item = this.item;
        if (item) {
            this.actionService.doAction({
                type: "ir.actions.act_window",
                res_model: "kjr.rental.item",
                res_id: item.id,
                views: [[false, "form"]],
            });
        }
    }

    openOrder(order) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "kjr.rental.order",
            res_id: order.id,
            views: [[false, "form"]],
        });
    }

    locationStyle(item) {
        // Farbe ist serverseitig als #RRGGBB geprüft (kjr.rental.location._check_color).
        const color = item.location_color || "#adb5bd";
        return `border-left: 0.75rem solid ${color};`;
    }
}

registry.category("actions").add("kjr_rental_scan", KjrRentalScan);
