# -*- coding: utf-8 -*-
"""Vollversammlung des KJR — Einladung, Anwesenheit, Beschlüsse, Wahlen.

Rechtevergabe (siehe security/ir.model.access.csv): Vollversammlung, Beschlüsse
und Kandidaturen bilden EIN Nachweisdokument. Die Rechte der Gruppe
"Sachbearbeiter" (group_kjr_reviewer) sind deshalb über alle drei Modelle
einheitlich auf Lesen gesetzt — sonst könnten ausgezählte Stimmen nachträglich
verändert werden, ohne dass die Versammlung selbst bearbeitet werden darf.
Gepflegt wird das Protokoll von der Gruppe "Administrator".

EINLADUNG UND ANMELDUNG (seit 19.0.17.0.0)
──────────────────────────────────────────
* Eingeladene Verbände: ``invited_member_ids`` (von Hand gepflegt oder per
  „Alle stimmberechtigten übernehmen“ vorbelegt). Gehört zur einzelnen
  Versammlung (copy=False): Eine duplizierte Versammlung startet ohne Liste,
  „Einladen“ übernimmt dann den aktuellen Stand der Stimmberechtigten.
* Versand: ``action_send_invitations`` legt je eingeladenem Verband einen
  Versandnachweis ``kjr.assembly.invitation`` an und schickt die Mailvorlage
  ``mail_template_assembly_invitation`` an die Delegierten des Verbands
  (``kjr_vr_delegate_ids`` mit E-Mail), sonst an die E-Mail des Verbands. Haben
  nicht alle Delegierten eine E-Mail-Adresse, geht die Einladung zusätzlich an
  die E-Mail des Verbands; die Versandnotiz und der Hinweis im Formular nennen
  die Delegierten ohne E-Mail. Versandt wird nur für eine geplante oder
  eingeladene Versammlung mit Termin in der Zukunft und nur an Verbände, die
  noch in der Liste stehen; das gilt auch für „Erneut senden“. Ein
  schon versandter Nachweis wird nie ein zweites Mal verschickt, außer über
  „Erneut senden“ an genau diesem Nachweis. Die versandte Mail bleibt im
  Verlauf des Nachweises stehen (Vorlage ohne auto_delete; mail.mail und
  mail.message werden nicht gelöscht), dazu Zeitpunkt, Absender, Empfänger und
  Anzahl in Feldern und eine Notiz an der Vollversammlung.
* Zustellung: Status „Versandt“ heißt „an den Mailversand übergeben“ (Mail-
  Warteschlange, force_send=False). Ob die Mail den Mailserver erreicht hat,
  zeigt ``delivery_state`` aus der zugehörigen mail.mail (In Warteschlange /
  An Mailserver übergeben / Fehlgeschlagen). Fehlgeschlagene Einladungen
  verschickt „Einladungen versenden“ erneut.
* Delegiertenverzeichnis: ``delegate_ids`` zeigt die Delegierten der
  eingeladenen Verbände mit Telefon und E-Mail.
* Anmeldung: Der Link in der Einladung führt auf
  /vollversammlung/anmeldung/<id>/<token> (controllers/assembly.py). Dort ist
  die Telefonnummer Pflicht; jede Anmeldung wird ``kjr.assembly.registration``.
  Auch die Geschäftsstelle kann Anmeldungen erfassen, ebenfalls nur mit
  Telefonnummer. Eine Online-Anmeldung wird nur innerhalb DERSELBEN Einladung
  über die E-Mail-Adresse wiedergefunden und aktualisiert; Anmeldungen anderer
  Verbände und von der Geschäftsstelle erfasste werden über den Link nie
  verändert. Den Kontakt (``partner_id``) ordnet die Online-Anmeldung nur zu,
  wenn die Person angemeldet ist und ihre eigene E-Mail-Adresse angibt; sonst
  ordnet die Geschäftsstelle von Hand zu (Vorschlag ``suggested_partner_id``).
* Löschung (DSGVO): Anmeldungen samt Verlauf werden nach
  ``kjr_grant.assembly_registration_retention_days`` Tagen nach dem
  Versammlungstermin gelöscht (Cron, 0 = aus), sobald die Versammlung
  durchgeführt oder abgesagt ist.
"""
import logging
import re
import uuid

from markupsafe import Markup

from datetime import timedelta

from odoo import SUPERUSER_ID, api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import escape_psql

_logger = logging.getLogger(__name__)

INVITATION_TEMPLATE = 'kjr_grant.mail_template_assembly_invitation'
# DSGVO: Löschfrist der Anmeldungen in Tagen nach dem Versammlungstermin (0 = aus).
PARAM_REGISTRATION_RETENTION = 'kjr_grant.assembly_registration_retention_days'
DEFAULT_REGISTRATION_RETENTION_DAYS = 365
# Zustellstatus der Einladung aus mail.mail.state (addons/mail/models/mail_mail.py).
MAIL_DELIVERY_STATE = {
    'outgoing': 'queued',
    'sent': 'sent',
    'received': 'sent',
    'exception': 'failed',
    'cancel': 'failed',
}
# Wie PHONE_RE im Portal (controllers/portal.py): Ziffern, Leerzeichen, + ( ) / - .
ASSEMBLY_PHONE_RE = re.compile(r'^[0-9 +()/.\-]{5,32}$')


