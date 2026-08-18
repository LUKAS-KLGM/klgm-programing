# -*- coding: utf-8 -*-
"""KJR-spezifische Erweiterung der Veranstaltung (Ferienprogramm, Schulungen)."""
from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError


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
