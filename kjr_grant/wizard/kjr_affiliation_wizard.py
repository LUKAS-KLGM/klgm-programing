# -*- coding: utf-8 -*-
"""Assistenten zur Entscheidung über eine Vereinsregistrierung.

Beide Assistenten entscheiden nichts selbst: sie sammeln die Eingaben der
Geschäftsstelle und rufen ausschließlich kjr.affiliation.request._kjr_do_approve
bzw. _kjr_do_reject. Dort liegen Gruppenprüfung, Adress- und USt-IdNr.-Wache.

Der Genehmigungsassistent setzt NIE is_kjr_member: die Mitgliedschaft beschließt
die Vollversammlung, gepflegt wird sie im Reiter „KJR Verband“ des Kontakts.

Dachverband (seit 19.0.17.0.0): Hat die Person bei der Registrierung einen
Dachverband gewählt, legt der Assistent eine NEUE Organisation als Kind dieses
Verbands an (eigene Ortsgruppe mit eigener Anschrift; die Person wird ihr
Kontakt) und schlägt zuerst eine gleichnamige Organisation unter diesem
Dachverband vor.

Grenze (bewusst): Die neue Ortsgruppe ist ihr eigener commercial partner und
ohne is_kjr_member. Das Portal „Mein Verband“ (controllers/portal.py,
_kjr_verband) öffnet sich nur für Mitgliedsverbände; Personen der Ortsgruppe
sehen dort nur den Hinweis. Weitere Ansprechpersonen der Ortsgruppe pflegt
deshalb die Geschäftsstelle im Backend, bis die Ortsgruppe selbst Mitglied ist
(Reiter „KJR Verband“). Offener Punkt: Portalpflege für Ortsgruppen unter
einem Mitgliedsverband.

Sichtbarkeit nach oben (Datenschutz): Der eigene commercial partner grenzt
nur die Rechte der Ortsgruppe ab (Antrags- und Verbandsrechte), NICHT die
Leserechte im Portal. Die Odoo-Regel base.res_partner_portal_public_rule
(base/security/base_security.xml) erlaubt Portal-Zugängen das Lesen von
res.partner mit [('id', 'child_of', user.commercial_partner_id.id)], und
child_of folgt bei res.partner der parent_id-Kette. Hängt die Ortsgruppe per
parent_id unter dem Dachverband, lesen die Portal-Zugänge des Dachverbands
die Ortsgruppe und ihre Personen (Name, Funktion, E-Mail, Telefon, Anschrift).
Das ist gewollt (die Gruppe gehört zum Dachverband) und steht im
Datenschutzhinweis der Registrierung (views/auth_signup_templates.xml, „Wer
es sieht“) und als Hinweis in diesem Assistenten. Soll der Dachverband das
nicht sehen, darf die Gruppe nicht per parent_id unter ihm hängen (eigenes
Feld statt parent_id; fachlich mit dem KJR zu klären).

Delegierte: Hat die Person „Ich bin Delegierte/r“ angekreuzt, schlägt der
Assistent den Verband mit Vertretungsrecht vor (die Organisation selbst oder
der nächste darüber) und nimmt die Person erst mit „Genehmigen“ in dessen
Delegiertenliste auf. Ist das ein übergeordneter Verband (Ortsgruppe ohne
eigenes Vertretungsrecht), steht die Person in dessen Portal „Mein Verband“
nicht unter „Ansprechpersonen“ (andere commercial partner): Die
Delegiertentabelle dort kennzeichnet sie mit „Änderungen über die
Geschäftsstelle“ (views/portal_templates.xml), und der Assistent weist vor der
Genehmigung darauf hin. An- und Abmeldung solcher Delegierten bleibt bei der
Geschäftsstelle.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import escape_psql

from odoo.addons.kjr_grant.models.kjr_affiliation_request import DELEGATE_VERBAND_DOMAIN


class KjrAffiliationApproveWizard(models.TransientModel):
    _name = 'kjr.affiliation.approve.wizard'
    _description = 'Vereinszugehörigkeit genehmigen'

    request_id = fields.Many2one(
        'kjr.affiliation.request', string='Vereinsregistrierung', required=True,
        readonly=True, ondelete='cascade',
    )
    partner_id = fields.Many2one(related='request_id.partner_id', readonly=True)
    requested_name = fields.Char(related='request_id.requested_name', readonly=True)
    requested_function = fields.Char(related='request_id.requested_function', readonly=True)
    requested_place = fields.Char(related='request_id.requested_place', readonly=True)
    partner_already_linked = fields.Boolean(
        related='request_id.partner_already_linked', readonly=True)
    requested_parent_id = fields.Many2one(
        related='request_id.requested_parent_id', readonly=True)
    requested_delegate = fields.Boolean(
        related='request_id.requested_delegate', readonly=True)
    partner_phone = fields.Char(related='request_id.partner_phone', readonly=True)
    # Telefon nachtragen, wenn am Kontakt keines steht: Sachbearbeiter haben auf
    # res.partner nur Leserecht; _kjr_do_approve übernimmt die Nummer per sudo
    # und nur in ein LEERES Telefonfeld (keine fremde Nummer überschreiben).
    new_phone = fields.Char(
        'Telefon der Person nachtragen',
        help='Nur wenn bei der Person noch keine Telefonnummer hinterlegt ist, z. B. '
             'nach telefonischer Rückfrage. Wird mit der Genehmigung in den Kontakt '
             'der Person übernommen. Für Delegierte Pflicht.',
    )
    # Übergeordneter Verband der gewählten bestehenden Organisation: dessen
    # Portal-Zugänge sehen die Person nach der Zuordnung (Hinweis im Formular).
    target_parent_id = fields.Many2one(
        related='target_partner_id.parent_id', string='Übergeordneter Verband',
        readonly=True)

    mode = fields.Selection(
        [('existing', 'Bestehende Organisation wählen'),
         ('new', 'Neue Organisation anlegen')],
        string='Vorgehen', compute='_compute_mode', store=True, readonly=False,
        required=True,
    )
    target_partner_id = fields.Many2one(
        'res.partner', string='Organisation', domain=[('is_company', '=', True)],
        compute='_compute_target_partner_id', store=True, readonly=False,
    )
    target_is_member = fields.Boolean(
        related='target_partner_id.is_kjr_member', string='KJR-Mitgliedsverband')

    new_name = fields.Char(
        'Name der Organisation', compute='_compute_new_defaults', store=True, readonly=False)
    new_street = fields.Char('Straße')
    new_zip = fields.Char('PLZ')
    new_city = fields.Char(
        'Ort', compute='_compute_new_defaults', store=True, readonly=False)
    new_email = fields.Char('E-Mail der Organisation')
    new_parent_id = fields.Many2one(
        'res.partner', string='Übergeordneter Verband (Dachverband)',
        domain=[('is_company', '=', True)],
        compute='_compute_new_defaults', store=True, readonly=False,
        help='Die neue Organisation wird als eigene Gruppe unter diesem Verband '
             'angelegt (z. B. Ortsfeuerwehr unter der Kreisjugendfeuerwehr). Sie '
             'behält ihre eigene Anschrift. Solange sie selbst kein KJR-Mitglied '
             'ist, pflegt ihre Ansprechpersonen die Geschäftsstelle; das Portal '
             '„Mein Verband“ steht nur Mitgliedsverbänden offen.',
    )
    add_delegate = fields.Boolean(
        'Als Delegierte/r eintragen', compute='_compute_add_delegate',
        store=True, readonly=False,
        help='Nimmt die Person mit der Genehmigung in die Delegiertenliste des '
             'unten gewählten Verbands auf. Vorbelegt aus der Angabe bei der '
             'Registrierung. Telefon ist für Delegierte Pflicht.',
    )
    delegate_partner_id = fields.Many2one(
        'res.partner', string='Delegierte/r für Verband',
        domain=DELEGATE_VERBAND_DOMAIN,
        compute='_compute_delegate_partner_id', store=True, readonly=False,
        help='Verband mit Vertretungsrecht in der Vollversammlung: die zugeordnete '
             'Organisation selbst oder ein übergeordneter Verband.',
    )
    delegate_base_state = fields.Selection(
        [('none', 'Keine Organisation gewählt'),
         ('no_vr', 'Kein Verband mit Vertretungsrecht'),
         ('ok', 'Verband mit Vertretungsrecht vorhanden')],
        compute='_compute_delegate_base_state',
        help='Steuert die Hinweise zur Delegiertenaufnahme im Assistenten.',
    )
    send_mail = fields.Boolean('Person per E-Mail benachrichtigen', default=True)

    def _kjr_delegate_base(self):
        """Organisation, von der aus der Verband mit Vertretungsrecht gesucht wird."""
        self.ensure_one()
        return self.target_partner_id if self.mode == 'existing' else self.new_parent_id

    @api.depends('mode', 'target_partner_id', 'new_parent_id')
    def _compute_delegate_base_state(self):
        Request = self.env['kjr.affiliation.request']
        for wiz in self:
            base = wiz._kjr_delegate_base()
            if not base:
                wiz.delegate_base_state = 'none'
            elif Request._kjr_delegate_verband_for(base):
                wiz.delegate_base_state = 'ok'
            else:
                wiz.delegate_base_state = 'no_vr'

    @api.depends('request_id')
    def _compute_target_partner_id(self):
        Partner = self.env['res.partner']
        for wiz in self:
            req = wiz.request_id
            target = Partner.browse()
            if req.partner_already_linked:
                target = req.partner_id.commercial_partner_id
            elif req.requested_name and req.requested_parent_id:
                # Gruppe mit gewähltem Dachverband: zuerst eine gleichnamige
                # Organisation in dessen Teilbaum (auch ohne eigene Mitgliedschaft,
                # Ortsgruppen sind meist keine KJR-Mitglieder).
                target = Partner.search([
                    ('name', '=ilike', escape_psql(req.requested_name)),
                    ('is_company', '=', True),
                    ('id', 'child_of', req.requested_parent_id.id),
                ], limit=1)
            if not target and not req.partner_already_linked and req.requested_name:
                # Nur ein exakter Treffer (ohne Groß-/Kleinschreibung) unter den
                # Mitgliedsverbänden; Platzhalterzeichen im Freitext werden maskiert.
                target = Partner.search([
                    ('name', '=ilike', escape_psql(req.requested_name)),
                    ('is_company', '=', True),
                    ('is_kjr_member', '=', True),
                ], limit=1)
            wiz.target_partner_id = target

    @api.depends('request_id')
    def _compute_mode(self):
        # Nur vom Antrag abhängig (Vorbelegung beim Öffnen); ein späterer Wechsel
        # der Organisation durch die Geschäftsstelle stellt das Vorgehen nicht um.
        for wiz in self:
            # Neue Ortsgruppe vorschlagen, wenn ein Dachverband gewählt wurde und
            # es darunter (noch) keine passende Organisation gibt.
            req = wiz.request_id
            if (req.requested_parent_id and not req.partner_already_linked
                    and not wiz.target_partner_id):
                wiz.mode = 'new'
            else:
                wiz.mode = 'existing'

    @api.depends('request_id')
    def _compute_new_defaults(self):
        for wiz in self:
            wiz.new_name = wiz.request_id.requested_name or False
            wiz.new_city = wiz.request_id.requested_place or False
            wiz.new_parent_id = wiz.request_id.requested_parent_id

    @api.depends('request_id')
    def _compute_add_delegate(self):
        for wiz in self:
            wiz.add_delegate = wiz.request_id.requested_delegate

    @api.depends('mode', 'target_partner_id', 'new_parent_id', 'add_delegate')
    def _compute_delegate_partner_id(self):
        Request = self.env['kjr.affiliation.request']
        for wiz in self:
            base = wiz._kjr_delegate_base()
            wiz.delegate_partner_id = Request._kjr_delegate_verband_for(base) if base else False

    def action_confirm(self):
        self.ensure_one()
        self.request_id._kjr_check_reviewer()
        if self.mode == 'new':
            if not (self.new_name and self.new_street and self.new_zip and self.new_city):
                raise UserError(_('Für eine neue Organisation bitte Name, Straße, PLZ und Ort angeben.'))
            # sudo: group_kjr_reviewer hat kein Anlagerecht auf res.partner; die
            # Gruppenprüfung steht unmittelbar davor.
            vals = {
                'name': self.new_name,
                'is_company': True,
                'street': self.new_street,
                'zip': self.new_zip,
                'city': self.new_city,
                'email': self.new_email or False,
            }
            if self.new_parent_id:
                # Ortsgruppe unter dem Dachverband. type='other' ist Absicht:
                # res.partner._fields_sync (base) gleicht bei type='contact' mit
                # parent_id die Anschrift ab — die neue Gruppe bekäme die Anschrift
                # des Dachverbands, und spätere Adressänderungen der Gruppe würden
                # nach oben in den Dachverband geschrieben. Als Unternehmen bleibt
                # sie ihr eigener commercial partner (_compute_commercial_partner):
                # Antrags- und Verbandsrechte hängen an ihr selbst. Die LESErechte
                # im Portal folgen dagegen parent_id (base.res_partner_portal_public_rule,
                # child_of user.commercial_partner_id): Die Portal-Zugänge des
                # Dachverbands sehen die Gruppe und ihre Personen. Offengelegt im
                # Datenschutzhinweis der Registrierung, siehe Modul-Docstring.
                # Ohne is_kjr_member öffnet sich „Mein Verband“ im Portal nicht
                # (controllers/portal.py, _kjr_verband): Ansprechpersonen der
                # Ortsgruppe pflegt bis zur Mitgliedschaft die Geschäftsstelle.
                vals.update({'parent_id': self.new_parent_id.id, 'type': 'other'})
            target = self.env['res.partner'].sudo().create(vals)
            # Ohne is_kjr_member: Mitgliedschaft beschließt die Vollversammlung,
            # gepflegt im Reiter „KJR Verband“.
        else:
            target = self.target_partner_id
            if not target:
                raise UserError(_('Bitte eine Organisation wählen.'))
        delegate_for = None
        if self.add_delegate:
            if not self.delegate_partner_id:
                raise UserError(_(
                    'Bitte den Verband mit Vertretungsrecht wählen, für den die Person '
                    'Delegierte/r ist, oder das Häkchen „Als Delegierte/r eintragen“ '
                    'entfernen.'))
            delegate_for = self.delegate_partner_id
        self.request_id._kjr_do_approve(
            target, notify=self.send_mail, delegate_for=delegate_for,
            phone=self.new_phone)
        return {'type': 'ir.actions.act_window_close'}


class KjrAffiliationRejectWizard(models.TransientModel):
    _name = 'kjr.affiliation.reject.wizard'
    _description = 'Vereinsregistrierung ablehnen'

    request_id = fields.Many2one(
        'kjr.affiliation.request', string='Vereinsregistrierung', required=True,
        readonly=True, ondelete='cascade',
    )
    reason = fields.Text('Grund (freiwillig, wird der Person mitgeteilt)')
    send_mail = fields.Boolean('Person per E-Mail benachrichtigen', default=True)

    def action_confirm(self):
        self.ensure_one()
        self.request_id._kjr_do_reject(self.reason, notify=self.send_mail)
        return {'type': 'ir.actions.act_window_close'}