class KjrAssembly(models.Model):
    _name = 'kjr.assembly'
    _description = 'KJR Vollversammlung'
    _order = 'date desc'
    _inherit = ['mail.thread']

    name = fields.Char(string='Bezeichnung', required=True, tracking=True)
    date = fields.Datetime(string='Datum & Uhrzeit', required=True, tracking=True)
    location = fields.Char(string='Ort', tracking=True)
    state = fields.Selection([
        ('draft', 'Planung'),
        ('invited', 'Eingeladen'),
        ('done', 'Durchgeführt'),
        ('cancelled', 'Abgesagt'),
    ], default='draft', tracking=True)
    agenda = fields.Html(string='Tagesordnung')
    protocol = fields.Html(string='Protokoll')
    attendee_ids = fields.Many2many(
        'res.partner', 'kjr_assembly_attendee_rel',
        string='Anwesende Mitgliedsverbände',
        # Dieselbe Menge, die auch eligible_member_count zählt (_eligible_member_domain).
        domain="[('is_kjr_member', '=', True), ('is_company', '=', True),"
               " ('kjr_vr_right', '=', True)]",
        help='Erfasst werden die anwesenden MITGLIEDSVERBÄNDE, nicht einzelne '
             'Delegierte oder Gäste: § 33 Abs. 1 BJR-Satzung gibt jedem Mitglied '
             'eine Stimme, und genau diese Zahl trägt die Beschlussfähigkeit. '
             'Die Namen der entsandten Personen gehören ins Protokoll bzw. an den '
             'Verband (Feld "Vertreter/innen" am Kontakt).',
    )
    attendee_count = fields.Integer(string='Anwesend', compute='_compute_attendee_count')
    decision_ids = fields.One2many('kjr.assembly.decision', 'assembly_id', string='Beschlüsse')
    decision_count = fields.Integer(string='Anzahl Beschlüsse', compute='_compute_decision_count')
    election_count = fields.Integer(string='Anzahl Wahlgänge', compute='_compute_decision_count')
    # copy=False: Die Liste gehört zur einzelnen Versammlung. Eine duplizierte
    # Vorjahresversammlung bekäme sonst die alte Liste (ausgetretene Verbände
    # ja, neue Mitglieder nein); „Einladen“ füllt eine leere Liste mit dem
    # aktuellen Stand der Stimmberechtigten.
    invited_member_ids = fields.Many2many(
        'res.partner', 'kjr_assembly_invited_rel',
        string='Eingeladene Verbände', copy=False,
        domain="[('is_kjr_member', '=', True), ('is_company', '=', True)]",
    )
    note = fields.Text(string='Anmerkungen')
    invited_count = fields.Integer(string='Eingeladen', compute='_compute_invited_count')
    invitation_date = fields.Date(
        string='Einladung versandt am', tracking=True,
        help='Datum des Einladungsversands. Wird beim Einladen vorbelegt und kann '
             'für nachträglich erfasste Sitzungen von Hand gesetzt werden. '
             'Erscheint im Protokoll als Nachweis der ordnungsgemäßen Ladung.',
    )
    # Absender und Firmenname der Einladung (White-Label, wie überall im Modul).
    company_id = fields.Many2one(
        'res.company', string='Firma', required=True,
        default=lambda self: self.env.company,
    )
    invitation_ids = fields.One2many(
        'kjr.assembly.invitation', 'assembly_id', string='Einladungsversand',
    )
    invitation_sent_count = fields.Integer(
        string='Einladungen versandt', compute='_compute_invitation_stats',
    )
    invitation_open_count = fields.Integer(
        string='Einladungen offen', compute='_compute_invitation_stats',
        help='Eingeladene Verbände, an die noch keine Einladung per E-Mail '
             'gegangen ist (neu hinzugekommen oder ohne E-Mail-Adresse).',
    )
    delegate_ids = fields.Many2many(
        'res.partner', 'kjr_assembly_delegate_rel', 'assembly_id', 'partner_id',
        string='Delegierte der eingeladenen Verbände',
        compute='_compute_delegate_ids',
        help='Delegiertenverzeichnis: die Vertreter/innen (Feld "Vertreter/innen" '
             'am Verband) aller eingeladenen Verbände.',
    )
    delegate_missing_phone_count = fields.Integer(
        string='Delegierte ohne Telefon', compute='_compute_delegate_ids',
    )
    delegate_missing_email_count = fields.Integer(
        string='Delegierte ohne E-Mail', compute='_compute_delegate_ids',
        help='Delegierte der eingeladenen Verbände ohne E-Mail-Adresse. Sie erhalten '
             'keine eigene Einladung; die Einladung geht zusätzlich an die E-Mail des '
             'Verbands (falls vorhanden). Bitte auf anderem Weg einladen.',
    )
    date_in_past = fields.Boolean(
        string='Termin vorbei', compute='_compute_date_in_past',
        help='Der Termin liegt in der Vergangenheit: Es werden keine Einladungen '
             'mehr versandt.',
    )
    registration_ids = fields.One2many(
        'kjr.assembly.registration', 'assembly_id', string='Anmeldungen',
    )
    registration_count = fields.Integer(
        string='Anmeldungen', compute='_compute_registration_count',
    )
    # ── Protokoll: verantwortliche Personen ──────────────────────────────────
    chair_id = fields.Many2one(
        'res.partner', string='Versammlungsleitung',
        help='Person, die die Sitzung geleitet hat. Unterschreibt das Protokoll.',
    )
    secretary_id = fields.Many2one(
        'res.partner', string='Protokollführung',
        help='Person, die das Protokoll geführt hat. Unterschreibt das Protokoll.',
    )
    teller_ids = fields.Many2many(
        'res.partner', 'kjr_assembly_teller_rel', 'assembly_id', 'partner_id',
        string='Wahlausschuss / Stimmzähler',
        help='Personen, die bei geheimen Wahlen (§ 34 Abs. 3 BJR-Satzung) die '
             'Stimmzettel ausgezählt haben. Wird im Protokoll ausgewiesen.',
    )
    is_repeat_session = fields.Boolean(
        string='Wiederholte (außerordentliche) Sitzung',
        help='§ 33 Abs. 3 BJR-Satzung: Eine wegen Beschlussunfähigkeit erneut '
             'einberufene Sitzung ist ohne Rücksicht auf die Zahl der Anwesenden '
             'beschlussfähig.',
    )
    eligible_member_count = fields.Integer(
        string='Stimmberechtigte Mitglieder', compute='_compute_eligible_members',
        help='Anzahl der Verbände mit Vertretungsrecht in der Vollversammlung. '
             'Solange die Versammlung läuft, wird der aktuelle Mitgliederbestand '
             'gezählt; mit dem Abschluss wird der Wert festgeschrieben.',
    )
    quorum_reached = fields.Boolean(
        string='Beschlussfähig', compute='_compute_quorum',
        help='Beschlussfähig, wenn mehr als die Hälfte der stimmberechtigten Mitglieder '
             'anwesend ist (§ 33 BJR-Satzung). Wiederholte Sitzungen sind stets '
             'beschlussfähig. Mit dem Abschluss wird das Ergebnis festgeschrieben.',
    )
    # ── Festgeschriebene Protokollkennzahlen ─────────────────────────────────
    # Ein Protokoll ist ein Nachweisdokument: Ein Nachdruck Monate später muss
    # dieselben Zahlen zeigen wie am Sitzungstag — auch wenn zwischenzeitlich ein
    # Verband ein- oder ausgetreten ist. Die maßgeblichen Kennzahlen werden
    # deshalb beim Abschluss (action_done) gespeichert; die Anzeigefelder oben
    # geben ab dann den festgeschriebenen Wert zurück.
    figures_locked_date = fields.Datetime(
        string='Kennzahlen festgeschrieben am', readonly=True, copy=False,
        help='Zeitpunkt, zu dem Stimmberechtigte und Beschlussfähigkeit für das '
             'Protokoll festgeschrieben wurden (beim Abschluss der Versammlung).',
    )
    eligible_member_count_final = fields.Integer(
        string='Stimmberechtigte (festgeschrieben)', readonly=True, copy=False,
        help='Zahl der stimmberechtigten Mitgliedsverbände zum Zeitpunkt des '
             'Abschlusses. Grundlage jedes Protokoll-Nachdrucks.',
    )
    quorum_reached_final = fields.Boolean(
        string='Beschlussfähig (festgeschrieben)', readonly=True, copy=False,
        help='Beschlussfähigkeit, wie sie beim Abschluss der Versammlung '
             'festgestellt wurde.',
    )

    @api.depends('attendee_ids')
    def _compute_attendee_count(self):
        for rec in self:
            rec.attendee_count = len(rec.attendee_ids)

    @api.depends('decision_ids', 'decision_ids.decision_type')
    def _compute_decision_count(self):
        for rec in self:
            rec.decision_count = len(rec.decision_ids)
            rec.election_count = len(
                rec.decision_ids.filtered(lambda d: d.decision_type == 'election')
            )

    @api.depends('invited_member_ids')
    def _compute_invited_count(self):
        for rec in self:
            rec.invited_count = len(rec.invited_member_ids)

    @api.depends('invitation_ids.state', 'invitation_ids.member_id',
                 'invitation_ids.delivery_state', 'invited_member_ids')
    def _compute_invitation_stats(self):
        for rec in self:
            sent = rec.invitation_ids.filtered(lambda i: i.state == 'sent')
            rec.invitation_sent_count = len(sent)
            # Fehlgeschlagene Zustellung zählt als offen: „Einladungen versenden“
            # verschickt sie erneut.
            delivered = sent.filtered(lambda i: i.delivery_state != 'failed')
            rec.invitation_open_count = len(rec.invited_member_ids - delivered.member_id)

    @api.depends('invited_member_ids', 'invited_member_ids.kjr_vr_delegate_ids',
                 'invited_member_ids.kjr_vr_delegate_ids.phone',
                 'invited_member_ids.kjr_vr_delegate_ids.email',
                 'invited_member_ids.kjr_vr_delegate_ids.active')
    def _compute_delegate_ids(self):
        for rec in self:
            delegates = rec.invited_member_ids.kjr_vr_delegate_ids.filtered('active')
            rec.delegate_ids = delegates
            rec.delegate_missing_phone_count = len(
                delegates.filtered(lambda p: not (p.phone or '').strip()))
            rec.delegate_missing_email_count = len(
                delegates.filtered(lambda p: not (p.email or '').strip()))

    @api.depends('date')
    def _compute_date_in_past(self):
        # Nicht gespeichert: hängt von der aktuellen Uhrzeit ab.
        now = fields.Datetime.now()
        for rec in self:
            rec.date_in_past = bool(rec.date) and rec.date <= now

    @api.depends('registration_ids.state')
    def _compute_registration_count(self):
        for rec in self:
            rec.registration_count = len(
                rec.registration_ids.filtered(lambda r: r.state == 'registered'))

    @api.model
    def _eligible_member_domain(self):
        """Stimmberechtigte Mitgliedsverbände (§ 33 Abs. 1 BJR-Satzung).

        Dieselbe Menge steht als Domain auf attendee_ids — dort als Literal,
        weil Feld-Domains nicht aus Methoden gelesen werden können.
        """
        return [
            ('is_kjr_member', '=', True),
            ('kjr_vr_right', '=', True),
            ('is_company', '=', True),
        ]

    def _attending_member_count(self):
        """Anzahl der anwesenden stimmberechtigten Mitgliedsverbände.

        Bestandsschutz: In bereits abgeschlossenen Protokollen ohne
        festgeschriebene Kennzahlen konnten vor Einführung der Domain auf
        attendee_ids auch einzelne Delegierte oder Gäste eingetragen worden
        sein. Dort bleibt die bisherige Zählweise (alle Einträge der
        Anwesenheitsliste) erhalten, damit ein einmal beurkundetes Ergebnis
        sich nicht nachträglich in "nicht beschlussfähig" verkehrt.
        """
        self.ensure_one()
        members = self.attendee_ids.filtered(
            lambda p: p.is_company and p.is_kjr_member and p.kjr_vr_right)
        if self.state == 'done' and len(members) != len(self.attendee_ids):
            return len(self.attendee_ids)
        return len(members)

    @api.depends('figures_locked_date', 'eligible_member_count_final')
    def _compute_eligible_members(self):
        # Nicht gespeichert: Solange nicht festgeschrieben, gilt der aktuelle
        # Mitgliederbestand (Live-Abfrage, nicht über @api.depends abbildbar).
        count = self.env['res.partner'].search_count(self._eligible_member_domain())
        for rec in self:
            if rec.figures_locked_date:
                rec.eligible_member_count = rec.eligible_member_count_final
            else:
                rec.eligible_member_count = count

    @api.depends('attendee_ids', 'attendee_ids.is_company', 'attendee_ids.is_kjr_member',
                 'attendee_ids.kjr_vr_right', 'invited_member_ids', 'is_repeat_session',
                 'state', 'figures_locked_date', 'quorum_reached_final')
    def _compute_quorum(self):
        eligible = self.env['res.partner'].search_count(self._eligible_member_domain())
        for rec in self:
            if rec.figures_locked_date:
                # Festgeschriebenes Protokoll: Ergebnis des Sitzungstags.
                rec.quorum_reached = rec.quorum_reached_final
                continue
            attending = rec._attending_member_count()
            # § 33 Abs. 3: wiederholte Sitzung ist quorum-unabhängig beschlussfähig.
            if rec.is_repeat_session:
                rec.quorum_reached = attending > 0
            elif eligible:
                rec.quorum_reached = attending * 2 > eligible
            else:
                # Fallback auf die Eingeladenen, falls (noch) keine Stimmberechtigten gepflegt sind.
                invited = len(rec.invited_member_ids)
                rec.quorum_reached = bool(invited) and (attending * 2 > invited)

    def action_fill_invited_members(self):
        """Alle stimmberechtigten Mitgliedsverbände als eingeladen übernehmen.

        Ergänzt die Liste, ersetzt sie nicht: von Hand eingetragene Verbände
        (z. B. Gäste ohne Stimmrecht) bleiben stehen.
        """
        members = self.env['res.partner'].search(self._eligible_member_domain())
        for rec in self:
            rec.invited_member_ids = [(4, member.id) for member in members]
        return True

    def action_invite(self):
        """Einladen: eingeladene Verbände festhalten und Einladung per E-Mail senden.

        Ist noch kein Verband eingetragen, werden alle stimmberechtigten
        Mitgliedsverbände übernommen (bisheriges Verhalten). Eine von Hand
        gepflegte Liste bleibt unverändert; eine duplizierte Versammlung
        startet ohne Liste (copy=False an invited_member_ids).

        Liegt der Termin in der Vergangenheit (nachträglich erfasste Sitzung),
        wird die Versammlung nur als eingeladen erfasst, ohne E-Mail-Versand
        und ohne Ladungsdatum (das trägt die Geschäftsstelle von Hand ein).
        """
        self.check_access('write')
        now = fields.Datetime.now()
        for rec in self:
            if not rec.invited_member_ids:
                rec.action_fill_invited_members()
        past = self.filtered(lambda r: r.date and r.date <= now)
        for rec in past:
            if rec.state not in ('draft', 'invited'):
                raise UserError(_(
                    'Einladungen lassen sich nur für eine geplante oder bereits eingeladene '
                    'Vollversammlung versenden.'))
            if rec.state == 'draft':
                rec.write({'state': 'invited'})
                rec.message_post(
                    body=Markup('<p>%s</p>') % _(
                        'Der Termin liegt in der Vergangenheit: als eingeladen erfasst, ohne '
                        'E-Mail-Versand (nachträglich erfasste Sitzung); %(total)d Verband/'
                        'Verbände eingeladen. Das Ladungsdatum bitte von Hand eintragen.',
                        total=len(rec.invited_member_ids)),
                    subtype_xmlid='mail.mt_note',
                )
        upcoming = self - past
        if upcoming:
            return upcoming.action_send_invitations()
        return True

    def action_send_invitations(self):
        """Einladungen an alle eingeladenen Verbände versenden, die noch keine haben.

        Kein Doppelversand: Verbände mit einem versandten Nachweis werden
        übersprungen, außer die Zustellung ist fehlgeschlagen
        (``delivery_state`` 'failed'); diese Einladungen gehen erneut raus.
        Wer nachträglich in die Liste kommt, erhält beim nächsten Aufruf seine
        Einladung. Nachweise noch nicht versandter Verbände, die aus der Liste
        genommen wurden, entfallen; versandte bleiben als Nachweis stehen,
        werden aber nie erneut verschickt (auch nicht bei fehlgeschlagener
        Zustellung). Für einen Termin in der Vergangenheit wird nichts mehr
        versandt (z. B. Bestandsversammlungen, die noch auf „Eingeladen“ stehen).
        """
        self.check_access('write')
        Invitation = self.env['kjr.assembly.invitation']
        now = fields.Datetime.now()
        for rec in self:
            if rec.state not in ('draft', 'invited'):
                raise UserError(_(
                    'Einladungen lassen sich nur für eine geplante oder bereits eingeladene '
                    'Vollversammlung versenden.'))
            if rec.date and rec.date <= now:
                raise UserError(_(
                    'Der Termin der Vollversammlung liegt in der Vergangenheit; Einladungen '
                    'werden nicht mehr versandt.'))
            if not rec.invited_member_ids:
                raise UserError(_('Bitte zuerst die eingeladenen Verbände erfassen.'))
            rec.invitation_ids.filtered(
                lambda i: i.state != 'sent' and i.member_id not in rec.invited_member_ids
            ).unlink()
            missing = rec.invited_member_ids - rec.invitation_ids.member_id
            if missing:
                Invitation.with_context(
                    mail_create_nolog=True, mail_create_nosubscribe=True,
                ).create([
                    {'assembly_id': rec.id, 'member_id': member.id} for member in missing])
            # Nur Verbände, die noch eingeladen sind: Ein versandter Nachweis
            # eines entfernten Verbands bleibt stehen (Nachweis), darf aber auch
            # bei fehlgeschlagener Zustellung nicht erneut verschickt werden.
            to_send = rec.invitation_ids.filtered(
                lambda i: i.member_id in rec.invited_member_ids
                and (i.state != 'sent' or i.delivery_state == 'failed'))
            # force: die Auswahl oben ist bereits die Liste der zu sendenden
            # Nachweise (offen oder Zustellung fehlgeschlagen).
            sent = to_send._kjr_send(force=True)
            no_address = to_send.filtered(lambda i: i.state == 'no_address')
            vals = {'state': 'invited'}
            # Ladungsdatum nur vorbelegen, nie überschreiben — ein von Hand
            # gepflegtes Datum (nacherfasste Sitzung) bleibt erhalten.
            if not rec.invitation_date and (sent or rec.invitation_sent_count):
                vals['invitation_date'] = fields.Date.context_today(rec)
            rec.write(vals)
            body = Markup('<p>%s</p>') % _(
                'Einladung per E-Mail an %(sent)d Verband/Verbände versandt; '
                'insgesamt %(total)d eingeladen.',
                sent=len(sent), total=len(rec.invited_member_ids))
            if no_address:
                body += Markup('<p>%s</p>') % _(
                    'Ohne E-Mail-Adresse (bitte auf anderem Weg einladen): %s',
                    ', '.join(no_address.member_id.mapped('name')))
            body += sent._kjr_missing_email_note()
            former = rec.invited_member_ids.filtered(lambda p: not p.is_kjr_member)
            if former:
                body += Markup('<p>%s</p>') % _(
                    'Eingeladen, aber (nicht mehr) KJR-Mitglied, bitte prüfen: %s',
                    ', '.join(former.mapped('name')))
            rec.message_post(body=body, subtype_xmlid='mail.mt_note')
        return True

    def action_view_registrations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Anmeldungen'),
            'res_model': 'kjr.assembly.registration',
            'view_mode': 'list,form',
            'domain': [('assembly_id', '=', self.id)],
            'context': {'default_assembly_id': self.id},
        }

    def action_done(self):
        """Versammlung abschließen und die Protokollkennzahlen festschreiben.

        Ab hier liefern eligible_member_count und quorum_reached den beim
        Abschluss festgestellten Wert, damit ein Nachdruck des Protokolls
        reproduzierbar bleibt. Bereits vorhandene abgeschlossene Versammlungen
        (Bestandsdaten) haben kein Festschreibedatum und rechnen unverändert
        weiter live.
        TODO(KJR): Für Altprotokolle liegen keine belegten Zahlen des
        Sitzungstags vor; sie werden bewusst NICHT rückwirkend gefüllt. Ob und
        mit welchen Werten sie nacherfasst werden, entscheidet der KJR.
        """
        for rec in self:
            vals = {'state': 'done'}
            if not rec.figures_locked_date:
                vals.update({
                    'eligible_member_count_final': rec.eligible_member_count,
                    'quorum_reached_final': rec.quorum_reached,
                    'figures_locked_date': fields.Datetime.now(),
                })
            rec.write(vals)

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_print_protokoll(self):
        """Sitzungsprotokoll als PDF (Beschlüsse und Wahlergebnisse)."""
        return self.env.ref('kjr_grant.action_report_kjr_assembly_protokoll').report_action(self)


