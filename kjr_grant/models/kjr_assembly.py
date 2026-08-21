# -*- coding: utf-8 -*-
"""Vollversammlung des KJR — Einladung, Anwesenheit, Beschlüsse, Wahlen.

Rechtevergabe (siehe security/ir.model.access.csv): Vollversammlung, Beschlüsse
und Kandidaturen bilden EIN Nachweisdokument. Die Rechte der Gruppe
"Sachbearbeiter" (group_kjr_reviewer) sind deshalb über alle drei Modelle
einheitlich auf Lesen gesetzt — sonst könnten ausgezählte Stimmen nachträglich
verändert werden, ohne dass die Versammlung selbst bearbeitet werden darf.
Gepflegt wird das Protokoll von der Gruppe "Administrator".
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


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
    invited_member_ids = fields.Many2many(
        'res.partner', 'kjr_assembly_invited_rel',
        string='Eingeladene Verbände',
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

    def action_invite(self):
        """Alle KJR-Mitglieder mit VR einladen."""
        members = self.env['res.partner'].search(self._eligible_member_domain())
        vals = {
            'invited_member_ids': [(6, 0, members.ids)],
            'state': 'invited',
        }
        # Ladungsdatum nur vorbelegen, nie überschreiben — ein von Hand
        # gepflegtes Datum (nacherfasste Sitzung) bleibt erhalten.
        if not self.invitation_date:
            vals['invitation_date'] = fields.Date.context_today(self)
        self.write(vals)
        self.message_post(
            body=_('%d Mitgliedsverbände eingeladen.') % len(members),
            subtype_xmlid='mail.mt_note',
        )

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
             'Feld leer — dort gilt das Wahlergebnis (Feld "Wahlergebnis").')

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
        ('relative', 'Einfache (relative) Mehrheit — meiste Stimmen'),
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
             'Mehrheitsberechnung — ohne Enthaltungen und ungültige Stimmen.',
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
                    '(%(att)s) — § 33 Abs. 1 BJR-Satzung: eine Stimme je Mitglied.'
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
            'name': _('%(office)s — Stichwahl (%(round)s. Wahlgang)') % {
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
        help='Optionale Verknüpfung mit dem Kontakt. Nicht erforderlich — '
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
