import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { KjrActivityPopupDialog } from "./activity_popup_dialog";

/** Erste Prüfung kurz nach dem Laden des Backends (Oberfläche zuerst aufbauen). */
export const INITIAL_DELAY_MS = 4000;
/** Bus-Hinweise („neue fällige Aktivität“) werden gebündelt. */
export const BUS_DEBOUNCE_MS = 3000;
/** Rückkehr in den Tab löst höchstens einmal pro Minute eine Prüfung aus. */
export const VISIBILITY_MIN_GAP_MS = 60 * 1000;
const DEFAULT_POLL_MINUTES = 10;
/** Schlüssel, unter dem web_tour eine laufende Tour ablegt (web_tour/js/tour_state.js). */
const CURRENT_TOUR_KEY = "current_tour";

function isTourRunning() {
    try {
        return Boolean(browser.localStorage.getItem(CURRENT_TOUR_KEY));
    } catch {
        return false;
    }
}

/**
 * Zeigt fällige/überfällige Aktivitäten (und Aufgaben-Fristen) des
 * angemeldeten Benutzers als großes Popup:
 *  - beim Laden des Backends,
 *  - danach regelmäßig (Systemparameter kjr_activity_popup.poll_minutes,
 *    Standard 10 Minuten),
 *  - sofort, wenn über den Bus eine neue fällige Aktivität gemeldet wird.
 *
 * Geprüft wird nur im sichtbaren Tab; ein verdeckter Tab holt die Prüfung
 * nach, sobald er wieder sichtbar wird. Welche Einträge heute schon
 * angezeigt wurden, merkt sich der Server – über alle Tabs hinweg.
 */
export const kjrActivityPopupService = {
    dependencies: ["orm", "dialog", "bus_service"],

    start(env, { orm, dialog, bus_service: busService }) {
        if (!user.isInternalUser) {
            return;
        }

        let pollMinutes = DEFAULT_POLL_MINUTES;
        let pollTimer = null;
        let busTimer = null;
        let checking = false;
        let dialogOpen = false;
        let pending = false;
        let disabled = false;
        let lastCheck = 0;

        const isVisible = () => document.visibilityState !== "hidden";

        function schedulePoll() {
            browser.clearTimeout(pollTimer);
            pollTimer = browser.setTimeout(() => check(), pollMinutes * 60 * 1000);
        }

        async function check() {
            if (checking || dialogOpen) {
                return;
            }
            if (isTourRunning()) {
                // Während einer (automatisierten oder geführten) Tour kein Popup,
                // es würde die Tour-Schritte verdecken.
                schedulePoll();
                return;
            }
            if (!isVisible()) {
                pending = true;
                schedulePoll();
                return;
            }
            checking = true;
            pending = false;
            lastCheck = Date.now();
            try {
                const result = await orm.silent.call("mail.activity", "kjr_popup_fetch", []);
                pollMinutes = result.poll_minutes || DEFAULT_POLL_MINUTES;
                disabled = !result.enabled;
                if (result.enabled && result.items?.length) {
                    dialogOpen = true;
                    dialog.add(
                        KjrActivityPopupDialog,
                        {
                            items: result.items,
                            more: result.more || 0,
                            snoozeMinutes: result.snooze_minutes,
                        },
                        {
                            onClose: () => {
                                dialogOpen = false;
                                schedulePoll();
                            },
                        }
                    );
                }
            } catch {
                // Netzwerk-/Serverfehler: still beim nächsten Intervall erneut versuchen.
            } finally {
                checking = false;
                schedulePoll();
            }
        }

        busService.subscribe("mail.activity/updated", (payload) => {
            if (disabled || !payload?.activity_created) {
                return;
            }
            browser.clearTimeout(busTimer);
            busTimer = browser.setTimeout(() => check(), BUS_DEBOUNCE_MS);
        });

        document.addEventListener("visibilitychange", () => {
            if (!isVisible()) {
                return;
            }
            if (pending || Date.now() - lastCheck >= VISIBILITY_MIN_GAP_MS) {
                check();
            }
        });

        browser.setTimeout(() => check(), INITIAL_DELAY_MS);

        return { check };
    },
};

registry.category("services").add("kjr_activity_popup", kjrActivityPopupService);
