# -*- coding: utf-8 -*-
"""Veranstaltung: Auswahl der Sign-Vorlage und Umschalten auf 'sign'.

Der Erweiterungspunkt ``_kjr_consent_mode`` liegt in kjr_event. Diese Brücke
liefert 'sign' nur, wenn
  1. kjr_event 'checkbox' ergibt (Einwilligung an der Veranstaltung verlangt),
  2. der Systemparameter ``kjr_event_sign.enabled`` wahr ist und
  3. eine GÜLTIGE Vorlage gefunden wird.
Sonst bleibt alles wie ohne Brücke (Rückfall auf 'checkbox', fail-safe).
"""
import logging

from odoo import api, fields, models
from odoo.tools.misc import str2bool

_logger = logging.getLogger(__name__)

PARAM_ENABLED = 'kjr_event_sign.enabled'
PARAM_DEFAULT_TEMPLATE = 'kjr_event_sign.default_template_id'
XMLID_DEFAULT_TEMPLATE = 'kjr_event_sign.sign_template_consent'


class EventEvent(models.Model):
    _inherit = 'event.event'

    kjr_consent_sign_template_id = fields.Many2one(
        'sign.template', string='Einwilligungsvorlage (Sign)',
        domain=[('active', '=', True)],
        help='Leer = Standardvorlage aus den Einstellungen.')

    # ------------------------------------------------------------------
    # Erweiterungspunkt aus kjr_event
    # ------------------------------------------------------------------
    def _kjr_consent_mode(self):
        mode = super()._kjr_consent_mode()
        if mode == 'checkbox' and self._kjr_consent_sign_template():
            return 'sign'
        return mode

    # ------------------------------------------------------------------
    # Vorlage
    # ------------------------------------------------------------------
    @api.model
    def _kjr_event_sign_enabled(self):
        """True, wenn "Einwilligung digital einholen" eingeschaltet ist."""
        value = self.env['ir.config_parameter'].sudo().get_param(PARAM_ENABLED)
        if not value:
            return False
        return str2bool(value, False)

    def _kjr_consent_sign_template(self):
        """Gültige Sign-Vorlage dieser Veranstaltung oder ein leeres Recordset.

        Reihenfolge: Vorlage an der Veranstaltung, sonst die Standardvorlage
        aus den Einstellungen, sonst die mitgelieferte Vorlage. Leer, solange
        die Brücke in den Einstellungen ausgeschaltet ist oder die gefundene
        Vorlage die Prüfung in ``_kjr_consent_template_ok`` nicht besteht.
        """
        self.ensure_one()
        Template = self.env['sign.template'].sudo()
        if not self._kjr_event_sign_enabled():
            return Template
        template = self.sudo().kjr_consent_sign_template_id
        if not template:
            raw = self.env['ir.config_parameter'].sudo().get_param(PARAM_DEFAULT_TEMPLATE)
            try:
                template = Template.browse(int(raw)).exists() if raw else Template
            except (TypeError, ValueError):
                template = Template
        if not template:
            template = self.env.ref(XMLID_DEFAULT_TEMPLATE, raise_if_not_found=False) or Template
        template = template.sudo()
        if not template or not self._kjr_consent_template_ok(template):
            return Template
        return template

    @api.model
    def _kjr_consent_template_ok(self, template, log=False):
        """Prüft, ob eine Vorlage für die Einwilligung taugt.

        Verlangt: aktiv, mindestens ein Dokument, GENAU eine Rolle über alle
        Felder (eine Unterschriftsanfrage hat bei uns genau einen Unterzeichner)
        und mindestens ein Unterschriftsfeld. Kein Abbruch.

        :param log: True nur an Stellen, die selten laufen und bei denen eine
                    Warnung gewollt ist (post_init_hook, Einstellungen). Die
                    Prüfung läuft sonst bei JEDEM Zugriff auf den nicht
                    gespeicherten Modus (``kjr_consent_mode``: Website-Dialog,
                    Erfolgsseite, Controller, ``kjr_sign_enabled`` je Anmeldung
                    in Listen und Formularen, Cron). Eine Warnung dort würde das
                    Protokoll mit derselben Meldung fluten; deshalb dann nur
                    DEBUG. Ins Protokoll kommt nur die Vorlagen-ID.
        """
        template = template.sudo()
        if not template:
            return False
        roles = template.sign_item_ids.responsible_id
        has_signature = any(
            item.type_id.item_type == 'signature' for item in template.sign_item_ids)
        ok = bool(template.active and template.document_ids
                  and len(roles) == 1 and has_signature)
        if not ok:
            _logger.log(
                logging.WARNING if log else logging.DEBUG,
                'KJR Einwilligung (Sign): Vorlage %s ist für die Einwilligung nicht '
                'geeignet (aktiv, Dokument, genau eine Rolle, Unterschriftsfeld nötig).',
                template.id)
        return ok

    # ------------------------------------------------------------------
    # Datenschutz: Anonymisierung (kjr_event, Befund K6)
    # ------------------------------------------------------------------
    @api.model
    def _kjr_purge_registration_copies(self, registrations):
        """Zusätzlich zu kjr_event: Unterschriftsanfragen der Anmeldungen lösen.

        Offene Anfragen werden storniert, alle Anfragen archiviert und die
        Verknüpfung an der Anmeldung geleert. Unterschriebene Anfragen samt
        Dokument und sign.log bleiben archiviert als Nachweis der Einwilligung
        erhalten; Odoo Sign lässt ihr Löschen ohnehin nicht zu.
        TODO(KJR): Aufbewahrungsfrist der unterschriebenen Einwilligungen
        festlegen (Löschkonzept), ebenso den Umgang mit den Eltern-Kontakten
        (Kategorie "KJR Erziehungsberechtigte").
        """
        res = super()._kjr_purge_registration_copies(registrations)
        regs = registrations.sudo().exists()
        requests = regs.with_context(active_test=False).mapped('kjr_sign_request_id')
        if requests:
            # Keine Storno-Notiz an der Anmeldung: kjr_event hat deren Chatter
            # gerade geleert, eine neue Nachricht wäre ein neuer Rest.
            requests = requests.with_context(kjr_sign_no_note=True)
            requests.filtered(lambda r: r.state == 'sent').cancel()
            requests.filtered('active').action_archive()
            regs.with_context(tracking_disable=True).write({'kjr_sign_request_id': False})
        return res
