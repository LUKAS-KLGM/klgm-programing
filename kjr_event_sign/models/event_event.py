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
# Mitgelieferte Standardvorlage. Seit 19.0.1.1.0 die vorbefüllte Vorlage v2;
# v1 bleibt installiert (bereits versendete Anfragen verweisen darauf) und ist
# nur noch wählbar, nicht mehr Rückfall.
XMLID_DEFAULT_TEMPLATE = 'kjr_event_sign.sign_template_consent_v2'
XMLID_TEMPLATE_V1 = 'kjr_event_sign.sign_template_consent'
# Name von v1, wie ihn sign_template_data.xml ausliefert (noupdate, auf der
# Produktion so installiert), und der Name nach der Umstellung auf v2: v1 ist
# nicht mehr Standard; in den Auswahllisten (Einstellungen, Veranstaltung)
# soll sie nicht als aktuelle Standardvorlage erscheinen.
TEMPLATE_V1_SHIPPED_NAME = 'Einwilligung Erziehungsberechtigte (Standard)'
TEMPLATE_V1_LEGACY_NAME = 'Einwilligung Erziehungsberechtigte (alt, ohne Vorbefüllung)'
# Felder der Veranstaltung, aus denen das vorbefüllte Feld "Veranstaltung"
# der Vorlage v2 entsteht (event.registration.kjr_sign_event_label).
EVENT_LABEL_FIELDS = ('name', 'date_begin', 'date_end', 'date_tz')