class KjrAssemblyDecision(models.Model):
    """Tagesordnungspunkt mit Abstimmung: Sachbeschluss oder (geheime) Wahl.

    Wahlen liegen bewusst in diesem Modell und nicht in einer zweiten,
    parallelen Struktur: eine Vollversammlung hat EINE Tagesordnung, in der
    Sachbeschlüsse und Wahlgänge in einer gemeinsamen Reihenfolge stehen —
    genau so muss sie auch im Protokoll erscheinen.
    """
    _name = 'kjr.assembly.decision'
    _description = 'Beschluss Vollversammlung'
    _order = 'sequence, id'

    assembly_id = fields.Many2one('kjr.assembly', string='Vollversammlung', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Beschluss', required=True)
    description = fields.Text(string='Details')
    decision_type = fields.Selection([
        ('resolution', 'Sachbeschluss'),
        ('election', 'Wahl (geheim)'),
    ], string='Art', default='resolution', required=True,
        help='Sachbeschluss: offene Abstimmung mit Ja/Nein/Enthaltung. '
             'Wahl: geheime Wahl nach § 34 Abs. 3 BJR-Satzung mit Kandidat/innen '
             'und ausgezählten Stimmensummen.')
    vote_yes = fields.Integer(string='Ja-Stimmen', default=0)
    vote_no = fields.Integer(string='Nein-Stimmen', default=0)
    vote_abstain = fields.Integer(string='Enthaltungen', default=0)
    vote_invalid = fields.Integer(
        string='Ungültige Stimmen', default=0,
        help='Ungültige Stimmzettel. Zählen wie Enthaltungen nicht zur '
             'Berechnungsgrundlage der Mehrheit (§ 33 Abs. 2 BJR-Satzung).',
    )
    ballots_cast = fields.Integer(
        string='Abgegebene Stimmzettel', default=0,
        help='Vom Wahlausschuss gezählte Stimmzettel. Dient nur der '
             'Plausibilitätskontrolle der Auszählung; kann leer bleiben.',
    )
    result = fields.Selection([
        ('accepted', 'Angenommen'),
        ('rejected', 'Abgelehnt'),
        ('tabled', 'Vertagt'),
    ], string='Ergebnis', compute='_compute_result', store=True, readonly=False,
        help='Wird aus den Stimmen vorbelegt (Mehrheit der Ja-/Nein-Stimmen), '
             'kann aber manuell überschrieben werden. Bei Wahlen bleibt dieses '
             'Feld leer, dort gilt das Wahlergebnis (Feld "Wahlergebnis").')

    # ── Wahl (geheim, § 34 Abs. 3 BJR-Satzung) ───────────────────────────────
    election_office = fields.Char(
        string='Zu besetzendes Amt',
        help='z. B. Vorsitz, stellvertretender Vorsitz, Beisitz. Nur bei Wahlen.',
    )
    seats = fields.Integer(
        string='Zu vergebende Sitze', default=1,
        help='Anzahl der in diesem Wahlgang zu besetzenden Sitze.',
    )
    ballot_round = fields.Integer(
        string='Wahlgang', default=1,
        help='1 = erster Wahlgang. Eine Stichwahl wird als weiterer Wahlgang '
             'mit eigenem Datensatz erfasst.',
    )
    runoff_parent_id = fields.Many2one(
        'kjr.assembly.decision', string='Stichwahl zu', ondelete='set null',
        # assembly_id ist im eingebetteten Formular nicht verfügbar und lässt sich
        # dort clientseitig nicht auswerten. Die zulässige Menge wird deshalb
        # serverseitig berechnet (allowed_runoff_parent_ids) und zusätzlich über
        # _check_runoff_parent geprüft — eine Domain ist nur UI, kein RPC-Schutz.
        domain="[('id', 'in', allowed_runoff_parent_ids)]",
        help='Vorangegangener Wahlgang, dessen Stichwahl dieser Datensatz ist. '
             'Zur Auswahl stehen nur Wahlgänge derselben Vollversammlung.',
    )
    allowed_runoff_parent_ids = fields.Many2many(
        'kjr.assembly.decision', 'kjr_decision_runoff_allowed_rel',
        'decision_id', 'parent_decision_id',
        string='Mögliche vorangegangene Wahlgänge',
        compute='_compute_allowed_runoff_parent_ids', store=False,
        help='Hilfswert für die Auswahl im Feld "Stichwahl zu": alle Wahlgänge '
             'derselben Vollversammlung außer diesem.',
    )
    runoff_ids = fields.One2many(
        'kjr.assembly.decision', 'runoff_parent_id', string='Stichwahlgänge',
    )
    candidate_ids = fields.One2many(
        'kjr.assembly.candidate', 'decision_id', string='Kandidat/innen',
    )
    majority_rule = fields.Selection([
        ('absolute', 'Absolute Mehrheit der gültigen Stimmen'),
        ('relative', 'Einfache (relative) Mehrheit, meiste Stimmen'),
    ], string='Erforderliche Mehrheit', default='absolute',
        help='Berechnungsgrundlage sind ausschließlich die auf Kandidat/innen '
             'entfallenen gültigen Stimmen; Enthaltungen und ungültige Stimmen '
             'bleiben nach § 33 Abs. 2 BJR-Satzung außer Betracht.')
    # TODO(KJR): Die Satzungsauszüge belegen die geheime Wahl (§ 34 Abs. 3), das
    # Stimmrecht "eine Stimme je Mitglied" (§ 33 Abs. 1) und den Ausschluss der
    # Enthaltungen (§ 33 Abs. 2). Welche Mehrheit für die Vorstandswahl konkret
    # erforderlich ist, ist NICHT belegt. Default ist deshalb bewusst die
    # strengere absolute Mehrheit; die relative Mehrheit ist je Wahlgang
    # umstellbar. Vor Go-live durch den KJR bestätigen lassen.
    election_valid_votes = fields.Integer(
        string='Gültige Kandidatenstimmen', compute='_compute_election',
        help='Summe der auf Kandidat/innen entfallenen Stimmen. Grundlage der '
             'Mehrheitsberechnung, ohne Enthaltungen und ungültige Stimmen.',
    )
    election_majority_needed = fields.Integer(
        string='Erforderliche Stimmen', compute='_compute_election',
        help='Bei absoluter Mehrheit: mehr als die Hälfte der gültigen '
             'Kandidatenstimmen. Bei relativer Mehrheit ohne feste Schwelle (0).',
    )
    election_state = fields.Selection([
        ('open', 'Offen / nicht ausgezählt'),
        ('elected', 'Gewählt'),
        ('runoff', 'Stichwahl erforderlich'),
        ('failed', 'Keine Wahl zustande gekommen'),
    ], string='Wahlergebnis', compute='_compute_election',
        help='Ergebnis des Wahlgangs. "Stichwahl erforderlich" bedeutet, dass '
             'noch nicht alle Sitze besetzt sind (fehlende Mehrheit oder '
             'Stimmengleichheit an der Sitzgrenze).')
    elected_names = fields.Char(
        string='Gewählt', compute='_compute_election',
        help='Namen der in diesem Wahlgang gewählten Kandidat/innen.',
    )
    plausibility_hint = fields.Char(
        string='Hinweis zur Auszählung', compute='_compute_plausibility_hint',
        help='Reiner Hinweis, keine Sperre: die Geschäftsstelle muss auch '
             'unvollständige oder strittige Auszählungen erfassen können.',
    )

    @api.depends('assembly_id', 'assembly_id.decision_ids',
                 'assembly_id.decision_ids.decision_type')
    def _compute_allowed_runoff_parent_ids(self):
        for rec in self:
            rec.allowed_runoff_parent_ids = rec.assembly_id.decision_ids.filtered(
                lambda d: d.decision_type == 'election' and d != rec)

    @api.constrains('runoff_parent_id', 'assembly_id', 'decision_type')
    def _check_runoff_parent(self):
        """Stichwahl darf nur auf einen Wahlgang derselben Versammlung zeigen."""
        for rec in self:
            parent = rec.runoff_parent_id
            if not parent:
                continue
            if parent == rec:
                raise ValidationError(_(
                    'Ein Wahlgang kann nicht die Stichwahl zu sich selbst sein.'))
            if parent.assembly_id != rec.assembly_id:
                raise ValidationError(_(
                    'Die Stichwahl muss sich auf einen Wahlgang derselben '
                    'Vollversammlung beziehen.'))
            if parent.decision_type != 'election':
                raise ValidationError(_(
                    'Eine Stichwahl kann sich nur auf eine Wahl beziehen, '
                    'nicht auf einen Sachbeschluss.'))

    @api.depends('vote_yes', 'vote_no', 'decision_type')
    def _compute_result(self):
        for rec in self:
            if rec.decision_type == 'election':
                # Wahlen werden über election_state ausgewiesen. Das Ja/Nein-
                # Ergebnisfeld bleibt hier bewusst unangetastet (kein Überschreiben
                # einer evtl. manuellen Eingabe).
                rec.result = rec.result or False
            elif not rec.vote_yes and not rec.vote_no:
                # Ohne erfasste Stimmen manuelle Angabe (z. B. "Vertagt") beibehalten.
                rec.result = rec.result or False
            elif rec.vote_yes > rec.vote_no:
                rec.result = 'accepted'
            else:
                rec.result = 'rejected'

    def _elected_candidates(self):
        """Gewählte Kandidat/innen dieses Wahlgangs.

        Berechnungsgrundlage sind ausschließlich die auf Kandidat/innen
        entfallenen Stimmen; Enthaltungen und ungültige Stimmen bleiben nach
        § 33 Abs. 2 BJR-Satzung außer Betracht. Bei Stimmengleichheit an der
        Sitzgrenze rückt niemand nach — dann ist eine Stichwahl nötig (es wird
        bewusst NICHT gelost oder nach Reihenfolge entschieden).
        """
        self.ensure_one()
        empty = self.env['kjr.assembly.candidate']
        if self.decision_type != 'election':
            return empty
        cands = self.candidate_ids.filtered(lambda c: not c.withdrawn and c.votes > 0)
        seats = max(self.seats or 0, 0)
        if not cands or not seats:
            return empty
        # Schwelle hier lokal bestimmen statt das berechnete Feld zu lesen —
        # sonst haengt _compute_is_elected ueber Umwege an _compute_election.
        threshold = self._election_threshold()
        ranked = cands.sorted(lambda c: (-c.votes, c.sequence, c.id))
        elected = empty
        for cand in ranked:
            if len(elected) >= seats:
                break
            if threshold and cand.votes < threshold:
                break
            tied = cands.filtered(lambda c: c.votes == cand.votes) - elected
            if len(tied) > seats - len(elected):
                # Stimmengleichheit an der Sitzgrenze -> Stichwahl.
                break
            elected |= cand
        return elected

    def _election_threshold(self):
        """Mindeststimmenzahl fuer die Wahl in diesem Wahlgang.

        Absolute Mehrheit = mehr als die Haelfte der gueltigen Kandidatenstimmen.
        Bemessungsgrundlage sind nur die auf Kandidat/innen entfallenen Stimmen,
        Enthaltungen und ungueltige Stimmen zaehlen nach Paragraph 33 Abs. 2
        BJR-Satzung nicht mit. Bei relativer Mehrheit gibt es keine feste
        Schwelle (0).
        """
        self.ensure_one()
        if self.majority_rule != 'absolute':
            return 0
        base = sum(self.candidate_ids.filtered(
            lambda c: not c.withdrawn).mapped('votes'))
        return base // 2 + 1 if base else 0

    @api.depends('decision_type', 'seats', 'majority_rule', 'vote_abstain',
                 'vote_invalid', 'ballots_cast',
                 'candidate_ids', 'candidate_ids.votes', 'candidate_ids.withdrawn')
    def _compute_election(self):
        for rec in self:
            if rec.decision_type != 'election':
                rec.election_valid_votes = 0
                rec.election_majority_needed = 0
                rec.election_state = False
                rec.elected_names = False
                continue
            cands = rec.candidate_ids.filtered(lambda c: not c.withdrawn)
            base = sum(cands.mapped('votes'))
            rec.election_valid_votes = base
            rec.election_majority_needed = rec._election_threshold()
            elected = rec._elected_candidates()
            rec.elected_names = ', '.join(elected.mapped('name')) or False
            seats = max(rec.seats or 0, 0)
            if not base:
                # Keine Kandidatenstimmen: entweder noch nicht ausgezaehlt oder
                # der Wahlgang ist (nur Enthaltungen/ungueltige) gescheitert.
                rec.election_state = (
                    'failed'
                    if (rec.vote_abstain or rec.vote_invalid or rec.ballots_cast)
                    else 'open'
                )
            elif seats and len(elected) >= seats:
                rec.election_state = 'elected'
            elif not elected and len(cands) <= 1:
                # Einzelkandidatur ohne erforderliche Mehrheit: eine Stichwahl
                # gäbe es hier nicht, der Wahlgang ist gescheitert.
                rec.election_state = 'failed'
            else:
                rec.election_state = 'runoff'

    @api.depends('decision_type', 'vote_yes', 'vote_no', 'vote_abstain', 'vote_invalid',
                 'ballots_cast', 'candidate_ids.votes', 'candidate_ids.withdrawn',
                 'assembly_id.attendee_count')
    def _compute_plausibility_hint(self):
        for rec in self:
            hints = []
            if rec.decision_type == 'election':
                counted = sum(rec.candidate_ids.filtered(
                    lambda c: not c.withdrawn).mapped('votes'))
            else:
                counted = rec.vote_yes + rec.vote_no
            counted += rec.vote_abstain + rec.vote_invalid
            if rec.ballots_cast and counted != rec.ballots_cast:
                hints.append(_(
                    'Erfasste Stimmen (%(counted)s) weichen von den abgegebenen '
                    'Stimmzetteln (%(cast)s) ab.'
                ) % {'counted': counted, 'cast': rec.ballots_cast})
            attendees = rec.assembly_id.attendee_count
            if attendees and counted > attendees:
                hints.append(_(
                    'Mehr Stimmen erfasst (%(counted)s) als Mitglieder anwesend '
                    '(%(att)s). § 33 Abs. 1 BJR-Satzung: eine Stimme je Mitglied.'
                ) % {'counted': counted, 'att': attendees})
            rec.plausibility_hint = ' '.join(hints) or False

    def action_create_runoff(self):
        """Stichwahl als weiteren Wahlgang anlegen.

        Übernommen werden alle noch nicht gewählten, nicht zurückgezogenen
        Kandidat/innen mit auf 0 zurückgesetzten Stimmen. Eine Begrenzung auf
        die zwei Bestplatzierten wird bewusst NICHT erzwungen — dafür liegt
        keine Satzungsgrundlage vor; die Versammlungsleitung streicht die
        Kandidatur im neuen Wahlgang bei Bedarf selbst.
        """
        self.ensure_one()
        elected = self._elected_candidates()
        remaining = self.candidate_ids.filtered(
            lambda c: not c.withdrawn) - elected
        office = self.election_office or self.name
        runoff = self.create({
            'assembly_id': self.assembly_id.id,
            'name': _('%(office)s: Stichwahl (%(round)s. Wahlgang)') % {
                'office': office, 'round': (self.ballot_round or 1) + 1,
            },
            'decision_type': 'election',
            'election_office': self.election_office,
            'majority_rule': self.majority_rule,
            'seats': max((self.seats or 0) - len(elected), 1),
            'ballot_round': (self.ballot_round or 1) + 1,
            'runoff_parent_id': self.id,
            'sequence': self.sequence,
            'candidate_ids': [
                (0, 0, {
                    'name': c.name,
                    'partner_id': c.partner_id.id,
                    'sequence': c.sequence,
                    'votes': 0,
                })
                for c in remaining
            ],
        })
        # Eigenständiger Formular-View — ohne view_id fiele Odoo auf das
        # generierte Default-Formular mit allen technischen Feldern zurück.
        view = self.env.ref('kjr_grant.view_kjr_assembly_decision_form')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Stichwahl'),
            'res_model': 'kjr.assembly.decision',
            'res_id': runoff.id,
            'view_mode': 'form',
            'view_id': view.id,
            'views': [(view.id, 'form')],
            'target': 'new',
        }


