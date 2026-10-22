/**
 * KJR Anmeldedialog (19.0.5.9.0, neu gefasst 19.0.5.11.0): Komfort im Formular.
 *
 * Rechnet aus dem eingegebenen Geburtsdatum das Alter am Beginntag der
 * Veranstaltung (data-kjr-event-start am Container .o_kjr_attendee_fields,
 * gleiche Formel wie event.event._kjr_age_at_begin) und schaltet je
 * Teilnehmer:in um (Termin 13.10.2026):
 *
 * - unter 18 oder noch kein Geburtsdatum: Block "Erziehungsberechtigte"
 *   sichtbar, Name/E-Mail/Telefon Pflicht; E-Mail/Telefon der Teilnehmer:in
 *   ausgeblendet und deaktiviert (wird nicht gesendet);
 * - ab 18: umgekehrt.
 * - Haken "Gleiche Anschrift wie Teilnehmer:in": blendet die Anschrift der
 *   Erziehungsberechtigten aus bzw. ein (dann Pflicht).
 * - Verfahren 'sign' (nur wenn eingeschaltet): steht im Namen der
 *   Erziehungsberechtigten derselbe Name wie bei der Teilnehmer:in, melden
 *   beide Felder einen Eingabefehler (serverseitig kjr_guardian_name_is_child).
 *
 * Nur Komfort: massgeblich ist die Vorpruefung im Controller
 * (KjrWebsiteEventController._kjr_form_precheck).
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
 * Vergleichsform fuer Namen wie im Controller (_kjr_norm_text).
 *
 * @param {string} value
 * @returns {string}
 */
function normName(value) {
    return (value || "").trim().split(/\s+/).join(" ").toLocaleLowerCase();
}

/**
 * Element ein-/ausblenden; darin liegende Eingaben dabei de-/aktivieren, damit
 * ausgeblendete Pflichtfelder das Absenden nicht blockieren.
 *
 * @param {HTMLElement} el
 * @param {boolean} visible
 * @param {boolean} required Eingaben bei Sichtbarkeit Pflicht
 */
function toggleBlock(el, visible, required) {
    el.classList.toggle("d-none", !visible);
    for (const input of el.querySelectorAll("input, select, textarea")) {
        if (input.type === "checkbox") {
            input.disabled = !visible;
            continue;
        }
        input.disabled = !visible;
        input.required = visible && required;
    }
}

export class KjrConsentFields extends Interaction {
    static selector = "#modal_attendees_registration";
    dynamicContent = {
        "input[name$='-birthdate']": {
            "t-on-change": this.onBirthdateChange,
            "t-on-input": this.onBirthdateChange,
        },
        "input[name$='-guardian_same_address']": {
            "t-on-change": this.onSameAddressChange,
        },
        // Name der Erziehungsberechtigten und Kernfeld "Name"
        // ("<zaehler>-name-<frage-id>", website_event.registration_event_question)
        "input[name$='-guardian_name'], input[name*='-name-']": {
            "t-on-input": this.onNameInput,
        },
    };

    start() {
        for (const input of this.el.querySelectorAll("input[name$='-birthdate']")) {
            this.updateFields(input);
        }
    }

    onBirthdateChange(ev) {
        this.updateFields(ev.currentTarget);
    }

    onSameAddressChange(ev) {
        const container = ev.currentTarget.closest(".o_kjr_attendee_fields");
        if (container) {
            // Sichtbarkeit des Blocks aus dem Alter ableiten (dieselbe Regel wie
            // updateFields), nicht aus den Anschriftsfeldern selbst.
            const birth = container.querySelector("input[name$='-birthdate']");
            const age = birth ? ageAt(birth.value, container.dataset.kjrEventStart) : null;
            this.updateAddress(container, !(age !== null && age >= 18));
        }
    }

    onNameInput(ev) {
        this.checkGuardianName(ev.currentTarget.name.split("-")[0]);
    }

    /**
     * Anschrift der Erziehungsberechtigten nur bei abweichender Anschrift.
     *
     * @param {HTMLElement} container
     * @param {boolean} guardianVisible
     */
    updateAddress(container, guardianVisible) {
        const same = container.querySelector("input[name$='-guardian_same_address']");
        const showAddress = guardianVisible && !!same && !same.checked;
        for (const el of container.querySelectorAll(".o_kjr_guardian_address")) {
            toggleBlock(el, showAddress, true);
        }
    }

    /**
     * @param {string} counter Zaehler der Teilnehmerin / des Teilnehmers
     */
    checkGuardianName(counter) {
        const guardianName = this.el.querySelector(`input[name='${counter}-guardian_name']`);
        if (!guardianName) {
            return;
        }
        const container = guardianName.closest(".o_kjr_attendee_fields");
        if (!container || container.dataset.kjrConsentMode !== "sign") {
            guardianName.setCustomValidity("");
            return;
        }
        const childName = this.el.querySelector(`input[name^='${counter}-name-']`);
        const guardian = normName(guardianName.value);
        const isChild =
            guardianName.required && !!guardian && !!childName && guardian === normName(childName.value);
        const message = isChild
            ? _t(
                  "Die Namen bei „Name Teilnehmer:in“ und beim Namen der Erziehungsberechtigten sind gleich. Bitte prüfen Sie beide Angaben."
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
    updateFields(input) {
        const container = input.closest(".o_kjr_attendee_fields");
        if (!container) {
            return;
        }
        const counter = input.name.split("-")[0];
        const age = ageAt(input.value, container.dataset.kjrEventStart);
        const isAdult = age !== null && age >= 18;

        for (const el of container.querySelectorAll(".o_kjr_guardian_block")) {
            if (el.classList.contains("o_kjr_guardian_address")) {
                continue;
            }
            el.classList.toggle("d-none", isAdult);
            for (const field of el.querySelectorAll("input, select, textarea")) {
                field.disabled = isAdult;
                if (field.classList.contains("o_kjr_guardian_required")) {
                    field.required = !isAdult;
                }
            }
        }
        this.updateAddress(container, !isAdult);
        for (const el of container.querySelectorAll(".o_kjr_adult_contact")) {
            toggleBlock(el, isAdult, true);
        }
        this.checkGuardianName(counter);
    }
}

registry.category("public.interactions").add("kjr_event.consent_fields", KjrConsentFields);
