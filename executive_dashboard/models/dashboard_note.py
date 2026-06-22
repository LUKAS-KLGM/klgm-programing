from odoo import api, fields, models


class DashboardKPINote(models.Model):
    _name = 'executive.dashboard.kpi.note'
    _description = 'KPI Notiz'
    _order = 'create_date desc'

    kpi_id = fields.Many2one('executive.dashboard.kpi', required=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', default=lambda self: self.env.user, required=True, readonly=True)
    text = fields.Text(required=True)
