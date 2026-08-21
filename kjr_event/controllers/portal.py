# -*- coding: utf-8 -*-
"""Portal-Zugriff für KJR-Kooperationspartner auf die Teilnehmerlisten.

Datenschutz-Hinweis (Befund K4 des Audits vom 21.08.2026):
Empfänger dieser Seiten sind EXTERNE Stellen (Kooperationspartner), die
Teilnehmerlisten für die Durchführung einer Maßnahme benötigen. Deshalb gilt
hier durchgängig eine Positivliste: Es verlässt nur das System, was für die
Durchführung erforderlich ist (Name, Alter, Status). Gesundheits- und
Kontaktangaben (Geburtsdatum, Ernährungs-Freitext, Bemerkungen,
Erziehungsberechtigte, Notfallkontakt) werden nicht nach außen gegeben.

Bewusst KEIN ``sudo()`` in diesem Controller: der Zugriff läuft vollständig
über die Rechte des angemeldeten Portalnutzers (Gruppe
``kjr_event.group_kjr_cooperation_partner`` + die Datensatzregeln in
``security/kjr_event_security.xml``). Nur so greift ein serverseitiger
Feldschutz (``groups=`` am Feld, Befund K3) überhaupt — ``sudo()`` würde ihn
umgehen. Wird hier künftig doch ein erhöhtes Recht gebraucht, darf es
ausschließlich feldweise und begründet gesetzt werden.
"""
from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError, MissingError
from odoo.addons.portal.controllers.portal import CustomerPortal


