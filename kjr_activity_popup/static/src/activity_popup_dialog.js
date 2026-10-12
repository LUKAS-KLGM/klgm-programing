import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

/**
 * Großes, gut lesbares Popup mit den fälligen/überfälligen Erinnerungen des
 * angemeldeten Benutzers. Je Eintrag: Öffnen / Erledigt / Später erinnern.
 */
export class KjrActivityPopupDialog extends Component {
    static template = "kjr_activity_popup.Dialog";
    static components = { Dialog };
    static props = {
        items: Array,
        more: { type: Number, optional: true },
        snoozeMinutes: Number,
        close: Function,
    };
    static defaultProps = { more: 0 };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            items: this.props.items.map((item) => ({ ...item })),
            busy: {},
        });
    }

    get title() {
        const count = this.state.items.length;
        // Neutral formuliert: das Popup zeigt Aktivitäten UND Aufgaben-Fristen.
        return count === 1
            ? _t("Erinnerung: 1 fälliger Eintrag")
            : _t("Erinnerung: %(count)s fällige Einträge", { count });
    }

    get snoozeLabel() {
        const minutes = this.props.snoozeMinutes;
        if (minutes % 60 === 0) {
            const hours = minutes / 60;
            return hours === 1
                ? _t("In 1 Std. erinnern")
                : _t("In %(hours)s Std. erinnern", { hours });
        }
        return _t("In %(minutes)s Min. erinnern", { minutes });
    }

    get snoozeAllLabel() {
        const minutes = this.props.snoozeMinutes;
        if (minutes % 60 === 0) {
            const hours = minutes / 60;
            return hours === 1
                ? _t("Alle in 1 Std. erinnern")
                : _t("Alle in %(hours)s Std. erinnern", { hours });
        }
        return _t("Alle in %(minutes)s Min. erinnern", { minutes });
    }

    dueLabel(item) {
        if (item.state === "today") {
            return _t("Heute fällig");
        }
        return item.days_overdue === 1
            ? _t("Seit 1 Tag überfällig")
            : _t("Seit %(days)s Tagen überfällig", { days: item.days_overdue });
    }

    iconClass(item) {
        const icon = /^fa-[a-z0-9-]+$/.test(item.icon || "") ? item.icon : "fa-tasks";
        return `fa ${icon}`;
    }

    /**
     * Eindeutige DOM-ID des Eintragstitels; der Listeneintrag ist darüber
     * beschriftet (aria-labelledby).
     */
    titleId(item) {
        return `o_kjr_ap_title_${item.kind}_${item.id}`;
    }

    /**
     * Zugänglicher Name der Knöpfe je Eintrag: sichtbarer Text plus Titel
     * („Öffnen: Rückruf“), damit Screenreader – auch in der Knopfliste –
     * sagen, zu welcher Erinnerung ein Knopf gehört. Der sichtbare Text steht
     * vorne (WCAG 2.5.3 „Label in Name“).
     */
    buttonLabel(action, item) {
        const label =
            action === "open"
                ? _t("Öffnen")
                : action === "done"
                ? _t("Erledigt")
                : this.snoozeLabel;
        return _t("%(label)s: %(title)s", { label, title: item.title });
    }

    _remove(item) {
        this.state.items = this.state.items.filter((i) => i.key !== item.key);
        if (!this.state.items.length) {
            this.props.close();
        }
    }

    _errorMessage(error) {
        return error?.data?.message || error?.message || _t("Unbekannter Fehler");
    }

    async _run(item, fn) {
        if (this.state.busy[item.key]) {
            return;
        }
        this.state.busy[item.key] = true;
        try {
            await fn();
        } catch (error) {
            this.notification.add(this._errorMessage(error), { type: "danger" });
        } finally {
            delete this.state.busy[item.key];
        }
    }

    async onOpen(item) {
        await this._run(item, async () => {
            const action = await this.orm.call("mail.activity", "kjr_popup_open", [
                item.kind,
                item.id,
            ]);
            // Aktion anstoßen, dann das Popup schließen (nicht auf doAction warten:
            // der Dialog ist danach zerstört, useService würde nie auflösen).
            this.action.doAction(action);
            this.props.close();
        });
    }

    async onDone(item) {
        await this._run(item, async () => {
            await this.orm.call("mail.activity", "kjr_popup_done", [item.kind, item.id]);
            this.notification.add(_t("„%(title)s“ ist erledigt.", { title: item.title }), {
                type: "success",
            });
            this._remove(item);
        });
    }

    async onSnooze(item) {
        await this._run(item, async () => {
            await this.orm.call("mail.activity", "kjr_popup_snooze", [[[item.kind, item.id]]]);
            this._remove(item);
        });
    }

    async onSnoozeAll() {
        const entries = this.state.items.map((item) => [item.kind, item.id]);
        try {
            await this.orm.call("mail.activity", "kjr_popup_snooze", [entries]);
            this.props.close();
        } catch (error) {
            this.notification.add(this._errorMessage(error), { type: "danger" });
        }
    }

    onShowAll() {
        this.action.doAction("mail.mail_activity_action_my", { clearBreadcrumbs: true });
        this.props.close();
    }
}