class KjrAssemblyCandidate(models.Model):
    """Kandidat/in eines Wahlgangs — bewusst NUR Stimmensummen.

    § 34 Abs. 3 BJR-Satzung schreibt für die Vorstandswahl eine GEHEIME Wahl
    vor. Geheim heißt: aus den gespeicherten Daten darf sich nicht
    rekonstruieren lassen, wer wie gestimmt hat. Dieses Modell speichert
    deshalb ausschließlich die vom Wahlausschuss ausgezählte Gesamtzahl der
    Stimmen je Kandidat/in sowie — auf dem Wahlgang — Enthaltungen und
    ungültige Stimmen.

    Es gibt hier bewusst KEIN Feld, das eine einzelne Stimme einer wählenden
    Person oder einem Mitgliedsverband zuordnet, und es gibt bewusst keine
    Stimmzettel-Einzeldatensätze. Ein solches Feld darf auch später nicht
    ergänzt werden: es würde das Wahlgeheimnis technisch aufheben, weil jede
    Auswertung (und jeder Datenbank-Export) das Stimmverhalten offenlegen
    könnte. Die Anwesenheitsliste der Versammlung (attendee_ids) bleibt davon
    unberührt — sie belegt die Teilnahme, nicht das Stimmverhalten.

    § 33 Abs. 1 BJR-Satzung: jedes Mitglied hat genau EINE Stimme; ein
    numerisches Stimmgewicht wird hier deshalb nicht verrechnet.
    """
    _name = 'kjr.assembly.candidate'
    _description = 'Kandidat/in einer Wahl (Vollversammlung)'
    _order = 'sequence, id'

    decision_id = fields.Many2one(
        'kjr.assembly.decision', string='Wahlgang', required=True, ondelete='cascade',
    )
    assembly_id = fields.Many2one(
        'kjr.assembly', string='Vollversammlung',
        related='decision_id.assembly_id', store=True, index=True,
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(
        string='Kandidat/in', required=True,
        help='Name wie im Protokoll geführt. Wird aus dem Kontakt vorbelegt, '
             'falls einer hinterlegt ist.',
    )
    partner_id = fields.Many2one(
        'res.partner', string='Kontakt', domain="[('is_company', '=', False)]",
        help='Optionale Verknüpfung mit dem Kontakt. Nicht erforderlich, '
             'Kandidaturen dürfen auch ohne angelegten Kontakt erfasst werden.',
    )
    votes = fields.Integer(
        string='Stimmen', default=0,
        help='Vom Wahlausschuss ausgezählte Gesamtzahl der auf diese Kandidatur '
             'entfallenen Stimmen. Einzelstimmen werden nicht gespeichert '
             '(geheime Wahl, § 34 Abs. 3 BJR-Satzung).',
    )
    withdrawn = fields.Boolean(
        string='Kandidatur zurückgezogen',
        help='Zurückgezogene Kandidaturen bleiben zur Dokumentation stehen, '
             'gehen aber nicht in die Auswertung ein.',
    )
    vote_share = fields.Float(
        string='Anteil (%)', compute='_compute_vote_share', digits=(5, 1),
        help='Anteil an den gültigen Kandidatenstimmen des Wahlgangs.',
    )
    is_elected = fields.Boolean(
        string='Gewählt', compute='_compute_is_elected', store=True, readonly=False,
        help='Wird aus den Stimmen ermittelt (Mehrheit ohne Enthaltungen, '
             'Sitzzahl des Wahlgangs) und kann von der Versammlungsleitung '
             'überschrieben werden, z. B. bei Ablehnung der Wahl.',
    )

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id and not self.name:
            self.name = self.partner_id.name

    @api.depends('votes', 'withdrawn', 'decision_id.candidate_ids.votes',
                 'decision_id.candidate_ids.withdrawn')
    def _compute_vote_share(self):
        for rec in self:
            base = sum(rec.decision_id.candidate_ids.filtered(
                lambda c: not c.withdrawn).mapped('votes'))
            rec.vote_share = (rec.votes * 100.0 / base) if base else 0.0

    @api.depends('votes', 'withdrawn', 'decision_id.decision_type', 'decision_id.seats',
                 'decision_id.majority_rule', 'decision_id.candidate_ids.votes',
                 'decision_id.candidate_ids.withdrawn')
    def _compute_is_elected(self):
        for rec in self:
            elected = rec.decision_id._elected_candidates() if rec.decision_id else None
            rec.is_elected = bool(elected) and rec in elected


class KjrAssemblyInvitation(models.Model):
    """Versandnachweis der Einladung je eingeladenem Verband.

    Genau ein Nachweis je Vollversammlung und Verband (Constraint). Die
    versandte Mail steht im Verlauf dieses Datensatzes (mail.thread; die
    Vorlage löscht nichts, auto_delete=False), Empfänger, Zeitpunkt, Absender
    und Anzahl zusätzlich in Feldern. ``state`` 'sent' heißt „an den
    Mailversand übergeben“; die Zustellung an den Mailserver zeigt
    ``delivery_state`` (aus der zuletzt erzeugten mail.mail).
    ``access_token`` sichert den Anmeldelink (controllers/assembly.py); er
    ist für die Empfänger der Einladung gedacht.

    Wer den Link sieht (bewusst offen, nicht per Feldgruppe gesperrt): Die
    versandte Mail bleibt als mail.message mit dem vollständigen Anmeldelink im
    Verlauf dieses Datensatzes (auto_delete=False, Nachweis der Ladung und
    delivery_state). Diese Nachricht darf lesen, wer den Nachweis lesen darf
    (mail.message folgt dem Dokument), also auch die Sachbearbeitung
    (group_kjr_reviewer, nur Lesen). Eine Sperre von access_token und
    registration_url auf die Leitung wäre daher nur Schein; die Felder sind
    deshalb offen für die Sachbearbeitung lesbar. Bekannte Folge: Wer den Link
    hat, kann über ihn Online-Anmeldungen dieses Verbands anlegen oder ändern
    (controllers/assembly.py). Die Sachbearbeitung gehört zur Geschäftsstelle
    und ist auf Vertraulichkeit verpflichtet; den Link nicht weitergeben.
    """
    _name = 'kjr.assembly.invitation'
    _description = 'Einladung zur Vollversammlung'
    _inherit = ['mail.thread']
    _order = 'assembly_id, member_id'
    _rec_name = 'member_id'

    assembly_id = fields.Many2one(
        'kjr.assembly', string='Vollversammlung', required=True, index=True,
        ondelete='cascade',
    )
    # restrict: ein versandter Nachweis darf nicht mit dem Kontakt verschwinden.
    member_id = fields.Many2one(
        'res.partner', string='Verband', required=True, index=True, ondelete='restrict',
    )
    company_id = fields.Many2one(related='assembly_id.company_id', store=True)
    state = fields.Selection([
        ('pending', 'Noch nicht versandt'),
        ('sent', 'Versandt'),
        ('no_address', 'Keine E-Mail-Adresse'),
    ], string='Status', default='pending', required=True, tracking=True)
    recipient_type = fields.Selection([
        ('delegates', 'Delegierte'),
        ('delegates_member', 'Delegierte und Verbandskontakt'),
        ('member', 'Verbandskontakt'),
    ], string='Empfänger', readonly=True,
        help='„Delegierte und Verbandskontakt“: Nicht alle Delegierten haben eine '
             'E-Mail-Adresse; die Einladung ging deshalb zusätzlich an die E-Mail des '
             'Verbands mit der Bitte um Weitergabe.')
    assembly_state = fields.Selection(related='assembly_id.state', string='Stand der Versammlung')
    can_resend = fields.Boolean(
        string='Erneut sendbar', compute='_compute_can_resend',
        help='„Erneut senden“ ist nur möglich, solange die Versammlung geplant oder '
             'eingeladen ist, ihr Termin in der Zukunft liegt und der Verband noch '
             'eingeladen ist.',
    )
    recipient_ids = fields.Many2many(
        'res.partner', 'kjr_assembly_invitation_recipient_rel', 'invitation_id', 'partner_id',
        string='Empfänger/innen', readonly=True,
    )
    date_sent = fields.Datetime(string='Versandt am', readonly=True, copy=False)
    sent_by_id = fields.Many2one('res.users', string='Versandt von', readonly=True, copy=False)
    send_count = fields.Integer(string='Anzahl Versendungen', readonly=True, copy=False)
    # Zuletzt erzeugte Mail. mail.mail ist nur für Administratoren lesbar
    # (mail/security/ir.model.access.csv), daher groups; gelesen wird sie nur
    # mit sudo in _compute_delivery_state.
    mail_id = fields.Many2one(
        'mail.mail', string='Versand-E-Mail', readonly=True, copy=False,
        ondelete='set null', groups='base.group_system',
    )
    delivery_state = fields.Selection([
        ('none', 'Keine E-Mail'),
        ('queued', 'In Warteschlange'),
        ('sent', 'An Mailserver übergeben'),
        ('failed', 'Fehlgeschlagen'),
        ('unknown', 'Unbekannt'),
    ], string='Zustellung', compute='_compute_delivery_state',
        help='Stand der zuletzt verschickten Einladungs-E-Mail. „In Warteschlange“: '
             'Odoo verschickt sie mit dem nächsten Lauf des Mailversands. '
             '„Fehlgeschlagen“: „Einladungen versenden“ verschickt sie erneut. '
             '„Unbekannt“: Die E-Mail wurde gelöscht (z. B. ältere Einladung).',
    )
    # groups = Sachbearbeitung (nicht nur Leitung): Der Link steht ohnehin in
    # der versandten Mail im Verlauf, siehe Klassen-Docstring.
    access_token = fields.Char(
        string='Zugangsschlüssel', copy=False, readonly=True,
        groups='kjr_grant.group_kjr_reviewer',
        default=lambda self: uuid.uuid4().hex,
    )
    registration_url = fields.Char(
        string='Anmeldelink', compute='_compute_registration_url',
        groups='kjr_grant.group_kjr_reviewer',
    )
    registration_ids = fields.One2many(
        'kjr.assembly.registration', 'invitation_id', string='Anmeldungen',
    )

    _assembly_member_uniq = models.Constraint(
        'UNIQUE(assembly_id, member_id)',
        'Für diesen Verband gibt es bei dieser Vollversammlung bereits eine Einladung.',
    )

    @api.depends('state', 'mail_id.state')
    def _compute_delivery_state(self):
        for rec in self:
            mail = rec.sudo().mail_id
            if mail:
                rec.delivery_state = MAIL_DELIVERY_STATE.get(mail.state, 'unknown')
            elif rec.state == 'sent':
                rec.delivery_state = 'unknown'
            else:
                rec.delivery_state = 'none'

    @api.depends('assembly_id.state', 'assembly_id.date',
                 'assembly_id.invited_member_ids', 'member_id')
    def _compute_can_resend(self):
        for rec in self:
            rec.can_resend = not rec._kjr_resend_blocker()

    def _kjr_resend_blocker(self):
        """Grund, warum dieser Nachweis nicht (erneut) versandt werden darf, sonst ''.

        Dieselben Sperren wie in kjr.assembly.action_send_invitations: Stand
        und Termin der Versammlung; dazu muss der Verband noch eingeladen sein.
        """
        self.ensure_one()
        assembly = self.assembly_id
        if assembly.state not in ('draft', 'invited'):
            return _('Einladungen lassen sich nur für eine geplante oder bereits eingeladene '
                     'Vollversammlung versenden.')
        if assembly.date and assembly.date <= fields.Datetime.now():
            return _('Der Termin der Vollversammlung liegt in der Vergangenheit; Einladungen '
                     'werden nicht mehr versandt.')
        if self.member_id not in assembly.invited_member_ids:
            return _('„%s“ steht nicht mehr in der Liste der eingeladenen Verbände; die '
                     'Einladung wird nicht erneut versandt.', self.member_id.display_name)
        return ''

    @api.depends('access_token')
    def _compute_registration_url(self):
        for rec in self:
            if rec.id and rec.access_token:
                rec.registration_url = '%s/vollversammlung/anmeldung/%s/%s' % (
                    rec.get_base_url(), rec.id, rec.access_token)
            else:
                rec.registration_url = False

    def _kjr_delegates_without_email(self):
        """Aktive Delegierte des Verbands ohne E-Mail-Adresse (erhalten keine eigene Mail)."""
        self.ensure_one()
        return self.member_id.sudo().kjr_vr_delegate_ids.filtered(
            lambda p: p.active and not (p.email or '').strip())

    def _kjr_recipients(self):
        """Empfänger der Einladung: Delegierte mit E-Mail, sonst der Verband selbst.

        Haben nicht alle Delegierten eine E-Mail-Adresse, geht die Einladung
        zusätzlich an die E-Mail des Verbands (Typ 'delegates_member', die Mail
        bittet um Weitergabe). mail.mail verschickt je Empfänger eine eigene
        Mail (_prepare_outgoing_list), Adressen anderer Empfänger sieht also
        niemand.
        """
        self.ensure_one()
        member = self.member_id.sudo()
        delegates = member.kjr_vr_delegate_ids.filtered(
            lambda p: p.active and (p.email or '').strip())
        member_has_email = bool((member.email or '').strip())
        if delegates:
            if self._kjr_delegates_without_email() and member_has_email:
                return delegates | member, 'delegates_member'
            return delegates, 'delegates'
        if member_has_email:
            return member, 'member'
        return self.env['res.partner'], False

    def _kjr_missing_email_note(self):
        """Notiz-Absatz: Delegierte ohne E-Mail je Verband (leer, wenn alle eine haben).

        Für die Versandnotiz an der Versammlung: Diese Delegierten haben keine
        eigene Einladung bekommen und müssen auf anderem Weg eingeladen werden.
        """
        parts = []
        for rec in self:
            lacking = rec._kjr_delegates_without_email()
            if lacking:
                parts.append('%s: %d' % (rec.member_id.name or '', len(lacking)))
        if not parts:
            return Markup()
        return Markup('<p>%s</p>') % _(
            'Delegierte ohne E-Mail-Adresse, bitte auf anderem Weg einladen (Verband: '
            'Anzahl): %s. Die Einladung ging dort zusätzlich an die E-Mail des Verbands, '
            'sofern vorhanden.', '; '.join(parts))

    def _kjr_send(self, force=False):
        """Einladung senden; liefert die tatsächlich versandten Nachweise.

        Ohne ``force`` werden schon versandte Nachweise übersprungen (kein
        Doppelversand). Wirft nie wegen eines einzelnen Verbands: Fehler landen
        mit Datensatz-ID und Fehlerart im Log (keine Personendaten), der
        Nachweis bleibt „noch nicht versandt“.

        „Versandt“ heißt: Die Mail steht in der Warteschlange (force_send=False).
        Die Zustellung selbst zeigt ``delivery_state`` aus ``mail_id``.
        """
        template = self.env.ref(INVITATION_TEMPLATE, raise_if_not_found=False)
        if not template:
            raise UserError(_('Die Mailvorlage für die Einladung zur Vollversammlung fehlt.'))
        sent = self.browse()
        for rec in self:
            if rec.state == 'sent' and not force:
                continue
            recipients, recipient_type = rec._kjr_recipients()
            if not recipients:
                rec.write({'state': 'no_address', 'recipient_ids': [(5, 0, 0)],
                           'recipient_type': False})
                continue
            try:
                with self.env.cr.savepoint():
                    rec.write({
                        'recipient_ids': [(6, 0, recipients.ids)],
                        'recipient_type': recipient_type,
                    })
                    # sudo wie bei allen Mailvorlagen dieses Moduls; die
                    # Schreibrechtprüfung steht im Aufrufer (check_access).
                    mail_id = template.sudo().send_mail(
                        rec.id, force_send=False,
                        email_values={'recipient_ids': [(6, 0, recipients.ids)]},
                    )
                    rec.write({
                        'state': 'sent',
                        'date_sent': fields.Datetime.now(),
                        'sent_by_id': self.env.uid,
                        'send_count': rec.send_count + 1,
                    })
                    # mail_id ist nur für Administratoren schreibbar (groups).
                    rec.sudo().mail_id = mail_id
            except Exception as err:  # noqa: BLE001 - ein Verband darf den Versand nicht kippen
                _logger.error('KJR Vollversammlung: Einladung %s nicht versandt (%s).',
                              rec.id, type(err).__name__)
                continue
            sent |= rec
        return sent

    def action_resend(self):
        """Einladung bewusst erneut senden (z. B. nach Wechsel der Delegierten).

        Nur solange die Versammlung geplant oder eingeladen ist, ihr Termin in
        der Zukunft liegt und der Verband noch eingeladen ist
        (_kjr_resend_blocker); sonst ginge ein gültiger Anmeldelink an einen
        Verband, der nicht (mehr) eingeladen ist.
        """
        self.check_access('write')
        for rec in self:
            blocker = rec._kjr_resend_blocker()
            if blocker:
                raise UserError(blocker)
        sent = self._kjr_send(force=True)
        for rec in sent:
            body = Markup('<p>%s</p>') % _(
                'Einladung an %s erneut versandt.', rec.member_id.name or '')
            body += rec._kjr_missing_email_note()
            rec.assembly_id.message_post(body=body, subtype_xmlid='mail.mt_note')
        return True

    def _kjr_register(self, name, email, phone, partner=None):
        """Anmeldung aus dem Anmeldelink anlegen oder aktualisieren.

        Gleiche E-Mail-Adresse unter DIESER Einladung = dieselbe Online-
        Anmeldung (wird aktualisiert, nicht verdoppelt). Gesucht wird nur in der
        eigenen Einladung und nur unter Online-Anmeldungen: Eine Anmeldung, die
        zu einem anderen Verband gehört oder von der Geschäftsstelle erfasst
        wurde, wird über den Link nie verändert oder umgehängt; dann entsteht
        eine neue Anmeldung, ohne dass die Seite verrät, ob die Adresse schon
        bekannt ist.

        ``partner`` übergibt nur der Controller, und nur für eine angemeldete
        Person mit ihrer eigenen E-Mail-Adresse. Eine im Formular eingetippte
        Adresse ist ungeprüft und ordnet deshalb keinen Kontakt zu; den
        Vorschlag dafür zeigt ``suggested_partner_id``, zuordnen muss die
        Geschäftsstelle.

        Läuft mit sudo aus dem Controller; Name, E-Mail und Telefon sind dort
        geprüft, das Telefon prüft zusätzlich die Bedingung am Modell.
        """
        self.ensure_one()
        # SUPERUSER statt sudo(): der Aufrufer ist meist der Public-User; sonst
        # stünde er als Autor der Verlaufseinträge (Muster
        # kjr.affiliation.request._kjr_create_from_signup).
        Registration = self.env['kjr.assembly.registration'].with_user(
            SUPERUSER_ID).with_context(mail_create_nolog=True, mail_create_nosubscribe=True)
        email = (email or '').strip()
        existing = Registration.search([
            ('assembly_id', '=', self.assembly_id.id),
            ('invitation_id', '=', self.id),
            ('member_id', '=', self.member_id.id),
            ('origin', '=', 'online'),
            ('email', '=ilike', escape_psql(email)),
        ], limit=1) if email else Registration
        vals = {
            'assembly_id': self.assembly_id.id,
            'invitation_id': self.id,
            'member_id': self.member_id.id,
            'name': name,
            'email': email,
            'phone': phone,
            'state': 'registered',
            'origin': 'online',
        }
        # Kontakt nur setzen, wenn der Controller einen geprüften übergibt. Eine
        # erneute Anmeldung ohne Login (z. B. Telefon korrigieren) darf die von
        # der Geschäftsstelle gesetzte Zuordnung (action_assign_suggested_partner)
        # und damit is_delegate nicht löschen.
        if partner:
            vals['partner_id'] = partner.id
        if existing:
            existing.write(vals)
            return existing
        return Registration.create(vals)


class KjrAssemblyRegistration(models.Model):
    """Anmeldung einer Person zur Vollversammlung.

    Telefon ist Pflicht: Anmeldungen per E-Mail ohne Telefonnummer haben dazu
    geführt, dass Delegierte am Sitzungstag nicht erreichbar waren und die
    Beschlussfähigkeit nicht geklärt werden konnte. Die Pflicht gilt am Modell
    (required + Formatprüfung), also für die Online-Anmeldung und für die
    Erfassung durch die Geschäftsstelle gleichermaßen.

    Datensparsam: E-Mail und Telefon ohne Feldhistorie (der Zweck braucht nur
    den aktuellen Stand); gelöscht wird die Anmeldung samt Verlauf nach der
    Frist ``kjr_grant.assembly_registration_retention_days`` (Cron
    ``_cron_purge_expired``).
    """
    _name = 'kjr.assembly.registration'
    _description = 'Anmeldung zur Vollversammlung'
    _inherit = ['mail.thread']
    _order = 'assembly_id, member_id, name'

    assembly_id = fields.Many2one(
        'kjr.assembly', string='Vollversammlung', required=True, index=True,
        ondelete='cascade',
    )
    invitation_id = fields.Many2one(
        'kjr.assembly.invitation', string='Einladung', ondelete='set null', index=True,
    )
    member_id = fields.Many2one(
        'res.partner', string='Verband', required=True, index=True,
        domain=[('is_company', '=', True), ('is_kjr_member', '=', True)],
    )
    partner_id = fields.Many2one(
        'res.partner', string='Kontakt', ondelete='set null',
        domain=[('is_company', '=', False)],
        help='Zugeordneter Kontakt. Die Online-Anmeldung setzt ihn nur, wenn die '
             'Person mit ihrem Konto angemeldet war und ihre eigene E-Mail-Adresse '
             'angegeben hat. Sonst ordnet die Geschäftsstelle von Hand zu '
             '(siehe „Vorschlag Kontakt“).',
    )
    suggested_partner_id = fields.Many2one(
        'res.partner', string='Vorschlag Kontakt (ungeprüft)',
        compute='_compute_suggested_partner_id',
        help='Delegierte/r oder Kontakt des Verbands mit derselben E-Mail-Adresse. '
             'Nur ein Vorschlag: Die Adresse im Anmeldeformular ist nicht geprüft. '
             'Bitte vor dem Zuordnen bestätigen, z. B. telefonisch.',
    )
    name = fields.Char(string='Name', required=True, tracking=True)
    email = fields.Char(string='E-Mail')
    phone = fields.Char(
        string='Telefon', required=True,
        help='Pflicht: Die Geschäftsstelle muss angemeldete Delegierte vor und am '
             'Tag der Vollversammlung erreichen können.',
    )
    is_delegate = fields.Boolean(
        string='Gemeldete/r Delegierte/r', compute='_compute_is_delegate',
        help='Die Person steht in der Delegiertenliste des Verbands.',
    )
    state = fields.Selection([
        ('registered', 'Angemeldet'),
        ('cancelled', 'Abgemeldet'),
    ], string='Status', default='registered', required=True, tracking=True)
    origin = fields.Selection([
        ('online', 'Online-Anmeldung'),
        ('office', 'Geschäftsstelle'),
    ], string='Herkunft', default='office', required=True)
    date_registered = fields.Datetime(
        string='Angemeldet am', default=fields.Datetime.now, readonly=True,
    )

    @api.depends('partner_id', 'email', 'member_id.kjr_vr_delegate_ids',
                 'member_id.child_ids.email')
    def _compute_suggested_partner_id(self):
        Partner = self.env['res.partner']
        for rec in self:
            email = (rec.email or '').strip().lower()
            if rec.partner_id or not email or not rec.member_id:
                rec.suggested_partner_id = Partner
                continue
            member = rec.member_id
            candidates = member.kjr_vr_delegate_ids | member.child_ids.filtered(
                lambda p: not p.is_company)
            rec.suggested_partner_id = candidates.filtered(
                lambda p: (p.email or '').strip().lower() == email)[:1]

    def action_assign_suggested_partner(self):
        """Vorschlag bewusst übernehmen (Geschäftsstelle, nach Prüfung)."""
        self.check_access('write')
        for rec in self:
            if rec.suggested_partner_id:
                rec.partner_id = rec.suggested_partner_id
        return True

    @api.depends('partner_id', 'member_id.kjr_vr_delegate_ids')
    def _compute_is_delegate(self):
        for rec in self:
            rec.is_delegate = bool(
                rec.partner_id and rec.partner_id in rec.member_id.kjr_vr_delegate_ids)

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id:
            self.name = self.name or self.partner_id.name
            self.email = self.email or self.partner_id.email
            self.phone = self.phone or self.partner_id.phone

    @api.constrains('phone')
    def _check_phone(self):
        for rec in self:
            phone = (rec.phone or '').strip()
            if not phone:
                raise ValidationError(_(
                    'Für die Anmeldung zur Vollversammlung ist eine Telefonnummer Pflicht.'))
            if not ASSEMBLY_PHONE_RE.match(phone):
                raise ValidationError(_(
                    'Telefon bitte nur mit Ziffern und den Zeichen + ( ) / - angeben '
                    '(z. B. 08321 1234-0).'))

    # ── DSGVO: Speicherbegrenzung ───────────────────────────────────────────

    @api.model
    def _kjr_retention_days(self):
        """Löschfrist in Tagen nach dem Versammlungstermin; 0 = Löschung aus.

        Einzige Auslegung des Parameters: Cron und Datenschutzhinweis der
        Anmeldeseite (controllers/assembly.py) nutzen dieselbe Umwandlung,
        damit der Hinweis nie eine andere Frist nennt, als tatsächlich gilt.
        Negative Werte gelten wie 0.
        """
        raw = self.env['ir.config_parameter'].sudo().get_param(PARAM_REGISTRATION_RETENTION)
        try:
            days = int(raw if raw not in (None, False, '') else DEFAULT_REGISTRATION_RETENTION_DAYS)
        except (TypeError, ValueError):
            days = DEFAULT_REGISTRATION_RETENTION_DAYS
        return max(days, 0)

    @api.model
    def _cron_purge_expired(self):
        """Anmeldungen nach Frist löschen (0 = aus).

        Nur bei durchgeführten oder abgesagten Versammlungen, deren Termin
        länger als die Frist zurückliegt. mail.thread.unlink entfernt
        Nachrichten, Feldhistorie und Follower mit. Die Anwesenheit (Verbände)
        und das Protokoll der Versammlung bleiben unberührt. Ins Protokoll
        kommt nur die Anzahl.
        """
        days = self._kjr_retention_days()
        if not days:
            return 0
        recs = self.sudo().with_context(active_test=False).search([
            ('assembly_id.state', 'in', ('done', 'cancelled')),
            ('assembly_id.date', '<', fields.Datetime.now() - timedelta(days=days)),
        ])
        count = len(recs)
        recs.unlink()
        _logger.info('KJR Vollversammlung: %d Anmeldung(en) nach Ablauf der Frist gelöscht.', count)
        return count