class EventEvent(models.Model):
    _inherit = 'event.event'

    kjr_consent_sign_template_id = fields.Many2one(
        'sign.template', string='Einwilligungsvorlage (Sign)',
        domain=[('active', '=', True)],
        help='Leer = Standardvorlage aus den Einstellungen.')

    def write(self, vals):
        res = super().write(vals)
        if any(field in vals for field in EVENT_LABEL_FIELDS):
            # Name oder Termine geändert: offene Anfragen mit vorbefülltem Feld
            # "Veranstaltung" zeigen sonst den alten Stand (siehe
            # event.registration._kjr_sign_check_prefilled). Gesucht wird mit
            # sudo, geprüft und neu versendet unter dem aufrufenden Benutzer
            # (Grenze für den automatischen Neuversand).
            regs = self.env['event.registration'].sudo().search([
                ('event_id', 'in', self.ids), ('kjr_sign_state', '=', 'sent')])
            if regs:
                regs.with_env(self.env)._kjr_sign_check_prefilled()
        return res

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
        aus den Einstellungen, sonst die mitgelieferte Vorlage (seit
        19.0.1.1.0 die vorbefüllte Vorlage v2). Leer, solange
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
    # Umstellung auf die vorbefüllte Vorlage v2 (19.0.1.1.0)
    # ------------------------------------------------------------------
    @api.model
    def _kjr_sign_switch_default_template_v2(self):
        """Stellt die Standardvorlage v1 auf v2 um (Migration 19.0.1.1.0).

        * Systemparameter ``kjr_event_sign.default_template_id``: auf v2, wenn
          er leer ist, auf v1 zeigt oder auf eine nicht mehr vorhandene
          Vorlage. Eine andere, von der Geschäftsstelle gewählte Vorlage
          bleibt unverändert.
        * Veranstaltungen, deren ``kjr_consent_sign_template_id`` auf v1 zeigt
          (auch archivierte Veranstaltungen): auf v2.
        * Bereits versendete Unterschriftsanfragen bleiben unberührt: sie
          verweisen über ``template_id`` weiter auf v1.
        * v1 wird umbenannt (``_kjr_sign_rename_template_v1``), sofern sie noch
          den ausgelieferten Namen trägt.

        Idempotent. Ins Protokoll kommen nur IDs und Zähler.

        :return: dict mit ``param`` ('set', 'kept' oder 'missing_v2'),
                 ``events`` (Anzahl umgestellter Veranstaltungen) und
                 ``v1_renamed`` (bool)
        """
        result = {'param': 'missing_v2', 'events': 0, 'v1_renamed': False}
        v2 = self.env.ref(XMLID_DEFAULT_TEMPLATE, raise_if_not_found=False)
        if not v2:
            _logger.warning('KJR Einwilligung (Sign): Vorlage v2 fehlt, keine Umstellung.')
            return result
        v1 = self.env.ref(XMLID_TEMPLATE_V1, raise_if_not_found=False)
        ICP = self.env['ir.config_parameter'].sudo()
        raw = ICP.get_param(PARAM_DEFAULT_TEMPLATE)
        current = self.env['sign.template'].sudo()
        try:
            current = current.browse(int(raw)).exists() if raw else current
        except (TypeError, ValueError):
            current = current.browse()
        if not current or (v1 and current == v1):
            ICP.set_param(PARAM_DEFAULT_TEMPLATE, str(v2.id))
            result['param'] = 'set'
        else:
            result['param'] = 'kept'
        if v1:
            events = self.sudo().with_context(active_test=False).search(
                [('kjr_consent_sign_template_id', '=', v1.id)])
            if events:
                events.write({'kjr_consent_sign_template_id': v2.id})
            result['events'] = len(events)
        result['v1_renamed'] = self._kjr_sign_rename_template_v1()
        _logger.info(
            'KJR Einwilligung (Sign): Standardvorlage %s (Parameter: %s), '
            '%s Veranstaltung(en) von Vorlage %s auf %s umgestellt.',
            v2.id, result['param'], result['events'], v1.id if v1 else '-', v2.id)
        return result

    @api.model
    def _kjr_sign_rename_template_v1(self):
        """Benennt die alte Vorlage v1 um, damit sie in den Auswahllisten
        (Einstellungen > Standardvorlage, Veranstaltung > Einwilligungsvorlage)
        nicht mehr als Standard erscheint.

        Nur wenn v1 noch den ausgelieferten Namen trägt
        (``TEMPLATE_V1_SHIPPED_NAME``): einen von der Geschäftsstelle
        vergebenen Namen lässt die Methode stehen. Geändert wird nur der Name;
        Dokument, Felder und versendete Anfragen bleiben unverändert.
        Aufgerufen aus der Migration 19.0.1.1.0 (über
        ``_kjr_sign_switch_default_template_v2``) und bei einer Neuinstallation
        aus dem post_init_hook. Idempotent.

        :return: True, wenn umbenannt wurde
        """
        v1 = self.env.ref(XMLID_TEMPLATE_V1, raise_if_not_found=False)
        if not v1 or v1.sudo().name != TEMPLATE_V1_SHIPPED_NAME:
            return False
        v1.sudo().name = TEMPLATE_V1_LEGACY_NAME
        _logger.info('KJR Einwilligung (Sign): Vorlage %s (v1) umbenannt.', v1.id)
        return True

    # ------------------------------------------------------------------
    # Datenschutz: Anonymisierung (kjr_event, Befund K6)
    # ------------------------------------------------------------------
    @api.model
    def _kjr_purge_registration_copies(self, registrations):
        """Zusätzlich zu kjr_event: Unterschriftsanfragen der Anmeldungen räumen.

        Erfasst werden ALLE Anfragen der Anmeldungen, nicht nur die aktuelle
        (``kjr_sign_request_id``): "Erneut senden" und ein Adresswechsel
        hinterlassen frühere, stornierte Anfragen, die nur noch über
        ``reference_doc`` auf die Anmeldung zeigen.

        * Nie unterschriebene Anfragen (offen, storniert, abgelaufen,
          abgelehnt) werden nach dem Storno GELÖSCHT. Seit der Vorlage v2
          (19.0.1.1.0) trägt jede Anfrage schon beim Anlegen den Namen des
          Kindes und den Namen der/des Erziehungsberechtigten
          (sign.request.item.value der vorbefüllten Felder); als archivierter
          Rest überdauerten sie die Anonymisierung. Odoo Sign verbietet nur
          das Löschen unterschriebener Anfragen (``_unlink_if_not_signed``);
          sign.log und Werte fallen per Datenbank-Kaskade mit.
        * Unterschriebene Anfragen bleiben samt Dokument und sign.log
          archiviert als Nachweis der Einwilligung erhalten (nicht löschbar).
        * Die Verknüpfung an der Anmeldung wird geleert.
        Schlägt das Löschen fehl (Fehler im Protokoll, nur IDs), werden die
        Anfragen wie bisher archiviert; die Anonymisierung läuft weiter.
        TODO(KJR): Aufbewahrungsfrist der unterschriebenen Einwilligungen
        festlegen (Löschkonzept), ebenso den Umgang mit den Eltern-Kontakten
        (Kategorie "KJR Erziehungsberechtigte").
        """
        res = super()._kjr_purge_registration_copies(registrations)
        regs = registrations.sudo().exists()
        if not regs:
            return res
        SignRequest = self.env['sign.request'].sudo().with_context(active_test=False)
        requests = regs.with_context(active_test=False).mapped('kjr_sign_request_id')
        requests |= SignRequest.search([
            ('reference_doc', 'in', ['event.registration,%d' % reg.id for reg in regs])])
        if requests:
            # Keine Storno-Notiz an der Anmeldung: kjr_event hat deren Chatter
            # gerade geleert, eine neue Nachricht wäre ein neuer Rest.
            requests = requests.with_context(kjr_sign_no_note=True)
            requests.filtered(lambda r: r.state == 'sent').cancel()
            unsigned = requests.filtered(lambda r: r.state != 'signed')
            if unsigned:
                savepoint = self.env.cr.savepoint()
                try:
                    with savepoint:
                        unsigned.unlink()
                except Exception:  # noqa: BLE001 - die Anonymisierung hat Vorrang
                    _logger.exception(
                        'KJR Einwilligung (Sign): nicht unterschriebene Anfragen %s '
                        'konnten bei der Anonymisierung nicht gelöscht werden; sie '
                        'werden archiviert.', unsigned.ids)
            requests = requests.exists()
            requests.filtered('active').action_archive()
            regs.with_context(tracking_disable=True).write({'kjr_sign_request_id': False})
        return res
