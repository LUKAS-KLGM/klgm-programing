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
 * - Verfahren 'sign': das Feld "E-Mail der/des Erziehungsberechtigten" wird
 *   hervorgehoben, aber NICHT Pflicht (leer greift die Anmelde-E-Mail).
 *   Das Feld "Name der/des Erziehungsberechtigten" wird fuer Minderjaehrige
 *   Pflichtfeld (required, Stern sichtbar; 19.0.5.10.0): der Name wird in das
 *   Einwilligungsformular uebernommen. Steht dort derselbe Name wie im
 *   Kernfeld "Name des Kindes / Teilnehmer/in" (gemeldeter Fall), melden
 *   BEIDE Felder einen Eingabefehler (setCustomValidity), weil nicht
 *   feststeht, welches falsch ist; serverseitig kjr_guardian_name_is_child.
 *
 * Nur Komfort: massgeblich ist die Vorpruefung im Controller
 * (KjrWebsiteEventController._kjr_consent_precheck).
 */
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

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

/**
 * Vergleichsform fuer Namen wie im Controller (_kjr_norm_text): Gross-/
 * Kleinschreibung und Mehrfach-Leerraum egal.
 *
 * @param {string} value
 * @returns {string}
 */
function normName(value) {
    return (value || "").trim().split(/\s+/).join(" ").toLocaleLowerCase();
}

export class KjrConsentFields extends Interaction {
    static selector = "#modal_attendees_registration";
    dynamicContent = {
        "input[name$='-birthdate']": {
            "t-on-change": this.onBirthdateChange,
            "t-on-input": this.onBirthdateChange,
        },
        // Name der/des Erziehungsberechtigten und Kernfeld "Name"
        // ("<zaehler>-name-<frage-id>", website_event.registration_event_question)
        "input[name$='-guardian_name'], input[name*='-name-']": {
            "t-on-input": this.onNameInput,
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
     * @param {Event} ev
     */
    onNameInput(ev) {
        this.checkGuardianName(ev.currentTarget.name.split("-")[0]);
    }

    /**
     * Markiert die Felder "Name des Kindes / Teilnehmer/in" und "Name der/des
     * Erziehungsberechtigten" derselben Person als fehlerhaft, wenn der Name
     * der Erziehungsberechtigten Pflicht ist (Verfahren 'sign', minderjaehrig)
     * und beide denselben Namen enthalten. Beide Felder, weil nicht
     * feststeht, welches falsch ist (gleicher Wortlaut wie die Meldung zu
     * kjr_guardian_name_is_child auf der Anmeldeseite).
     *
     * @param {string} counter Zaehler der Teilnehmerin / des Teilnehmers
     */
    checkGuardianName(counter) {
        const guardianName = this.el.querySelector(`input[name='${counter}-guardian_name']`);
        if (!guardianName) {
            return;
        }
        const childName = this.el.querySelector(`input[name^='${counter}-name-']`);
        const guardian = normName(guardianName.value);
        const isChild =
            guardianName.required && !!guardian && !!childName && guardian === normName(childName.value);
        const message = isChild
            ? _t(
                  "Die Namen bei „Name des Kindes / Teilnehmer/in“ und „Name der/des Erziehungsberechtigten“ sind gleich. Bitte prüfen Sie beide Angaben."
              )
            : "";
        guardianName.setCustomValidity(message);
        if (childName) {
            childName.setCustomValidity(message);
        }
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
            const guardianName = container.querySelector(
                `input[name='${counter}-guardian_name']`
            );
            if (guardianName) {
                guardianName.required = isMinor;
                this.checkGuardianName(counter);
            }
            const guardianNameStar = container.querySelector(".o_kjr_guardian_name_required");
            if (guardianNameStar) {
                guardianNameStar.classList.toggle("d-none", !isMinor);
            }
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
