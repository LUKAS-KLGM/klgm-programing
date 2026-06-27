/** @odoo-module **/
// Warenkorb: Artikel per JSON-Route hinzufügen, ohne Seitenreload.
import { rpc } from "@web/core/network/rpc";

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
    try {
        const result = await rpc("/service/verleih/cart/add", { item_id: itemId, qty: qty });
        if (result && result.error) {
            alert(result.error);
        } else if (result) {
            const badge = document.getElementById("kjr_cart_count");
            if (badge) {
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
        }
    } catch (e) {
        alert("Fehler beim Hinzufügen zum Warenkorb.");
    } finally {
        btn.disabled = false;
    }
});
