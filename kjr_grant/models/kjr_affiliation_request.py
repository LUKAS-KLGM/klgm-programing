# -*- coding: utf-8 -*-
"""Vereinsregistrierung: Prüfung der Vereinszugehörigkeit durch die Geschäftsstelle.

ZWECK
─────
Bei der Konto-Registrierung auf der Website (/web/signup) wählt die Person
„als Privatperson“ oder „für einen Verein / Verband“. Wer sich für einen Verein
registriert, bekommt sofort ein nutzbares PERSÖNLICHES Konto. Die Zuordnung zum
Verband (und damit jedes Vereinsrecht) entsteht erst, wenn die Geschäftsstelle
die Zugehörigkeit genehmigt. Dieser Datensatz hält Antrag, Entscheidung und
Nachweis fest.

KERNPRINZIP (Rechte)
────────────────────
Alle Vereinsrechte hängen am commercial partner des Benutzers: am Flag
``commercial_partner_id.is_kjr_member`` (Verbandsportal /my/verband,
Mitgliedspreise in kjr_rental und kjr_facility) bzw. an jedem Mitgliedsverband
im Teilbaum ``child_of commercial_partner_id`` (Zuschussanträge und deren
Record Rules; Maßstab res.partner._kjr_grants_member_rights). Eine freie Registrierung ohne Token legt einen Partner OHNE
``parent_id`` an (auth_signup/models/res_users.py, ``signup`` und
``_create_user_from_template``); der Partner ist sein eigener commercial
partner und hat damit keine Rechte.

Die Genehmigung ist ausschließlich das Setzen von ``parent_id`` durch die
Geschäftsstelle. Der Status (beantragt / genehmigt / abgelehnt) dient der
Buchführung, dem Nachweis und der Anzeige im Portal. KEINE Rechteprüfung liest
den Status, und keine soll ihn lesen.

Entscheidungen laufen ausschließlich über ``_kjr_do_approve`` und
``_kjr_do_reject`` (die Assistenten rufen genau diese Methoden). Status,
Zuordnung und Ablehnungsgrund sind gegen direktes Schreiben gesperrt
(``write``); Vereinsangaben und Firma nur bis zur Entscheidung änderbar.
"""
import logging
from datetime import timedelta

from markupsafe import Markup, escape

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)

ACTIVITY_TYPE = 'mail.mail_activity_data_todo'      # mail/data/mail_activity_type_data.xml
ACTIVITY_SUMMARY = 'Vereinszugehörigkeit prüfen'      # Duplikatsschutz über summary
PARAM_RESPONSIBLE = 'kjr_grant.affiliation_responsible_user_id'
PARAM_RETENTION = 'kjr_grant.affiliation_rejected_retention_days'
DEFAULT_RETENTION_DAYS = 180
# Felder, die nur die Entscheidungsmethoden (sudo) setzen dürfen
PROTECTED_FIELDS = frozenset({'state', 'target_partner_id', 'date_decided',
                              'decided_by_id', 'origin', 'partner_id', 'user_id',
                              'rejection_reason'})
# Angaben, die bis zur Entscheidung korrigierbar sind und danach zum Nachweis
# gehören (Datenauskunft Art. 15, Ablehnungsgrund im Portal, company_id als
# Absender und Firmenname der Mails).
LOCKED_AFTER_DECISION = frozenset({'requested_name', 'requested_function',
                                   'requested_place', 'company_id'})


