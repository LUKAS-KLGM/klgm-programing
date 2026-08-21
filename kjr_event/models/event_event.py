# -*- coding: utf-8 -*-
"""KJR-spezifische Erweiterung der Veranstaltung (Ferienprogramm, Schulungen)."""
import logging
from datetime import datetime

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# DSGVO-Anonymisierung: Anzahl der Anmeldungen, die pro Schreibvorgang gebuendelt
# verarbeitet werden. Rein technischer Wert (Speicher/Transaktionsgroesse), keine
# fachliche Bedeutung.
_KJR_ANONYMIZE_CHUNK = 100


class EventEvent(models.Model):
    _inherit = 'event.event'

    is_kjr = fields.Boolean(string='KJR-Veranstaltung')
    kjr_event_type = fields.Selection([
        ('ferienprogramm', 'Ferienprogramm'),
        ('juleica_course', 'Juleica-Schulung'),
        ('rescue_course', 'Rettungsschwimmer-Kurs'),
        ('other', 'Sonstige'),
    ], string='KJR-Art')
    kjr_min_age = fields.Integer(string='Mindestalter', help='0 = keine Prüfung.')
    kjr_max_age = fields.Integer(string='Höchstalter', help='0 = keine Obergrenze.')
    # E13 – Mindestanzahl Teilnehmer (Nupian-Parität; Odoo kennt nativ nur ein Maximum)
    kjr_seats_min = fields.Integer(
        string='Mindestanzahl Teilnehmer',
        help='0 = keine Mindestanzahl. Odoo hat serienmäßig nur ein Sitzplatz-Maximum '
             '(seats_max) – dieses Feld ergänzt die von Nupian gewohnte Mindestanzahl, '
             'z. B. um zu entscheiden, ob eine Fahrt bei zu wenig Anmeldungen abgesagt wird.',
    )
    kjr_seats_min_reached = fields.Boolean(
        string='Mindestanzahl erreicht',
        compute='_compute_kjr_seats_min_reached',
        help='True, wenn keine Mindestanzahl gesetzt ist oder die aktuellen Anmeldungen '
             '(Registrierte + bereits Erschienene, also seats_taken) die Mindestanzahl erreichen.',
    )
    # E14 – Warteliste (Odoo kennt nativ nur ein Sitzplatz-Maximum, kein Nachrücken)
    kjr_waitlist_enabled = fields.Boolean(
        string='Warteliste aktiv',
        help='Wenn aktiv, wird eine Anmeldung bei ausgebuchter Veranstaltung nicht abgewiesen, '
             'sondern als Wartelistenplatz angelegt. Wartelistenplätze zählen NICHT auf die '
             'belegten Plätze (seats_taken) und blockieren sich daher nicht gegenseitig. '
             'Das Nachrücken löst die Geschäftsstelle bewusst manuell aus.',
    )
    kjr_waitlist_count = fields.Integer(
        string='Wartende Anmeldungen',
        compute='_compute_kjr_waitlist',
        help='Anzahl der Anmeldungen auf der Warteliste (abgesagte und archivierte zählen nicht).',
    )
    kjr_waitlist_ready = fields.Boolean(
        string='Nachrücken möglich',
        compute='_compute_kjr_waitlist',
        help='True, wenn mindestens ein regulärer Platz frei ist und mindestens eine Anmeldung '
             'auf der Warteliste steht.',
    )

    kjr_enforce_age_range = fields.Boolean(
        string='Altersgruppe erzwingen',
        help='Wenn aktiv, wird eine Anmeldung außerhalb der Altersgruppe hart abgewiesen '
             '(Constraint). Andernfalls wird sie nur als Warnung markiert.',
    )
    requires_parental_consent = fields.Boolean(
        string='Einwilligung Erziehungsberechtigter erforderlich',
        help='Bei Maßnahmen für Minderjährige: Einwilligung der Erziehungsberechtigten ist Pflicht. '
             'Erfassung auf der Website am besten über Veranstaltungs-Fragen (event.question) abbilden.',
    )
    is_juleica_course = fields.Boolean(string='Juleica-Ausbildung', compute='_compute_is_juleica', store=True)

    # E5/E6 – Zahlung
    payment_required = fields.Boolean(
        string='Zahlungspflichtig',
        help='Wenn aktiv, gilt die Veranstaltung als zahlungspflichtig; Anmeldungen erhalten '
             'einen offenen Zahlungsstatus statt "nicht erforderlich".',
    )

    # E9 – Schulungsanmeldung -> Rechnung
    training_product_id = fields.Many2one(
        'product.product',
        string='Schulungsprodukt (Rechnung)',
        help='Produkt, das bei zahlungspflichtigen Schulungsanmeldungen zur Rechnungserzeugung '
             'verwendet wird, wenn keine Ticket-/Verkaufslogik (event_sale) greift.',
    )

    # E4 – Kooperationspartner
    cooperation_partner_id = fields.Many2one(
        'res.partner',
        string='Kooperationspartner',
        help='Externer Partner (z. B. Verein/Schule), der über das Portal die Teilnehmerliste '
             'dieser Veranstaltung einsehen darf.',
    )
    cooperation_user_ids = fields.Many2many(
        'res.users',
        'kjr_event_cooperation_user_rel',
        'event_id',
        'user_id',
        string='Kooperations-Benutzer',
        help='Weitere Portalbenutzer mit Lesezugriff auf die Teilnehmerliste dieser Veranstaltung.',
    )

    # E11 – Dokumente (Website)
    kjr_document_ids = fields.One2many(
        'kjr.event.document', 'event_id',
        string='Dokumente',
        help='Zusätzliche Dateien (z. B. PDF-Merkblätter, Hinweise) zur Veranstaltung. '
             'Anzeigbar auf der Website als optionaler Sidebar-Block (Website-Editor → '
             'Anpassen → Sidebar-Blöcke → Dokumente).',
    )

    # E12 – Treffpunkt, Wichtig, Webseite (Nupian-Parität)
    kjr_meeting_point = fields.Text(
        string='Treffpunkt',
        help='Abfahrts-/Treffpunkt, falls abweichend vom eigentlichen Veranstaltungsort '
             '(z. B. "Bahnhof Sonthofen, Zustieg auch in Immenstadt/Kempten möglich"). '
             'Wird auf der Website im Ort-Block der Seitenleiste angezeigt.',
    )
    kjr_important_note = fields.Html(
        string='Wichtig',
        help='Auffällig hervorgehobener Hinweis (z. B. "Bitte 100€ in bar mitgeben") – wird '
             'immer sichtbar oberhalb der Beschreibung auf der Website angezeigt, unabhängig '
             'von den an-/abschaltbaren Seitenleisten-Blöcken.',
    )
    kjr_website_url = fields.Char(
        string='Webseite',
        help='Weiterführender externer Link (z. B. zur Webseite des Ausflugsziels). '
             'Nicht zu verwechseln mit dem internen Odoo-Seiten-Link (website_url) oder der '
             'Online-Event-URL (event_url) – dieser Link ist rein informativ.',
    )

    @api.depends('kjr_event_type')
    def _compute_is_juleica(self):
        for rec in self:
            rec.is_juleica_course = rec.kjr_event_type == 'juleica_course'

    @api.depends('kjr_seats_min', 'seats_taken')
    def _compute_kjr_seats_min_reached(self):
        for event in self:
            event.kjr_seats_min_reached = not event.kjr_seats_min or event.seats_taken >= event.kjr_seats_min

    # ------------------------------------------------------------------
    # E14 – Warteliste
    # ------------------------------------------------------------------
    @api.depends('kjr_waitlist_enabled', 'seats_max', 'seats_taken',
                 'registration_ids.kjr_is_waitlist', 'registration_ids.state',
                 'registration_ids.active')
    def _compute_kjr_waitlist(self):
        """Zählt die wartenden Anmeldungen und prüft, ob nachgerückt werden kann."""
        waiting_per_event = {}
        origins = self._origin
        if origins:
            groups = self.env['event.registration']._read_group(
                [('event_id', 'in', origins.ids),
                 ('kjr_is_waitlist', '=', True),
                 ('state', '!=', 'cancel')],
                groupby=['event_id'],
                aggregates=['__count'],
            )
            waiting_per_event = {event.id: count for event, count in groups}
        for event in self:
            waiting = waiting_per_event.get(event._origin.id, 0)
            free = event._kjr_free_seats()
            event.kjr_waitlist_count = waiting
            # Hinweis nur, wenn die Warteliste überhaupt geführt wird, jemand wartet
            # UND ein regulärer Platz frei ist (free is None = unbegrenzte Plätze).
            event.kjr_waitlist_ready = bool(
                event.kjr_waitlist_enabled and waiting and (free is None or free > 0)
            )

    def _kjr_free_seats(self):
        """Freie reguläre Plätze laut Odoo-Kernrechnung; ``None`` = unbegrenzt.

        Bewusst KEINE eigene Sitzplatzrechnung: Odoo führt die Belegung über
        ``seats_taken`` (registrierte + erschienene Anmeldungen) und daraus
        ``seats_available``. Wartelistenplätze werden im unbestätigten Status gehalten
        (siehe ``event.registration._kjr_waitlist_state``) und zählen dort nicht mit –
        deshalb kann hier direkt der Kernwert verwendet werden.

        Die Feldnamen werden defensiv geprüft (gleiches Muster wie im
        Statistik-Wizard), damit das Modul auch bei abweichenden Odoo-Editionen lädt.
        """
        self.ensure_one()
        limited = self.seats_limited if 'seats_limited' in self._fields else bool(self.seats_max)
        if not limited or not self.seats_max:
            return None
        if 'seats_available' in self._fields:
            return max(self.seats_available, 0)
        return max(self.seats_max - self.seats_taken, 0)

    def _kjr_waitlist_registrations(self):
        """Wartende Anmeldungen in Reihenfolge des Anmeldezeitpunkts (FIFO)."""
        self.ensure_one()
        if not self._origin.id:
            return self.env['event.registration']
        return self.env['event.registration'].search(
            [('event_id', '=', self._origin.id),
             ('kjr_is_waitlist', '=', True),
             ('state', '!=', 'cancel')],
            order='create_date asc, id asc',
        )

    def action_kjr_promote_from_waitlist(self):
        """Zieht die nächste wartende Anmeldung auf einen frei gewordenen Platz nach.

        BEWUSST MANUELL und nicht automatisch (kein Cron, kein Trigger beim Absagen):
        Die Geschäftsstelle will selbst entscheiden, WEN sie nachrückt – z. B. weil ein
        Geschwisterkind, eine Altersgruppe oder eine Zusage am Telefon Vorrang hat. Ein
        automatisches Nachrücken würde außerdem Absagen mit sofortigen Zusagemails
        beantworten, die sich nicht mehr zurücknehmen lassen.

        Diese Methode nimmt den ersten Platz der Warteliste (FIFO). Soll jemand anderes
        nachrücken, wird die Anmeldung direkt über
        ``event.registration.action_kjr_promote_waitlist()`` nachgezogen.
        """
        self.ensure_one()
        free = self._kjr_free_seats()
        if free is not None and free <= 0:
            raise UserError(_(
                'Für "%s" ist derzeit kein regulärer Platz frei. Bitte zuerst einen Platz '
                'freigeben (Anmeldung absagen) oder die maximale Teilnehmerzahl erhöhen.',
                self.name))
        registration = self._kjr_waitlist_registrations()[:1]
        if not registration:
            raise UserError(_('Für "%s" steht niemand auf der Warteliste.', self.name))
        registration.action_kjr_promote_waitlist()
        self.message_post(body=Markup('<p>%s</p>') % _(
            'Von der Warteliste nachgerückt: %s', registration.name or registration.display_name))
        return True

    # ------------------------------------------------------------------
    # DSGVO – Aufbewahrung / Anonymisierung der Anmeldedaten
    # (Datenschutz-Audit 21.08.2026, Befunde K5 und K6)
    # ------------------------------------------------------------------
    @api.model
    def _kjr_registration_retention_years(self):
        """Aufbewahrungsfrist für Anmeldedaten in Jahren; 0 = Automatik AUS.

        Die Frist ist eine fachliche/rechtliche Festlegung des KJR bzw. der
        Datenschutzbeauftragten und steht bewusst NICHT im Code, sondern im
        Systemparameter ``kjr_event.registration_retention_years``
        (Einstellungen → Technisch → Systemparameter).

        Auslieferungszustand ist 0, d. h. es wird nichts angefasst, solange keine
        Frist festgelegt ist. Das ist Absicht: eine erfundene Frist würde entweder
        zu früh löschen (Verstoß gegen Aufbewahrungspflichten) oder zu spät
        (Verstoß gegen Art. 5 Abs. 1 lit. e DSGVO).
        TODO(KJR): Frist festlegen und im Systemparameter eintragen.
        """
        param = self.env['ir.config_parameter'].sudo().get_param(
            'kjr_event.registration_retention_years', '0')
        try:
            years = int(param)
        except (TypeError, ValueError):
            _logger.warning(
                'DSGVO-Anonymisierung: Systemparameter '
                'kjr_event.registration_retention_years ist kein ganzzahliger Wert (%r) – '
                'Automatik bleibt aus.', param)
            return 0
        return years if years > 0 else 0

    @api.model
    def _kjr_anonymize_batch_limit(self):
        """Technische Obergrenze der je Cron-Lauf verarbeiteten Anmeldungen.

        Rein technisch (Laufzeit/Transaktionsgröße), kein fachlicher Wert: Der Cron
        läuft täglich und arbeitet einen Rückstand über mehrere Tage ab.
        """
        param = self.env['ir.config_parameter'].sudo().get_param(
            'kjr_event.registration_anonymize_batch_limit', '200')
        try:
            limit = int(param)
        except (TypeError, ValueError):
            limit = 200
        return max(limit, 1)

    @api.model
    def _kjr_anonymize_expired_registrations(self, registrations):
        """Leert die personenbezogenen Anteile der übergebenen Anmeldungen.

        Getrennt vom Cron, damit dieselbe Logik später auch für einen manuell
        ausgelösten Einzelfall (Löschersuchen nach Art. 17 DSGVO) verwendet werden
        kann, ohne die Fristprüfung zu duplizieren. Die Methode prüft KEINE Frist –
        das ist Aufgabe des Aufrufers.
        """
        Registration = self.env['event.registration'].sudo()
        reg_fields = Registration._fields

        # Merkerfeld gehört zu event.registration (anderer Zuständigkeitsbereich).
        # Fehlt es, wird bewusst NICHTS angefasst: ohne Merker wäre der Lauf nicht
        # idempotent, der Cron würde dieselben Datensätze täglich erneut bearbeiten
        # und das Ergebnis wäre nicht nachweisbar.
        if 'kjr_data_anonymized' not in reg_fields:
            _logger.error(
                'DSGVO-Anonymisierung übersprungen: Feld event.registration.kjr_data_anonymized '
                'fehlt. Ohne Merkerfeld ist der Lauf nicht idempotent – bitte Modul aktualisieren.')
            return 0

        # Geleert wird alles, was eine konkrete Person bezeichnet oder erreichbar
        # macht, sowie die Gesundheitsangaben (potenziell Art. 9 DSGVO):
        #   birthdate            – Geburtsdatum (Alter bleibt als Aggregat, s. u.)
        #   guardian_*           – Erziehungsberechtigte: Name und Telefon
        #   emergency_contact    – Notfallkontakt (dritte Person)
        #   dietary_requirements – Ernährungs-/Allergiekategorie: bewusst MIT geleert.
        #                          Es ist zwar ein Aggregatmerkmal, aber eine
        #                          Gesundheitskategorie und für den Förder-/
        #                          Verwendungsnachweis nicht erforderlich.
        #                          TODO(KJR): Falls die Küchenplanung die Quoten
        #                          dauerhaft braucht, vorher entscheiden.
        #   dietary_note, notes  – Freitexte, in der Praxis Allergien/Medikamente
        #   email, phone, mobile – Kontaktdaten der Anmeldung
        #   partner_id           – Zeiger auf den Kontaktdatensatz; bleibt er stehen,
        #                          läuft die ganze Anonymisierung ins Leere.
        #                          res.partner selbst wird NICHT angefasst (wird von
        #                          Buchungen/Rechnungen mitbenutzt, s. Docstring des Crons).
        blank_fields = (
            'birthdate', 'guardian_name', 'guardian_phone', 'emergency_contact',
            'dietary_requirements', 'dietary_note', 'notes',
            'email', 'phone', 'mobile', 'partner_id',
        )
        vals = {fname: False for fname in blank_fields if fname in reg_fields}
        vals['kjr_data_anonymized'] = True
        if 'name' in reg_fields:
            vals['name'] = _('(anonymisiert)')

        count = 0
        for index in range(0, len(registrations), _KJR_ANONYMIZE_CHUNK):
            batch = registrations[index:index + _KJR_ANONYMIZE_CHUNK]

            # Aggregatmerkmale sichern: kjr_age/is_minor sind stored computes auf
            # birthdate. Wird das Geburtsdatum geleert, rechnet Odoo sie auf 0/False
            # zurück – damit wäre die Altersstatistik der Freizeit zerstört, obwohl
            # das Alter selbst keinen Personenbezug mehr trägt. Deshalb Snapshot
            # vorher, Rückschreiben nachher.
            # Sauberer wäre, dass _compute_kjr_age den Wert für anonymisierte
            # Datensätze stehen lässt (so löst es kjr.grant.participant._compute_age).
            # Sobald das in event_registration.py umgesetzt ist, greift der
            # Rückschreibschritt unten schlicht nicht mehr.
            snapshot = {}
            if 'kjr_age' in reg_fields:
                snapshot = {
                    rec.id: (rec.kjr_age, rec.is_minor if 'is_minor' in reg_fields else None)
                    for rec in batch
                }

            # tracking_disable: sonst schreibt jedes write() die ALTEN Klarwerte als
            # mail.tracking.value in den Chatter – die Anonymisierung würde die Daten
            # dann selbst noch einmal duplizieren (genau Befund K6).
            batch.with_context(tracking_disable=True).write(vals)

            if snapshot:
                # Anstehende Neuberechnung erzwingen, damit der Rückschreibvorgang
                # nicht anschließend wieder überschrieben wird.
                batch.flush_recordset()
                for rec in batch:
                    age, minor = snapshot.get(rec.id, (None, None))
                    restore = {}
                    if age is not None and rec.kjr_age != age:
                        restore['kjr_age'] = age
                    if minor is not None and rec.is_minor != minor:
                        restore['is_minor'] = minor
                    if restore:
                        rec.with_context(tracking_disable=True).write(restore)

            self._kjr_purge_registration_copies(batch)
            count += len(batch)
        return count

    @api.model
    def _kjr_purge_registration_copies(self, registrations):
        """Räumt die Nebenschauplätze, an denen Kopien derselben Daten liegen (K6).

        Eine Anonymisierung, die nur die Felder des Primärdatensatzes leert, erfüllt
        ihren Zweck nicht: Name, Telefonnummer und Allergiehinweis stehen danach
        unverändert im Chatter, in der Feldhistorie und in hochgeladenen Dateien.

        ERFASST WIRD:
        * ``mail.tracking.value`` zu allen Chatter-Nachrichten der Anmeldung –
          Odoo speichert dort den alten UND den neuen Wert jedes verfolgten Feldes,
          bei Many2one zusätzlich den damaligen Anzeigenamen als Text.
        * ``mail.message`` mit ``model='event.registration'`` – Anmeldebestätigungen,
          Erinnerungen und interne Notizen enthalten Name und Mailadresse im Klartext.
          Beim Löschen einer Nachricht räumt Odoo die unmittelbar an ihr hängenden
          Anhänge und die ``mail.notification``-Zeilen mit ab.
        * ``ir.attachment`` mit ``res_model='event.registration'`` – hochgeladene
          Einwilligungen, Atteste, Merkblätter. Diese Dateien werden GELÖSCHT und
          nicht anonymisiert: ein Scan lässt sich nicht teilweise schwärzen. Das
          geschieht ausschließlich nach Ablauf der vom KJR festgelegten Frist.
        * ``mail.followers`` mit ``res_model='event.registration'`` – der Abonnenten-
          eintrag ist ein weiterer direkter Zeiger auf die betroffene Person.
        * Freitext-Antworten auf Veranstaltungsfragen
          (``event.registration.answer.value_text_box``), falls das Modell vorhanden
          ist. Die ausgewählte Antwortoption (``value_answer_id``) bleibt stehen –
          sie ist eine Auswahlkategorie ohne Personenbezug und wird für die
          Auswertung der Veranstaltung gebraucht.

        BEWUSST NICHT ERFASST:
        * ``account.move``/``account.move.line`` samt deren Anhängen: Buchungsbelege
          sind hashverkettet und dürfen nicht gelöscht werden; die Verknüpfung
          ``kjr_training_invoice_id`` bleibt deshalb stehen. Der personenbezogene
          Anteil einer Rechnung muss auf der Buchhaltungsseite anonymisiert werden.
          TODO(DSGVO): eigene Routine, mit der Datenschutzbeauftragten abzustimmen.
        * ``res.partner``: derselbe Kontakt hängt an Rechnungen, Vermietungen und
          Belegungen. Ein modulweiter Kontakt darf nicht von der Veranstaltungsseite
          aus geleert werden. TODO(DSGVO): querschnittliche Entscheidung nötig.
        * Chatter-Nachrichten AN DER VERANSTALTUNG (``model='event.event'``): dort
          steht z. B. der Name der nachgerückten Person aus
          ``action_kjr_promote_from_waitlist``. Sie lassen sich nicht zuverlässig von
          fachlichen Notizen der Geschäftsstelle unterscheiden und werden deshalb
          nicht pauschal gelöscht. Bekannter Rückstand, TODO(KJR).
        * Datenbank-Backups: liegen außerhalb der Anwendung (Hosting).
        """
        if not registrations:
            return
        reg_ids = registrations.ids

        messages = self.env['mail.message'].sudo().search([
            ('model', '=', 'event.registration'), ('res_id', 'in', reg_ids)])
        if messages:
            # Reihenfolge: Tracking-Werte zuerst explizit, damit die Anzahl im Log
            # stimmt – über die Kaskade des Fremdschlüssels würden sie ohnehin fallen.
            trackings = self.env['mail.tracking.value'].sudo().search([
                ('mail_message_id', 'in', messages.ids)])
            tracking_count = len(trackings)
            message_count = len(messages)
            trackings.unlink()
            messages.unlink()
            _logger.info(
                'DSGVO-Anonymisierung: %d Chatter-Nachrichten und %d Feldhistorien-Einträge '
                'zu Anmeldungen entfernt', message_count, tracking_count)

        attachments = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'event.registration'), ('res_id', 'in', reg_ids)])
        if attachments:
            _logger.info('DSGVO-Anonymisierung: %d Anhänge zu Anmeldungen gelöscht',
                         len(attachments))
            attachments.unlink()

        followers = self.env['mail.followers'].sudo().search([
            ('res_model', '=', 'event.registration'), ('res_id', 'in', reg_ids)])
        followers.unlink()

        # Freitext-Antworten auf Veranstaltungsfragen (Odoo-Standardmodell).
        # Defensiv geprüft, damit das Modul auch bei abweichenden Odoo-Editionen lädt
        # (gleiches Muster wie _kjr_free_seats).
        if 'event.registration.answer' in self.env:
            Answer = self.env['event.registration.answer'].sudo()
            if 'value_text_box' in Answer._fields:
                answers = Answer.search([
                    ('registration_id', 'in', reg_ids), ('value_text_box', '!=', False)])
                if answers:
                    answers.write({'value_text_box': False})

    @api.model
    def _cron_kjr_anonymize_expired_registrations(self):
        """DSGVO: Anmeldedaten nach Ablauf der Aufbewahrungsfrist anonymisieren.

        Hintergrund (Datenschutz-Audit 21.08.2026, Befund K5): Für Anmeldungen gab
        es bisher keinen Verfallsmechanismus – Geburtsdatum, Allergiehinweis und
        Notfallkontakt einer Freizeit aus 2027 hätten 2035 unverändert in der
        Datenbank gestanden. Einschätzung des Audits: Art. 5 Abs. 1 lit. e DSGVO,
        bei Gesundheitsangaben Minderjähriger mit erhöhtem Gewicht.

        ANONYMISIEREN STATT LÖSCHEN, weil die Veranstaltung als solche nachweispflichtig
        bleibt: Teilnehmerzahl, Altersstruktur und Wartelisten-/Zahlungsstatus gehen in
        Statistik und Verwendungsnachweis ein. Erhalten bleiben deshalb bewusst
        ``kjr_age``/``is_minor`` (Altersgruppe, nach Wegfall des Geburtsdatums ohne
        Personenbezug), ``state``, ``kjr_is_waitlist``, die Zahlungsfelder und die
        Verknüpfung zur Schulungsrechnung. Was geleert bzw. mitgeräumt wird, steht in
        ``_kjr_anonymize_expired_registrations`` und ``_kjr_purge_registration_copies``.

        BEZUGSPUNKT ist das ENDE der Veranstaltung (``event_id.date_end``), nicht das
        Anmeldedatum: Die Erforderlichkeit der Gesundheits- und Notfalldaten erledigt
        sich mit der Rückkehr von der Freizeit, und eine ein Jahr vorher eingegangene
        Anmeldung darf deswegen nicht ein Jahr früher verfallen. Gezählt werden volle
        Kalenderjahre nach dem Ende (Jahresend-Anker, s. Kommentar am Stichtag).

        AUSLIEFERUNGSZUSTAND: AUS. Der Systemparameter
        ``kjr_event.registration_retention_years`` steht auf 0; dann kehrt dieser Cron
        sofort und ohne Datenbankzugriff auf Anmeldungen zurück. Es wird nichts
        anonymisiert, solange der KJR keine Frist festgelegt hat.
        TODO(KJR)/TODO(DSGVO): Frist je Datenart festlegen. Anhaltspunkte aus den
        Projektunterlagen – ausdrücklich nur Anhaltspunkte, keine Rechtsaussage und
        keine Vorbelegung: 8 Jahre nach § 147 AO / § 257 HGB für Buchungsbelege,
        5 Jahre nach ANBest-P Nr. 6.6 für Zuwendungsunterlagen, "1 Jahr nach dem
        Ferienprogramm" als ausdrücklich selbstdefinierte Policy des KJR ohne
        gesetzliche Grundlage. Für Gesundheits- und Notfalldaten ist eine kürzere
        Frist als für die zahlungsrelevanten Felder denkbar; das ist eine Festlegung
        der Datenschutzbeauftragten, keine Codeentscheidung.

        Abgesagte und archivierte Anmeldungen werden ausdrücklich mit erfasst
        (``active_test=False``) – gerade dort liegen Daten, die niemand mehr ansieht.
        """
        years = self._kjr_registration_retention_years()
        if not years:
            # Frist nicht gepflegt: Automatik aus. Bewusst nur eine Debug-Meldung,
            # damit das Log bei täglichem Lauf nicht zuläuft.
            _logger.debug(
                'DSGVO-Anonymisierung übersprungen: kjr_event.registration_retention_years = 0 '
                '(keine Frist festgelegt).')
            return 0

        # Merkerfeld vor der Suche prüfen: es steht im Suchbereich, und ohne Merker
        # darf ohnehin nicht anonymisiert werden (Idempotenz, s. u.).
        if 'kjr_data_anonymized' not in self.env['event.registration']._fields:
            _logger.error(
                'DSGVO-Anonymisierung übersprungen: Feld event.registration.kjr_data_anonymized '
                'fehlt. Ohne Merkerfeld ist der Lauf nicht idempotent – bitte Modul aktualisieren.')
            return 0

        # Jahresend-Anker: gezählt werden volle Kalenderjahre NACH dem Jahr, in dem
        # die Veranstaltung endete. Eine Freizeit mit Ende 2027 und einer Frist von
        # 5 Jahren ist damit erst ab dem 01.01.2033 fällig und nicht schon irgendwann
        # im Laufe des Jahres 2032. Bewusst die spätere Variante: zu früh zu
        # anonymisieren würde eine etwaige Aufbewahrungspflicht verletzen. Gleicher
        # Anker wie in kjr_grant (_dsgvo_cutoff_date), damit beide Module denselben
        # Stichtag rechnen.
        cutoff = datetime(fields.Date.today().year - years, 1, 1)
        stale = self.env['event.registration'].sudo().with_context(active_test=False).search(
            [('kjr_data_anonymized', '=', False),
             ('event_id.date_end', '!=', False),
             ('event_id.date_end', '<', cutoff)],
            order='id asc',
            limit=self._kjr_anonymize_batch_limit(),
        )
        if not stale:
            return 0

        count = self._kjr_anonymize_expired_registrations(stale)
        _logger.info(
            'DSGVO-Anonymisierung: %d Anmeldungen anonymisiert (Frist %d Jahre ab dem '
            'Ende des Veranstaltungsjahres, Stichtag %s).',
            count, years, fields.Datetime.to_string(cutoff))
        return count
