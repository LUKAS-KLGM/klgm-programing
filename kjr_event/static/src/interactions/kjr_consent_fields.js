/**
 * KJR Einwilligung (19.0.5.9.0): Komfort im Anmeldedialog.
 *
 * Rechnet aus dem eingegebenen Geburtsdatum das Alter am Beginntag der
 * Veranstaltung (data-kjr-event-start am Container .o_kjr_attendee_fields,
 * gleiche Formel wie event.event._kjr_age_at_begin) und markiert die
 * Einwilligungsfelder derselben Teilnehmerin bzw. desselben Teilnehmers:
 *
 * - Verfahren 'checkbox': das Haekchen "Einwilligung liegt vor" wird fuer
 *   Minderjaehrige zum Pflichtfeld (required) und sonst wieder freigegeben.
 * - Verfahren 'sign': das Feld "E-Mail Erziehungsberechtigte/r" wird
 *   hervorgehoben, aber NICHT Pflicht (leer greift die Anmelde-E-Mail).
 *
 * Nur Komfort: massgeblich ist die Vorpruefung im Controller
 * (KjrWebsiteEventController._kjr_consent_precheck).
 */
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

/**
 * Alter in vollen Jahren am Stichtag; null bei fehlenden oder ungueltigen Daten.
 *
 * @param {string} birthdate ISO-Datum JJJJ-MM-TT
 * @param {string} start ISO-Datum JJJJ-MM-TT
 * @returns {number|null}
 */
function ageAt(birthdate, start) {
    const pattern = /^(\d{4})-(\d{2})-(\d{2})$/;
    const bd = pattern.exec(birthdate || "");
    const st = pattern.exec(start || "");
    if (!bd || !st) {
        return null;
    }
    const [bdYear, bdMonth, bdDay] = bd.slice(1).map(Number);
    const [stYear, stMonth, stDay] = st.slice(1).map(Number);
    const beforeBirthday = stMonth < bdMonth || (stMonth === bdMonth && stDay < bdDay);
    return stYear - bdYear - (beforeBirthday ? 1 : 0);
}

export class KjrConsentFields extends Interaction {
    static selector = "#modal_attendees_registration";
    dynamicContent = {
        "input[name$='-birthdate']": {
            "t-on-change": this.onBirthdateChange,
            "t-on-input": this.onBirthdateChange,
        },
    };

    start() {
        for (const input of this.el.querySelectorAll("input[name$='-birthdate']")) {
            this.updateConsentFields(input);
        }
    }

    /**
     * @param {Event} ev
     */
    onBirthdateChange(ev) {
        this.updateConsentFields(ev.currentTarget);
    }

    /**
     * @param {HTMLInputElement} input Geburtsdatumsfeld "<zaehler>-birthdate"
     */
    updateConsentFields(input) {
        const container = input.closest(".o_kjr_attendee_fields");
        if (!container) {
            return;
        }
        const counter = input.name.split("-")[0];
        const mode = container.dataset.kjrConsentMode;
        const age = ageAt(input.value, container.dataset.kjrEventStart);
        const isMinor = age !== null && age < 18;

        if (mode === "checkbox") {
            const checkbox = container.querySelector(
                `input[name='${counter}-parental_consent'][data-kjr-consent-checkbox]`
            );
            if (checkbox) {
                checkbox.required = isMinor;
            }
        } else if (mode === "sign") {
            const guardianEmail = container.querySelector(
                `input[name='${counter}-guardian_email']`
            );
            if (guardianEmail) {
                guardianEmail.classList.toggle("border-primary", isMinor);
                guardianEmail.classList.toggle("border-2", isMinor);
            }
            const hint = container.querySelector(".o_kjr_consent_sign_hint");
            if (hint) {
                hint.classList.toggle("fw-bold", isMinor);
            }
        }
    }
}

registry.category("public.interactions").add("kjr_event.consent_fields", KjrConsentFields);