class KjrAffiliationRequest(models.Model):
    _name = 'kjr.affiliation.request'
    _description = 'Vereinsregistrierung'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_requested desc, id desc'

    partner_id = fields.Many2one(
        'res.partner', string='Person (Kontakt)', required=True, index=True,
        ondelete='cascade', tracking=True,
    )
    user_id = fields.Many2one(
        'res.users', string='Benutzerkonto', ondelete='set null', readonly=True,
    )
    partner_email = fields.Char(related='partner_id.email', string='E-Mail')
    # Quelle für Absender und Firmenname der Mails (White-Label).
    company_id = fields.Many2one(
        'res.company', string='Firma', required=True,
        default=lambda self: self.env.company,
    )
    requested_name = fields.Char('Angegebener Verein / Verband', required=True)
    requested_function = fields.Char('Funktion im Verein')
    requested_place = fields.Char('Ort / Anschrift (Angabe)')
    state = fields.Selection(
        [('requested', 'Beantragt'), ('approved', 'Genehmigt'), ('rejected', 'Abgelehnt')],
        string='Status', required=True, default='requested', index=True, tracking=True,
    )
    origin = fields.Selection(
        [('signup', 'Registrierung'), ('backend', 'Geschäftsstelle'),
         ('migration', 'Bestandsübernahme')],
        string='Herkunft', default='backend', readonly=True,
    )
    target_partner_id = fields.Many2one(
        'res.partner', string='Zugeordnete Organisation',
        domain=[('is_company', '=', True)], ondelete='set null', readonly=True,
        tracking=True,
    )
    target_is_member = fields.Boolean(
        related='target_partner_id.is_kjr_member', string='KJR-Mitgliedsverband',
    )
    # Bewusst OHNE tracking: der Grund wird mit dem Satz gelöscht (Cron unten);
    # ein Tracking-Eintrag würde ihn im Verlauf doppelt aufbewahren.
    rejection_reason = fields.Text('Ablehnungsgrund')
    date_requested = fields.Datetime(
        'Beantragt am', default=fields.Datetime.now, readonly=True,
    )
    date_decided = fields.Datetime('Entschieden am', readonly=True)
    decided_by_id = fields.Many2one('res.users', string='Entschieden von', readonly=True)
    partner_already_linked = fields.Boolean(
        string='Bereits zugeordnet', compute='_compute_partner_already_linked',
    )

    _one_open_per_partner = models.UniqueIndex(
        "(partner_id) WHERE state = 'requested'",
        'Für diese Person liegt bereits eine offene Vereinsregistrierung vor.',
    )

    # ── Berechnungen und Prüfungen ──────────────────────────────────────────

    @api.depends('partner_id.name', 'requested_name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s / %s' % (rec.partner_id.name or '', rec.requested_name or '')

    @api.depends('partner_id', 'partner_id.commercial_partner_id')
    def _compute_partner_already_linked(self):
        for rec in self:
            partner = rec.partner_id
            rec.partner_already_linked = bool(
                partner and partner.commercial_partner_id != partner)

    @api.constrains('state', 'target_partner_id')
    def _check_approved_has_target(self):
        for rec in self:
            if rec.state == 'approved' and not rec.target_partner_id:
                raise ValidationError(_(
                    'Eine genehmigte Vereinsregistrierung braucht eine zugeordnete Organisation.'))

    @api.constrains('partner_id')
    def _check_partner_is_person(self):
        for rec in self:
            if rec.partner_id.is_company:
                raise ValidationError(_(
                    'Eine Vereinsregistrierung gehört zu einer Person, nicht zu einer Organisation.'))

    # ── Schreibschutz ───────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            for vals in vals_list:
                for key in ('state', 'target_partner_id', 'date_decided',
                            'decided_by_id', 'origin', 'user_id', 'rejection_reason'):
                    vals.pop(key, None)
                partner = self.env['res.partner'].sudo().browse(vals.get('partner_id'))
                if partner.exists():
                    vals['user_id'] = partner.with_context(
                        active_test=False).user_ids[:1].id or False
        records = super().create(vals_list)
        if not self.env.su:
            # Backend-Anlage durch die Geschäftsstelle: gleiche Aktivität wie beim Signup.
            records._kjr_notify_office()
        return records

    def write(self, vals):
        if not self.env.su:
            if PROTECTED_FIELDS.intersection(vals):
                raise AccessError(_(
                    'Status und Zuordnung einer Vereinsregistrierung ändert nur die '
                    'Entscheidung der Geschäftsstelle (Genehmigen / Ablehnen).'))
            if (LOCKED_AFTER_DECISION.intersection(vals)
                    and self.filtered(lambda r: r.state != 'requested')):
                raise AccessError(_(
                    'Die Angaben einer entschiedenen Vereinsregistrierung sind Teil '
                    'des Nachweises und können nicht mehr geändert werden.'))
        return super().write(vals)

    # ── Anlage aus der Registrierung und Benachrichtigung ───────────────────

    @api.model
    def _kjr_create_from_signup(self, user, data):
        """Antrag aus der Registrierung. Läuft im Savepoint aus
        res.users._signup_create_user (models/res_users.py).

        with_user(SUPERUSER_ID): env.user ist beim Signup der Public-User; ohne
        Wechsel wären Erstellungsnotiz, Follower und Aktivitätsbenachrichtigung
        dem Public-User zugeordnet. SUPERUSER_ID setzt zugleich env.su, die
        geschützten Felder (origin, user_id) bleiben also erhalten.
        """
        Request = self.with_user(SUPERUSER_ID).with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True)
        req = Request.create({
            'partner_id': user.partner_id.id,
            'user_id': user.id,
            'company_id': user.company_id.id or self.env.company.id,
            'requested_name': data['name'],
            'requested_function': data.get('function') or False,
            'requested_place': data.get('place') or False,
            'origin': 'signup',
        })
        req._kjr_notify_office()
        return req

    def _kjr_office_responsible(self):
        """Zuständige Person der Geschäftsstelle für neue Vereinsregistrierungen.

        Jede Kandidatin muss aktiv, intern und Mitglied von group_kjr_reviewer
        sein: mail.activity.create prüft nicht, ob die zugewiesene Person den
        Datensatz öffnen darf (mail/models/mail_activity.py, create), und
        kjr.affiliation.request ist nur für Sachbearbeiter und Leitung lesbar
        (security/ir.model.access.csv).

        1. Systemparameter kjr_grant.affiliation_responsible_user_id (Benutzer-ID);
        2. sonst die erste passende Person der Gruppe Sachbearbeiter
           (all_user_ids enthält über implied_ids auch die Leitung);
        3. sonst niemand: die Aktivität entsteht ohne Zuweisung und erscheint
           in der Liste „Vereinsregistrierungen“ der Geschäftsstelle. Einen
           Rückfall auf base.user_admin gibt es bewusst nicht: ist der
           Administrator Sachbearbeiter, findet ihn schon Schritt 2, sonst
           könnte er die Aktivität nicht öffnen.
        """
        Users = self.env['res.users'].sudo()

        def _eligible(user):
            return bool(user and user.active and user._is_internal()
                        and user.has_group('kjr_grant.group_kjr_reviewer'))

        raw = self.env['ir.config_parameter'].sudo().get_param(PARAM_RESPONSIBLE)
        if raw:
            try:
                user = Users.browse(int(raw)).exists()
            except (TypeError, ValueError):
                user = Users.browse()
            if _eligible(user):
                return user
            # Nur die ID aus dem Parameter, keine Personendaten.
            _logger.warning('KJR Vereinsregistrierung: Parameter %s verweist auf keinen aktiven '
                            'internen Sachbearbeiter (Wert %s), wird übergangen.',
                            PARAM_RESPONSIBLE, raw)
        group = self.env.ref('kjr_grant.group_kjr_reviewer', raise_if_not_found=False)
        if group:
            user = group.sudo().all_user_ids.filtered(
                lambda u: u.active and not u.share).sorted('id')[:1]
            if user:
                return user
        _logger.warning('KJR Vereinsregistrierung: keine zuständige Person in der Gruppe '
                        'Sachbearbeiter, Aktivität ohne Zuweisung.')
        return Users.browse()

    def _kjr_notify_office(self):
        """Aktivität „Zu erledigen“ für die Geschäftsstelle; wirft nie.

        Muster: kjr_event/models/event_registration.py (_kjr_consent_activity).
        Besteht schon eine offene Aktivität mit derselben Zusammenfassung,
        entsteht keine zweite. Weil user_id nicht der env.user (OdooBot) ist,
        verschickt Odoo die Zuweisungsbenachrichtigung selbst.
        """
        responsible = self._kjr_office_responsible()
        for rec in self:
            savepoint = self.env.cr.savepoint()
            try:
                with savepoint:
                    rec_su = rec.with_user(SUPERUSER_ID)
                    if rec_su.activity_ids.filtered(lambda a: a.summary == ACTIVITY_SUMMARY):
                        continue
                    values = {
                        'summary': ACTIVITY_SUMMARY,
                        'note': _('Neue Registrierung für einen Verein oder Verband. Bitte die '
                                  'Zugehörigkeit prüfen und genehmigen oder ablehnen.'),
                    }
                    if responsible:
                        # activity_schedule ergänzt user_id nur aus default_user_id
                        # des Aktivitätstyps (mail_activity_mixin.activity_schedule).
                        values['user_id'] = responsible.id
                    rec_su.activity_schedule(ACTIVITY_TYPE, **values)
            except Exception as err:  # noqa: BLE001 - die Aktivität darf die Registrierung nicht kippen
                _logger.error('KJR Vereinsregistrierung %s: Aktivität nicht angelegt (%s).',
                              rec.id, type(err).__name__)

    # ── Entscheidungen ──────────────────────────────────────────────────────

    def _kjr_check_reviewer(self):
        if not self.env.su and not self.env.user.has_group('kjr_grant.group_kjr_reviewer'):
            raise AccessError(_('Vereinsregistrierungen entscheidet die Geschäftsstelle.'))

    def _kjr_check_open(self):
        if self.state != 'requested':
            raise UserError(_('Diese Vereinsregistrierung ist bereits entschieden.'))

    def _kjr_do_approve(self, target, notify=True):
        """Genehmigen: Person der Organisation zuordnen (parent_id setzen).

        Das ist die EINZIGE Stelle, an der aus einer Registrierung ein Vereinsrecht
        entsteht. sudo ist nötig, weil group_kjr_reviewer kein Schreibrecht auf
        res.partner hat (nur base.group_partner_manager); die Gruppenprüfung und
        die Rechtewache (keine internen Benutzer, kein Umhängen ohne
        Kontaktrecht) stehen deshalb vorher.
        """
        self._kjr_check_reviewer()
        self.ensure_one()
        self._kjr_check_open()
        partner = self.partner_id.sudo()
        target = target.sudo()
        if not target or not target.is_company or target == partner:
            raise UserError(_('Bitte eine Organisation (Unternehmen) als Verband wählen.'))
        if not self.env.su:
            # RECHTEWACHE. Das sudo unten darf Sachbearbeitern ohne Schreibrecht
            # auf res.partner nicht mehr erlauben als die Zuordnung einer
            # Registrierungsperson: keine Kontakte interner Benutzer (auch
            # archivierter) und kein Umhängen aus einer anderen Organisation.
            if partner.with_context(active_test=False).user_ids.filtered(
                    lambda u: not u.share):
                raise UserError(_(
                    'Diese Person hat ein internes Benutzerkonto. Die Zuordnung zu einer '
                    'Organisation erfolgt dann nicht über eine Vereinsregistrierung.'))
            if (partner.parent_id and partner.parent_id != target
                    and not self.env.user.has_group('base.group_partner_manager')):
                raise UserError(_(
                    'Die Person ist bereits einer anderen Organisation zugeordnet. Das '
                    'Umhängen darf nur, wer Kontakte bearbeiten darf.'))

        # ADRESSWACHE. res.partner._fields_sync (base): Hat die Organisation
        # irgendein Adressfeld, ersetzt Odoo die Anschrift der Person durch die der
        # Organisation (Schritt 1b). Hat sie gar keine, schreibt Odoo die
        # Privatanschrift der Person in die Organisation (Schritt 2). Beides ist
        # bei unvollständiger Anschrift der Organisation falsch.
        if (partner.parent_id != target and partner._get_address_values()
                and not (target.street and target.zip and target.city)):
            raise UserError(_(
                'Die gewählte Organisation hat keine vollständige Anschrift (Straße, PLZ, Ort). '
                'Beim Zuordnen würde Odoo die Privatanschrift der Person in die Organisation '
                'übernehmen oder sie durch eine unvollständige Anschrift ersetzen. Bitte zuerst '
                'die Anschrift der Organisation pflegen.'))

        # USt-IdNr.-WACHE. _fields_sync schreibt synchronisierte kaufmännische
        # Felder (heute nur vat) der Person nach oben, wenn sie von denen der
        # Organisation abweichen; _get_commercial_values übernimmt nur GESETZTE
        # Werte der Organisation nach unten. Deshalb hier ausdrücklich angleichen.
        vals = {'parent_id': target.id}
        for fname in partner._synced_commercial_fields():
            if partner[fname] != target[fname]:
                vals[fname] = target._fields[fname].convert_to_write(target[fname], target)
        if self.requested_function and not partner.function:
            vals['function'] = self.requested_function
        # company_name setzt res.partner.write bei parent_id selbst auf False.
        partner.write(vals)

        self.sudo().write({
            'state': 'approved',
            'target_partner_id': target.id,
            'date_decided': fields.Datetime.now(),
            'decided_by_id': self.env.uid,
            'rejection_reason': False,
        })
        self.sudo().activity_feedback([ACTIVITY_TYPE], feedback=_('Genehmigt'))
        # Markup escapt den Parameter; sudo lässt den uid unverändert, Autor ist
        # also die Sachbearbeiterin bzw. der Sachbearbeiter.
        self.sudo().message_post(
            body=Markup('<p>%s</p>') % _('Genehmigt, zugeordnet zu %s.', target.display_name),
            subtype_xmlid='mail.mt_note',
        )
        if notify:
            self._kjr_send_mail('kjr_grant.mail_template_affiliation_approved')
        return True

    def _kjr_do_reject(self, reason=False, notify=True):
        """Ablehnen: Partner bleibt unverändert, das Konto bleibt als persönliches
        Konto nutzbar."""
        self._kjr_check_reviewer()
        self.ensure_one()
        self._kjr_check_open()
        if self.partner_already_linked:
            raise UserError(_(
                'Die Person ist bereits einer Organisation zugeordnet. Bitte zuerst die '
                'Zuordnung im Kontakt lösen oder die Registrierung genehmigen.'))
        reason = (reason or '').strip() or False
        self.sudo().write({
            'state': 'rejected',
            'rejection_reason': reason,
            'date_decided': fields.Datetime.now(),
            'decided_by_id': self.env.uid,
        })
        self.sudo().activity_feedback([ACTIVITY_TYPE], feedback=_('Abgelehnt'))
        body = Markup('<p>%s</p>') % _('Abgelehnt.')
        if reason:
            body += Markup('<p>%s</p>') % escape(reason)
        self.sudo().message_post(body=body, subtype_xmlid='mail.mt_note')
        if notify:
            self._kjr_send_mail('kjr_grant.mail_template_affiliation_rejected')
        return True

    def action_open_approve_wizard(self):
        self._kjr_check_reviewer()
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Vereinszugehörigkeit genehmigen'),
            'res_model': 'kjr.affiliation.approve.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def action_open_reject_wizard(self):
        self._kjr_check_reviewer()
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Vereinsregistrierung ablehnen'),
            'res_model': 'kjr.affiliation.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def _kjr_send_mail(self, xmlid):
        """Mail an die Person; wirft nie (Muster kjr_grant_application)."""
        template = self.env.ref(xmlid, raise_if_not_found=False)
        if not template:
            _logger.warning('KJR Vereinsregistrierung: Mailvorlage %s fehlt.', xmlid)
            return
        for rec in self:
            try:
                template.sudo().send_mail(rec.id, force_send=False)
            except Exception as err:  # noqa: BLE001
                _logger.error('KJR Vereinsregistrierung %s: Mail nicht versendet (%s).',
                              rec.id, type(err).__name__)

    # ── DSGVO: Speicherbegrenzung ───────────────────────────────────────────

    @api.model
    def _kjr_retention_days(self):
        """Löschfrist abgelehnter Registrierungen in Tagen; 0 = Löschung aus.

        Einzige Auslegung des Parameters: der Cron unten und der
        Datenschutzhinweis im Registrierungsformular (controllers/signup.py)
        nutzen dieselbe Umwandlung und denselben Rückfall, damit der Hinweis nie
        eine andere Frist nennt, als tatsächlich gilt. Negative Werte gelten wie
        0 (der Cron löscht dann nichts).
        """
        raw = self.env['ir.config_parameter'].sudo().get_param(PARAM_RETENTION)
        try:
            days = int(raw or DEFAULT_RETENTION_DAYS)
        except (TypeError, ValueError):
            days = DEFAULT_RETENTION_DAYS
        return max(days, 0)

    @api.model
    def _cron_purge_rejected(self):
        """Abgelehnte Registrierungen nach Frist löschen (0 = aus).

        mail.thread.unlink entfernt dabei Nachrichten, Tracking und Follower,
        mail.activity.mixin die Aktivitäten. Genehmigte Registrierungen bleiben
        als Nachweis, offene bis zur Entscheidung.
        """
        days = self._kjr_retention_days()
        if not days:
            return 0
        recs = self.sudo().search([
            ('state', '=', 'rejected'),
            ('date_decided', '<', fields.Datetime.now() - timedelta(days=days)),
        ])
        count = len(recs)
        recs.unlink()
        _logger.info('KJR Vereinsregistrierung: %d abgelehnte Registrierung(en) gelöscht.', count)
        return count
