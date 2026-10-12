import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

/**
 * KJR-Spam-Schutz für Formulare, die nicht serverseitig mit Token gerendert
 * werden: Formulare aus dem Website-Builder (.s_website_form) und eigene
 * Formulare mit data-captcha (z. B. Spielmobil-Anfrage, data-captcha="kjr_spielmobil").
 *
 * - Holt beim Start ein signiertes Zeittoken über /service/antispam/token.
 * - Fügt Honeypot (kjr_hp) und Token (kjr_ts) per this.insert() ein. Die
 *   Elemente werden beim Beenden der Interaction wieder entfernt (auch beim
 *   Wechsel in den Bearbeitungsmodus) und landen damit nie in arch_db.
 * - Ist das Token älter als 20 Stunden, wird es beim nächsten Fokus im
 *   Formular neu geholt (Höchstalter serverseitig standardmäßig 24 Stunden).
 * - Bringt das Formular bereits ein kjr_ts mit (serverseitig gerendert, z. B.
 *   Teilnehmerdialog der Veranstaltungsanmeldung), tut die Interaction nichts.
 * - Die serverseitige Mindestzeit (min_seconds, Standard 2 s) läuft ab dem
 *   Laden der Seite. Das Token wird bewusst NICHT erst beim ersten Fokus bzw.
 *   bei der ersten Eingabe geholt: Das verkürzte die gemessene Zeit nur, und
 *   wer ohne Fokuswechsel absendet (Safari fokussiert Knöpfe beim Klick nicht,
 *   Autofill) oder während der Abruf noch läuft, hätte gar kein Token
 *   ('token_missing'). Vorausgefüllte, serverseitig gerenderte Dialoge sind
 *   serverseitig von der Mindestzeit ausgenommen (min_seconds_exempt).
 *
 * Ohne JavaScript fehlt das Token: solche Absendungen werden im Modus
 * "enforce" abgewiesen (siehe README.md).
 */

const TOKEN_ROUTE = "/service/antispam/token";
const REFRESH_AFTER_MS = 20 * 60 * 60 * 1000;
// Nach einem fehlgeschlagenen Abruf frühestens nach einer Minute erneut versuchen.
const RETRY_AFTER_MS = 60 * 1000;

export class KjrAntispam extends Interaction {
    static selector = ".s_website_form form, form.s_website_form, form[data-captcha]";
    dynamicContent = {
        _root: { "t-on-focusin": this.onFocusIn },
    };

    setup() {
        this.skip = !!this.el.querySelector("input[name='kjr_ts']");
        this.token = "";
        this.fetchedAt = 0;
        this.refreshing = false;
        this.tokenEl = null;
    }

    async willStart() {
        if (this.skip) {
            return;
        }
        await this.fetchToken();
    }

    start() {
        if (this.skip) {
            return;
        }
        const honeypotEl = document.createElement("div");
        honeypotEl.className = "o_kjr_hp";
        honeypotEl.setAttribute("aria-hidden", "true");
        const labelEl = document.createElement("label");
        labelEl.textContent = "Bitte leer lassen";
        const inputEl = document.createElement("input");
        inputEl.type = "text";
        inputEl.name = "kjr_hp";
        inputEl.value = "";
        inputEl.tabIndex = -1;
        inputEl.autocomplete = "off";
        labelEl.appendChild(inputEl);
        honeypotEl.appendChild(labelEl);

        this.tokenEl = document.createElement("input");
        this.tokenEl.type = "hidden";
        this.tokenEl.name = "kjr_ts";
        this.tokenEl.value = this.token;

        // this.insert entfernt beide Elemente beim Aufräumen der Interaction.
        this.insert(honeypotEl, this.el);
        this.insert(this.tokenEl, this.el);
    }

    async fetchToken() {
        let token = "";
        try {
            const result = await this.waitFor(rpc(TOKEN_ROUTE, {}, { silent: true }));
            token = (result && result.token) || "";
        } catch {
            token = "";
        }
        this.token = token;
        this.fetchedAt = token ? Date.now() : Date.now() - REFRESH_AFTER_MS + RETRY_AFTER_MS;
        if (this.tokenEl) {
            this.tokenEl.value = token;
        }
    }

    onFocusIn() {
        if (this.skip || this.refreshing) {
            return;
        }
        if (Date.now() - this.fetchedAt <= REFRESH_AFTER_MS) {
            return;
        }
        this.refreshing = true;
        this.fetchToken().finally(() => {
            this.refreshing = false;
        });
    }
}

registry
    .category("public.interactions")
    .add("kjr_website_antispam.antispam", KjrAntispam);
