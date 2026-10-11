# -*- coding: utf-8 -*-
from odoo import api, models

KJR_SALE_PRINT_REPORT_NAME = (
    "(object.order_line.filtered('event_id') and "
    "(('Reservierungsbestätigung - %s' if object.state in ('draft', 'sent') else 'Anmeldebestätigung - %s') % object.name)) "
    "or (object.state in ('draft', 'sent') and 'Angebot - %s' % (object.name)) or 'Auftrag - %s' % (object.name)"
)


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    @api.model
    def _kjr_set_sale_print_report_name(self):
        """Dateiname des Angebots-/Auftrags-PDF fuer Kursanmeldungen. Das Feld
        ist uebersetzbar, deshalb in jeder aktiven Sprache setzen."""
        report = self.env.ref('sale.action_report_saleorder', raise_if_not_found=False)
        if not report:
            return
        for lang in self.env['res.lang'].get_installed():
            report.with_context(lang=lang[0]).print_report_name = KJR_SALE_PRINT_REPORT_NAME
