# -*- coding: utf-8 -*-
"""Erweiterung res.partner für KJR-Mitgliedsverbände.

SCHREIBSCHUTZ DER MITGLIEDSCHAFTSDATEN
──────────────────────────────────────
Seit der Portalseite /my/verband pflegt ein Mitgliedsverband seine Kontakt- und
Adressdaten selbst. Die Angaben zur MITGLIEDSCHAFT sind dagegen Feststellungen
des Kreisjugendrings (Aufnahmebeschluss, Verbandstyp nach § 30 BJR-Satzung,
Vertretungsrecht) — der Verband darf sie sehen, aber nicht ändern.

`readonly=True` schützt davor NICHT: das ist eine reine UI-Angabe, ein direkter
RPC-Aufruf (`/web/dataset/call_kw` → `res.partner.write`) umgeht sie vollständig.
Serverseitig wirken nur zwei Mittel, und dieses Modul nutzt beide:

  (a) `groups='base.group_user'` am Feld. Die ORM prüft das in `write()`,
      `create()`, beim Lesen (`_fetch_field`) UND seit Odoo 19 auch in
      Suchdomains (`_field_to_sql` → `_check_field_access`). Ein `sudo()`-Env
      hebt die Prüfung auf (`Model._has_field_access`: `if ... or self.env.su`).
      Gesetzt an: kjr_member_type, kjr_member_number, kjr_active_since,
      kjr_vr_votes. Diese vier werden nirgends von einem Portal-User gelesen.

  (b) Der Wächter `_kjr_assert_member_status_writable()` in `write()`/`create()`.
      Er blockt Schreibzugriffe nicht-interner Nutzer auf ALLE sechs Felder der
      Liste KJR_MEMBER_STATUS_FIELDS — also auch auf `is_kjr_member` und
      `kjr_vr_right`, die aus den unten dokumentierten Gründen KEIN `groups=`
      tragen dürfen.

WARUM is_kjr_member UND kjr_vr_right KEIN groups= BEKOMMEN
  * `is_kjr_member` ist bewusst namensgleich ein zweites Mal in
    kjr_rental/models/res_partner.py definiert (ADR-1: kjr_rental hängt NICHT
    von kjr_grant ab). Beide Definitionen teilen sich eine Spalte und werden von
    der ORM verschmolzen. Ein hier gesetztes `groups=` würde deshalb auch für
    kjr_rental gelten — obwohl der dortige Modul-Docstring ausdrücklich verlangt,
    Zusatzattribute nicht einseitig zu setzen. Betroffen wäre u. a. der
    gespeicherte Compute `KjrRentalOrder._compute_is_member`
    (`@api.depends('partner_id.is_kjr_member')`), der in dem Env läuft, das ihn
    auslöst — im Verleih-Portal auch ohne sudo.
  * `kjr_vr_right` wird in `KjrGrantApplication._check_completeness()` gelesen.
    Diese Methode hängt an `action_submit()`, und die Gruppe „Antragsteller"
    (group_kjr_applicant, ein Portal-Profil) hat laut ir.model.access Schreib-
    und Anlagerecht auf kjr.grant.application. Ein `groups=` würde diesen Pfad
    mit einem AccessError beenden.
Der Wächter (b) deckt beide Felder ohne diese Nebenwirkungen ab.

FOLGE FÜR DAS PORTAL: Die unter (a) geschützten Felder sind für einen
Portal-Nutzer serverseitig unsichtbar. Wer sie auf /my/verband ANZEIGEN will
(Anforderung: „der Verband soll sehen, was hinterlegt ist"), muss den Verband
dafür über `sudo()` lesen. Geschrieben werden dürfen sie auch mit sudo() nicht —
der Controller arbeitet mit einer Feld-Whitelist.
"""
from odoo import api, fields, models, _
from odoo.exceptions import AccessError