class KjrCooperationPortal(CustomerPortal):

    # Positivliste der Angaben, die an einen externen Kooperationspartner gehen.
    # Änderungen hier sind eine Datenschutz-Entscheidung, keine reine Anzeigefrage.
    _KJR_PORTAL_ATTENDEE_FIELDS = ('name', 'kjr_age', 'state')

    def _kjr_cooperation_events_domain(self):
        partner = request.env.user.partner_id
        return [
            '|',
            ('cooperation_partner_id', '=', partner.id),
            ('cooperation_user_ids', 'in', request.env.user.id),
        ]

    # ------------------------------------------------------------------
    # Hilfsfunktionen
    # ------------------------------------------------------------------
    def _kjr_field_selection(self, records, field_name):
        """Liefert die Selection-Paare eines Feldes zur Laufzeit.

        Die Statuswerte von ``event.registration`` werden bewusst NICHT geraten,
        sondern aus dem Feld gelesen (gleiche Vorgehensweise wie
        ``event.registration._kjr_waitlist_state``). Eine Selection kann als
        Liste, als Methodenname oder als Callable definiert sein.
        """
        selection = records._fields[field_name].selection
        if isinstance(selection, str):
            selection = getattr(records, selection)()
        elif callable(selection):
            selection = selection(records)
        return list(selection or [])

    def _kjr_confirmed_state_domain(self, registration_model):
        """Domain-Teil: nur bestätigte Anmeldungen.

        Odoo 19 kennt bei ``event.registration`` die Status ``draft``
        (unbestätigt), ``open`` (registriert), ``done`` (teilgenommen) und
        ``cancel`` (abgesagt). Für einen Externen sind nur ``open`` und ``done``
        relevant: Stornierungen und unbestätigte Anmeldungen — dort werden auch
        Wartelistenplätze geparkt, siehe ``_kjr_waitlist_state`` — gehören nicht
        in eine Liste, die das Haus verlässt.
        """
        keys = [key for key, _label in self._kjr_field_selection(registration_model, 'state')]
        confirmed = [key for key in ('open', 'done') if key in keys]
        if confirmed:
            return [('state', 'in', confirmed)]
        excluded = [key for key in ('draft', 'cancel') if key in keys]
        if excluded:
            return [('state', 'not in', excluded)]
        # TODO(KJR): Unbekannte Statuswerte (abweichende Odoo-Variante/Fremdmodul).
        # Dann bewusst nichts ausgeben statt versehentlich Stornierungen an einen
        # externen Empfänger zu übermitteln.
        return [('id', '=', False)]

    def _kjr_portal_attendee_rows(self, registrations):
        """Baut die Anzeigezeilen der externen Teilnehmerliste.

        Rückgabe sind einfache Dictionaries statt Recordsets: dadurch kann die
        Vorlage nur noch die hier freigegebenen Angaben ausgeben und nicht
        versehentlich weitere Felder des Datensatzes nachladen.
        """
        state_labels = dict(self._kjr_field_selection(registrations, 'state'))
        rows = []
        for reg in registrations:
            name = reg.name
            if not name:
                try:
                    name = reg.partner_id.name or ''
                except AccessError:
                    # Portalnutzer dürfen fremde Kontakte nicht lesen -> kein Name.
                    name = ''
            try:
                # kjr_age/has_birthdate leiten sich aus dem Geburtsdatum ab. Trägt
                # eines der Felder künftig ein groups= (Befund K3), entfällt die
                # Altersangabe hier, statt die Seite scheitern zu lassen.
                age = reg.kjr_age if reg.has_birthdate else None
            except AccessError:
                age = None
            rows.append({
                'name': name,
                'age': age,
                'state_label': state_labels.get(reg.state, ''),
            })
        return rows

    def _kjr_portal_dietary_summary(self, registrations):
        """Verpflegungsübersicht als reine ANZAHL je Kategorie, ohne Namensbezug.

        Fachliche Abwägung: Für die Verpflegung braucht ein Kooperationspartner,
        wie viele Portionen je Kategorie zu planen sind — nicht, wer welche
        Angabe gemacht hat. Die namentliche Zuordnung ist genau der Punkt, der
        aus einer Ernährungsangabe eine Gesundheits- bzw. Religionsangabe zu
        einer bestimmten minderjährigen Person macht (Allergie, halal, koscher).
        Deshalb nur aggregiert, und der Freitext ``dietary_note`` grundsätzlich
        gar nicht.

        TODO(KJR): Ob die Küche für einzelne Allergien doch eine personenscharfe
        Angabe braucht, entscheidet der KJR gemeinsam mit der
        Datenschutzbeauftragten. Bis dahin gilt die engere Variante.
        """
        try:
            values = registrations.mapped('dietary_requirements')
        except AccessError:
            # Feldschutz (groups=) greift -> gar keine Verpflegungsangabe ausgeben.
            return []
        labels = dict(self._kjr_field_selection(registrations, 'dietary_requirements'))
        counts = {}
        for value in values:
            if not value or value == 'none':
                continue
            counts[value] = counts.get(value, 0) + 1
        return [
            {'label': labels.get(key, key), 'count': count}
            for key, count in sorted(counts.items(), key=lambda item: labels.get(item[0], item[0]))
        ]

    # ------------------------------------------------------------------
    # Routen
    # ------------------------------------------------------------------
    @http.route(['/my/kjr-events'], type='http', auth='user', website=True)
    def kjr_cooperation_events(self, **kw):
        Event = request.env['event.event']
        events = Event.search(self._kjr_cooperation_events_domain(), order='date_begin desc')
        values = {
            'events': events,
            'page_name': 'kjr_events',
        }
        return request.render('kjr_event.portal_kjr_events', values)

    @http.route(['/my/kjr-events/<int:event_id>/teilnehmer'],
                type='http', auth='user', website=True)
    def kjr_cooperation_attendees(self, event_id, **kw):
        try:
            event = request.env['event.event'].browse(event_id)
            event.check_access('read')
            event.read(['name'])  # löst AccessError aus, falls nicht erlaubt
        except (AccessError, MissingError):
            return request.redirect('/my')
        # Zusätzliche Absicherung: Event muss zur Kooperation des Nutzers gehören.
        allowed = request.env['event.event'].search(
            self._kjr_cooperation_events_domain() + [('id', '=', event_id)])
        if not allowed:
            return request.redirect('/my/kjr-events')
        Registration = request.env['event.registration']
        # K4: nur bestätigte, keine Wartelistenplätze. kjr_is_waitlist wird
        # zusätzlich zum Status geprüft, weil ein Wartelistenplatz manuell
        # bestätigt worden sein kann, ohne dass das Kennzeichen fiel.
        domain = [('event_id', '=', event_id), ('kjr_is_waitlist', '=', False)]
        domain += self._kjr_confirmed_state_domain(Registration)
        registrations = Registration.search(domain, order='name')
        values = {
            'event': event,
            # Bewusst keine Recordsets in die Vorlage: nur die freigegebenen Angaben.
            'attendees': self._kjr_portal_attendee_rows(registrations),
            'dietary_summary': self._kjr_portal_dietary_summary(registrations),
            'page_name': 'kjr_events',
        }
        return request.render('kjr_event.portal_kjr_event_attendees', values)
