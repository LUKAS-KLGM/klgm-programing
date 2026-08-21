# -*- coding: utf-8 -*-
"""Teilnehmerliste für Zuschussanträge (lt. KJR OA TN-Liste)."""
import logging

from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class KjrGrantParticipant(models.Model):
    _name = 'kjr.grant.participant'
    _description = 'Teilnehmer'
    _order = 'sequence, name'

    application_id = fields.Many2one(
        'kjr.grant.application', string='Antrag',
        required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(string='Nr.', default=10)
    name = fields.Char(string='Name, Vorname', required=True)
    # Geburtsdatum wird im Website-Formular nicht mehr abgefragt (nur noch das Alter),
    # bleibt im Backend aber erfassbar (abgetippte Papieranträge).
    birthdate = fields.Date(string='Geburtsdatum')
    age = fields.Integer(
        string='Alter', compute='_compute_age', store=True, readonly=False,
        help='Alter zu Beginn der Maßnahme. Wird aus dem Geburtsdatum berechnet, '
             'sofern eines erfasst ist — sonst direkt eingeben.',
    )
    gender = fields.Selection([
        ('male',    'männlich'),
        ('female',  'weiblich'),
        ('diverse', 'divers'),
    ], string='Geschlecht')
    zip_code = fields.Char(string='PLZ')
    city = fields.Char(string='Wohnort')
    role_code = fields.Selection([
        ('EA', 'EA – ehrenamtliche/r Mitarbeiter/in'),
        ('HA', 'HA – haupt-/nebenberufliche/r Mitarbeiter/in'),
        ('HO', 'HO – Honorarkraft'),
        ('PR', 'PR – Praktikant/in'),
        ('SO', 'SO – sonstige'),
    ], string='Kennziffer',
        help='Kennziffer laut Teilnahmeliste des KJR Oberallgäu. '
             'Nur für Mitarbeitende/Leitung — Teilnehmende bleiben leer.')
    is_leader = fields.Boolean(string='Gruppenleitung', default=False)
    has_juleica = fields.Boolean(string='Juleica', default=False)
    note = fields.Char(string='Bemerkung')
    data_anonymized = fields.Boolean(
        string='Anonymisiert (DSGVO)', default=False, readonly=True, copy=False,
        help='Personenbezogene Daten wurden nach Ablauf der Aufbewahrungsfrist anonymisiert.',
    )

    # ── Berechnungen / Onchange ──────────────────────────────────────────────

    @api.depends('birthdate', 'application_id.measure_start')
    def _compute_age(self):
        """Alter aus dem Geburtsdatum ableiten, sofern eines erfasst ist.
        Ohne Geburtsdatum bleibt der manuell eingegebene Wert stehen (age ist
        store=True/readonly=False — im Website-Formular wird nur noch das Alter abgefragt)."""
        for rec in self:
            if rec.birthdate and rec.application_id.measure_start:
                start = rec.application_id.measure_start
                bd = rec.birthdate
                rec.age = start.year - bd.year - (
                    (start.month, start.day) < (bd.month, bd.day)
                )
            else:
                # Kein Geburtsdatum: erfassten Wert NICHT auf 0 überschreiben.
                rec.age = rec.age or 0

    @api.onchange('role_code')
    def _onchange_role_code(self):
        """Kennziffer gesetzt ⇒ Mitarbeitende/Leitung. is_leader trägt die gesamte
        Förderlogik (Betreuungsschlüssel 1:5, Ausnahme vom Altersfenster) und bleibt
        deshalb ein eigenes, manuell überschreibbares Feld."""
        for rec in self:
            rec.is_leader = bool(rec.role_code)

    # ── DSGVO ────────────────────────────────────────────────────────────────

    @api.model
    def _cron_anonymize_expired(self):
        """DSGVO (Storage Limitation): Teilnehmerdaten (z. T. Minderjähriger) nach Ablauf
        der Aufbewahrungsfrist anonymisieren statt zu löschen, damit aggregierte Nachweise
        (Anzahl, Juleica-Quote) für die Förderprüfung erhalten bleiben.
        Frist über System-Parameter 'kjr_grant.participant_retention_years' (Default 5 Jahre).
        TODO(DSGVO): Aufbewahrungsfrist und Anonymisierungsverfahren datenschutzrechtlich final bestätigen.

        Befund K6 (Datenschutz-Audit 21.08.2026): Diese Routine erfasste nur das
        Primärmodell. Dieselben Klarnamen lagen danach weiterhin in den
        hochgeladenen Dateien, in der Feldhistorie (mail.tracking.value) und im
        Chatter des Antrags. Deshalb übergibt der Lauf die gerade anonymisierten
        Klarnamen an kjr.grant.application._dsgvo_anonymize_related(), das die
        Nebenschauplätze mitzieht.

        Fristen: Die Nebenschauplätze können eine EIGENE Frist je Belegklasse haben
        (DSGVO_RETENTION_PARAMS in kjr_grant_application.py). Ist eine Klasse nicht
        gepflegt, gilt bewusst DIESE Basisfrist als Rückfallwert – die Spuren laufen
        also mit, statt stehen zu bleiben. Nur ein ausdrücklich auf 0 gesetzter
        Klassenparameter schaltet eine Klasse ab.

        ACHTUNG, Auslieferungszustand: Die Basisfrist steht auf 5 Jahren, zusätzlich
        sind retention_years_report = 5 und retention_years_receipt = 8 ausgeliefert.
        Der Nachlauf ist damit ab dem ersten Tag wirksam und ersetzt hochgeladene
        Dateien, löscht Trackingwerte und schwärzt Chatter-Texte – alles
        unwiederbringlich. TODO(KJR): Fristen je Belegklasse VOR dem Go-live
        bestätigen; bis dahin ggf. den Cron
        kjr_grant.cron_kjr_application_anonymize_related deaktivieren."""
        years = int(self.env['ir.config_parameter'].sudo().get_param(
            'kjr_grant.participant_retention_years', 5))
        cutoff = fields.Date.today() - relativedelta(years=years)
        stale = self.search([
            ('data_anonymized', '=', False),
            ('application_id.measure_end', '<', cutoff),
        ])
        # Klarnamen je Antrag merken, BEVOR sie überschrieben werden – danach sind
        # sie nicht mehr rekonstruierbar und im Chatter nicht mehr auffindbar.
        names_by_app = {}
        for rec in stale:
            if rec.name:
                names_by_app.setdefault(rec.application_id.id, []).append(rec.name)
            # Bewusst NICHT anonymisiert: age, gender, role_code — reine Aggregatmerkmale
            # ohne Personenbezug, werden für Statistik/Förderprüfung weiter benötigt.
            # (age bleibt trotz Löschung des Geburtsdatums stehen, s. _compute_age.)
            rec.write({
                'name': _('(anonymisiert)'),
                'birthdate': False,
                'zip_code': False,
                'city': False,
                'note': False,
                'data_anonymized': True,
            })
        if stale:
            _logger.info('DSGVO-Anonymisierung: %d Teilnehmerdatensätze anonymisiert', len(stale))
        # Nebenschauplätze am zugehörigen Antrag (Befund K6). Jede Belegklasse prüft
        # dort ihre eigene Frist; ist keine gesetzt, passiert nichts.
        applications = stale.application_id
        if applications:
            stats = applications._dsgvo_anonymize_related(participant_names=names_by_app)
            _logger.info(
                'DSGVO-Anonymisierung Nebenschauplätze: %d Anträge bearbeitet, '
                '%d Anhänge ersetzt, %d Trackingwerte entfernt, '
                '%d Chatter-Nachrichten geschwärzt',
                stats['applications'], stats['attachments'],
                stats['tracking'], stats['messages'],
            )