# Feststellungen des KJR über die Mitgliedschaft eines Verbands. Sie entstehen
# durch Beschluss der Vollversammlung bzw. durch Verwaltungsakt der
# Geschäftsstelle und sind kein Selbstauskunftsfeld des Verbands. Wer diese
# Liste ändert, muss die Feld-Whitelist des Portal-Controllers
# (/my/verband, controllers/portal.py) gegenprüfen.
KJR_MEMBER_STATUS_FIELDS = (
    'is_kjr_member',
    'kjr_member_type',
    'kjr_member_number',
    'kjr_vr_right',
    'kjr_vr_votes',
    'kjr_active_since',
)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_kjr_member = fields.Boolean(
        string='KJR-Mitgliedsverband', default=False,
        help='Nur Verbände mit diesem Flag sind antragsberechtigt. '
             'Wird automatisch als Firma (Unternehmen) behandelt.',
    )

    @api.onchange('is_kjr_member')
    def _onchange_is_kjr_member(self):
        if self.is_kjr_member and not self.is_company:
            self.is_company = True
    kjr_member_type = fields.Selection([
        ('large_umbrella', 'Dachverband groß (§ 30 Abs. 2b BJR-Satzung)'),
        ('small_umbrella', 'Dachverband klein (§ 30 Abs. 2a BJR-Satzung)'),
        ('large_assoc',    'Jugendverband groß (§ 30 Abs. 2b BJR-Satzung)'),
        ('assoc',          'Jugendverband (§ 30 Abs. 2a BJR-Satzung)'),
        ('group',          'Jugendgruppe (§ 30 Abs. 2c BJR-Satzung)'),
        ('open',           'Offene Jugendeinrichtung'),
    ], string='Verbandstyp', groups='base.group_user',
        help='Einstufung nach § 30 BJR-Satzung. Feststellung des KJR — im Portal '
             'nur sichtbar, Änderungen laufen über die Geschäftsstelle.',
    )
    kjr_member_number = fields.Char(
        string='Mitgliedsnummer KJR', copy=False, groups='base.group_user',
        help='Vergibt die Geschäftsstelle. Feststellung des KJR — im Portal nur '
             'sichtbar, Änderungen laufen über die Geschäftsstelle.',
    )
    # TODO(KJR): Die Gap-Analyse (Vault, "KJR Funktions-Gap-Analyse 2026-06.md",
    # Abschnitt Antragsberechtigung) haelt fest, dass Antragsberechtigung und
    # Stimmrecht in der Vollversammlung zu TRENNEN sind — massgeblich ist die
    # Mitgliedschaft im KJR, nicht das Vertretungsrecht. Der Vollstaendigkeits-
    # check in kjr_grant_application.py (_check_completeness) sperrt derzeit
    # jedoch Antraege ohne kjr_vr_right. Vor Umbau (eigenes Feld
    # member_status / Pruefung je Foerderlinie) Kundenentscheidung einholen und
    # gegen die gueltige KJR-Richtlinie § 3.1 verifizieren.
    kjr_vr_right = fields.Boolean(
        string='Vertretungsrecht in Vollversammlung', default=False,
        help='Kennzeichnet Verbände mit Sitz und Stimme in der KJR-Vollversammlung. '
             'Dient derzeit zusätzlich als Prüfkriterium der Antragsberechtigung '
             '(§ 3.1 Richtlinien) — siehe TODO(KJR) im Code.',
    )
    kjr_vr_delegate_ids = fields.Many2many(
        'res.partner', 'kjr_partner_delegate_rel', 'partner_id', 'delegate_id',
        string='Vertreter/innen',
        help='Kontaktpersonen die den Verband in der KJR-Vollversammlung vertreten.',
        domain="[('is_company', '=', False)]",
    )
    kjr_vr_delegate_count = fields.Integer(
        string='Anzahl Vertreter', compute='_compute_delegate_count',
    )
    # HISTORISCH — nicht mehr verwenden.
    # Nach § 33 Abs. 1 der Satzung hat jedes Mitglied in der Vollversammlung
    # genau EINE Stimme; ein numerisches Stimmgewicht je Verbandstyp existiert
    # nicht. Quorum und Abstimmungen in kjr.assembly zaehlen entsprechend je
    # stimmberechtigtem Mitgliedsverband eine Stimme und lesen dieses Feld
    # nirgends aus. Das Feld bleibt nur erhalten, weil es bereits gepflegte
    # Altdaten enthalten kann; es ist aus dem Kontaktformular entfernt.
    kjr_vr_votes = fields.Integer(
        string='Stimmen in Vollversammlung (historisch)', default=0,
        groups='base.group_user',
        help='Historisches Feld ohne fachliche Wirkung. Nach § 33 Abs. 1 der '
             'Satzung hat jedes Mitglied in der Vollversammlung genau EINE '
             'Stimme; ein numerisches Stimmgewicht gibt es nicht. Der Wert wird '
             'in keiner Berechnung, Auswertung oder Abstimmung verwendet.',
    )
    kjr_active_since = fields.Date(
        string='Mitglied seit', groups='base.group_user',
        help='Beginn der Mitgliedschaft laut Aufnahmebeschluss. Feststellung des '
             'KJR — im Portal nur sichtbar, Änderungen laufen über die '
             'Geschäftsstelle.',
    )
    kjr_grant_ids = fields.One2many(
        'kjr.grant.application', 'partner_id', string='Zuschussanträge',
    )
    kjr_juleica_ids = fields.One2many('kjr.juleica', 'partner_id', string='Juleica-Karten')
    kjr_grant_count = fields.Integer(
        string='Anzahl Anträge', compute='_compute_kjr_grant_count',
    )
    kjr_grant_total_approved = fields.Float(
        string='Bewilligte Zuschüsse gesamt (€)',
        compute='_compute_kjr_grant_count', digits=(10, 2),
    )
    # ── Ehrenamtsstunden ─────────────────────────────────────────────────────
    volunteer_log_ids = fields.One2many(
        'kjr.volunteer.log', 'partner_id', string='Ehrenamtsstunden',
    )
    volunteer_hours_total = fields.Float(
        string='Ehrenamtsstunden gesamt', compute='_compute_volunteer_hours',
        store=True, digits=(8, 2),
    )
    volunteer_log_count = fields.Integer(
        string='Anzahl Stundeneinträge', compute='_compute_volunteer_hours', store=True,
    )
    volunteer_first_date = fields.Date(
        string='Ehrenamt seit', compute='_compute_volunteer_hours', store=True,
    )
    volunteer_last_date = fields.Date(
        string='Letzter Ehrenamtseintrag', compute='_compute_volunteer_hours', store=True,
    )

    @api.depends('kjr_vr_delegate_ids')
    def _compute_delegate_count(self):
        for rec in self:
            rec.kjr_vr_delegate_count = len(rec.kjr_vr_delegate_ids)

    @api.depends('kjr_grant_ids', 'kjr_grant_ids.state', 'kjr_grant_ids.grant_approved')
    def _compute_kjr_grant_count(self):
        for rec in self:
            grants = rec.kjr_grant_ids
            rec.kjr_grant_count = len(grants)
            rec.kjr_grant_total_approved = sum(
                g.grant_approved for g in grants if g.state in ('approved', 'paid')
            )

    @api.depends('volunteer_log_ids', 'volunteer_log_ids.hours', 'volunteer_log_ids.date')
    def _compute_volunteer_hours(self):
        for rec in self:
            logs = rec.volunteer_log_ids
            rec.volunteer_hours_total = sum(logs.mapped('hours'))
            rec.volunteer_log_count = len(logs)
            dates = [d for d in logs.mapped('date') if d]
            rec.volunteer_first_date = min(dates) if dates else False
            rec.volunteer_last_date = max(dates) if dates else False

    # ══════════════════════════════════════════════════════════════════════════
    # SCHREIBSCHUTZ DER MITGLIEDSCHAFTSDATEN (siehe Modul-Docstring)
    # ══════════════════════════════════════════════════════════════════════════

    def _kjr_assert_member_status_writable(self, vals):
        """Verhindert, dass ein Portal-Nutzer die Mitgliedschaftsdaten setzt.

        Greift für jeden nicht-internen Nutzer (Portal, öffentlich) und damit
        auch für einen direkten RPC-Aufruf, den kein Template und kein
        Controller absichern kann.

        `self.env.su` ist bewusst ausgenommen: der Portal-Controller muss den
        Verband ohnehin mit sudo() schreiben (Portal-Nutzer haben auf
        res.partner laut base.access_res_partner_portal nur Leserecht), und
        Serverlogik, Import und Migrationen laufen ebenfalls mit sudo. Der
        Schutz gegen unerwünschte Felder liegt dort in der Feld-Whitelist des
        Controllers; hier wird der Weg abgeschnitten, der an jedem Controller
        vorbeiführt.
        """
        if self.env.su or self.env.user._is_internal():
            return
        touched = [name for name in KJR_MEMBER_STATUS_FIELDS if name in vals]
        if not touched:
            return
        labels = ', '.join(
            self._fields[name].string or name for name in touched
        )
        raise AccessError(_(
            'Die Angaben zur KJR-Mitgliedschaft (%s) stellt die Geschäftsstelle '
            'des Kreisjugendrings fest; sie können im Portal nicht geändert '
            'werden. Bitte wenden Sie sich für eine Korrektur an die '
            'Geschäftsstelle.'
        ) % labels)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._kjr_assert_member_status_writable(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._kjr_assert_member_status_writable(vals)
        return super().write(vals)

    def _volunteer_hours_by_category(self):
        """Stunden je Tätigkeitskategorie (für den Ehrenamtsnachweis).
        Liefert nur Kategorien mit Stunden > 0, in der Reihenfolge der Auswahl."""
        self.ensure_one()
        selection = self.env['kjr.volunteer.log']._fields['category'].selection
        totals = {}
        for log in self.volunteer_log_ids:
            totals[log.category] = totals.get(log.category, 0.0) + log.hours
        return [
            {'label': label, 'hours': totals[key]}
            for key, label in selection if totals.get(key)
        ]

    def action_kjr_volunteer_logs(self):
        """Ehrenamtsstunden dieser Person öffnen/erfassen."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ehrenamtsstunden'),
            'res_model': 'kjr.volunteer.log',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    def action_kjr_datenauskunft(self):
        """DSGVO Art. 15: Datenauskunft über die zu dieser Person/Organisation
        im KJR-Modul gespeicherten Daten als PDF."""
        self.ensure_one()
        return self.env.ref('kjr_grant.action_report_kjr_datenauskunft').report_action(self)
