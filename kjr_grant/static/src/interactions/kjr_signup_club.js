/**
 * KJR Vereinsregistrierung (19.0.16.0.0): Komfort im Registrierungsformular.
 *
 * Blendet die Vereinsfelder ein, sobald "für einen Verein / Verband" gewählt
 * ist, und macht den Vereinsnamen dann zur Pflicht (required). Bei
 * "als Privatperson" werden die Felder ausgeblendet und der Name ist frei.
 *
 * Nur Komfort: massgeblich ist die Pruefung im Controller
 * (KjrAuthSignupHome._prepare_signup_values, controllers/signup.py).
 */
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class KjrSignupClub extends Interaction {
    static selector = ".o_kjr_signup_type";
    dynamicContent = {
        "input[name='kjr_signup_type']": { "t-on-change": this.onTypeChange },
    };

    start() {
        this.onTypeChange();
    }

    onTypeChange() {
        const checked = this.el.querySelector("input[name='kjr_signup_type']:checked");
        const club = checked?.value === "club";
        this.el.querySelector(".o_kjr_club_fields")?.classList.toggle("d-none", !club);
        const name = this.el.querySelector("input[name='kjr_club_name']");
        if (name) {
            name.required = club;
        }
    }
}

registry.category("public.interactions").add("kjr_grant.signup_club", KjrSignupClub);
