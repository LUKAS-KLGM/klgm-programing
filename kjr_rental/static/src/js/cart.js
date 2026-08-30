/** @odoo-module **/
// Warenkorb: Artikel per JSON-Route hinzufügen, ohne Seitenreload.
//
// Die Route läuft bewusst über type='json2' (Odoo 19) und nicht über den
// JSON-RPC-Dispatcher: JSON-RPC beantwortet auch Ausnahmen mit HTTP 200 und legt
// den Fehler nur in den Rumpf. Ein abgestürzter Warenkorb sah dadurch im
// Zugriffsprotokoll wie ein Erfolg aus. json2 liefert echte Statuscodes, deshalb
// wird hier mit fetch() gearbeitet statt mit dem rpc()-Helfer.

/**
 * Fehlermeldung sichtbar im Seiteninhalt ausgeben statt per alert().
 * alert() blockiert die ganze Seite, taucht in keiner Konsole auf und ist für
 * jede Überwachung unsichtbar.
 */
function showCartError(btn, message) {
    const group = btn.closest(".input-group") || btn.parentElement;
    if (!group) {
        return;
    }
    let box = group.parentElement.querySelector(".kjr-cart-msg");
    if (!box) {
        box = document.createElement("div");
        box.className = "kjr-cart-msg alert alert-danger alert-sm small mt-2 mb-0";
        box.setAttribute("role", "alert");
        box.setAttribute("aria-live", "assertive");
        group.insertAdjacentElement("afterend", box);
    }
    box.textContent = message;
}

function clearCartError(btn) {
    const group = btn.closest(".input-group") || btn.parentElement;
    const box = group && group.parentElement.querySelector(".kjr-cart-msg");
    if (box) {
        box.remove();
    }
}

document.addEventListener("click", async (ev) => {
    const btn = ev.target.closest(".kjr-cart-add");
    if (!btn) {
        return;
    }
    ev.preventDefault();
    const itemId = parseInt(btn.dataset.itemId, 10);
    const qtyInput = document.getElementById("kjr_qty_" + itemId);
    const qty = qtyInput ? parseInt(qtyInput.value, 10) || 1 : 1;
    btn.disabled = true;
    clearCartError(btn);
    try {
        const response = await fetch("/service/verleih/cart/add", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ item_id: itemId, qty: qty }),
        });
        let result = null;
        try {
            result = await response.json();
        } catch {
            result = null;
        }
        if (!response.ok || (result && result.error)) {
            // 4xx trägt eine fachliche Meldung, 5xx nur eine technische —
            // dem Nutzer wird in beiden Fällen etwas Lesbares gezeigt.
            showCartError(btn, (result && result.error) ||
                "Der Artikel konnte nicht in den Warenkorb gelegt werden. Bitte später erneut versuchen.");
            return;
        }
        const badge = document.getElementById("kjr_cart_count");
        if (badge && result) {
            badge.textContent = result.cart_count;
        }
        btn.classList.remove("btn-primary");
        btn.classList.add("btn-success");
        btn.innerHTML = '<i class="fa fa-check me-1"></i>Hinzugefügt';
        setTimeout(() => {
            btn.classList.remove("btn-success");
            btn.classList.add("btn-primary");
            btn.innerHTML = '<i class="fa fa-cart-plus me-1"></i>In den Warenkorb';
        }, 1500);
    } catch {
        showCartError(btn, "Netzwerkfehler beim Hinzufügen zum Warenkorb. Bitte später erneut versuchen.");
    } finally {
        btn.disabled = false;
    }
});
