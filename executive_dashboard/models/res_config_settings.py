from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ── AI ──
    ed_ai_provider = fields.Selection([
        ('anthropic', 'Anthropic (Claude)'),
        ('openai', 'OpenAI (GPT)'),
    ], string='AI Anbieter', default='anthropic',
        config_parameter='executive_dashboard.ai_provider')

    ed_ai_api_key = fields.Char(
        string='AI API Key',
        config_parameter='executive_dashboard.ai_api_key',
        groups='base.group_system')

    # ── Kontostand ──
    ed_bank_journal = fields.Selection(
        selection='_get_bank_journals',
        string='Bankjournal für Kontostand',
        config_parameter='executive_dashboard.bank_journal_id')

    @api.model
    def _get_bank_journals(self):
        journals = self.env['account.journal'].sudo().search([('type', '=', 'bank')])
        return [('0', 'Automatisch (erstes Bankkonto)')] + [(str(j.id), j.name) for j in journals]

    def action_test_ai_key(self):
        """Test the configured AI API key."""
        ICP = self.env['ir.config_parameter'].sudo()
        api_key = ICP.get_param('executive_dashboard.ai_api_key', '')
        provider = ICP.get_param('executive_dashboard.ai_provider', 'anthropic')

        if not api_key:
            return self._ai_test_notification('API Key fehlt', 'danger')

        try:
            import requests
            if provider == 'anthropic':
                resp = requests.post(
                    'https://api.anthropic.com/v1/messages',
                    headers={
                        'x-api-key': api_key,
                        'anthropic-version': '2023-06-01',
                        'content-type': 'application/json',
                    },
                    json={
                        'model': 'claude-sonnet-4-20250514',
                        'max_tokens': 16,
                        'messages': [{'role': 'user', 'content': 'Say OK'}],
                    },
                    timeout=10,
                )
                resp.raise_for_status()
            else:
                resp = requests.post(
                    'https://api.openai.com/v1/chat/completions',
                    headers={
                        'Authorization': f'Bearer {api_key}',
                        'Content-Type': 'application/json',
                    },
                    json={
                        'model': 'gpt-4o-mini',
                        'messages': [{'role': 'user', 'content': 'Say OK'}],
                        'max_tokens': 16,
                    },
                    timeout=10,
                )
                resp.raise_for_status()
            return self._ai_test_notification(
                f'{provider.title()} API Key funktioniert!', 'success')
        except Exception as e:
            return self._ai_test_notification(
                f'Fehler: {str(e)[:150]}', 'danger')

    def _ai_test_notification(self, message, notif_type):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'AI Key Test',
                'message': message,
                'type': notif_type,
                'sticky': False,
            },
        }
