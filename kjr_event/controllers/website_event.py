# -*- coding: utf-8 -*-
"""Frontend-Erweiterung der Online-Anmeldung um KJR-Felder und den Altersfilter."""
import logging
from datetime import timedelta

from odoo import http
from odoo.fields import Domain
from odoo.http import request
from odoo.addons.website_event.controllers.main import WebsiteEventController

_logger = logging.getLogger(__name__)


# Felder, die im Anmeldeformular je Teilnehmer/in erfasst werden können.
KJR_VALUE_FIELDS = (
    'birthdate', 'guardian_name', 'guardian_phone',
    'emergency_contact', 'dietary_requirements', 'dietary_note', 'notes',
)

# Kernfelder des STANDARD-Anmeldeformulars (website_event), über die eine Formularzeile
# wieder genau einer erzeugten Anmeldung zugeordnet wird. Sie stammen aus demselben POST
# wie die KJR-Felder und tragen dieselbe Namenskonvention "<counter>-<feldname>" (siehe
# views/website_event_templates.xml, Einschub in //t[@name='attendee_loop']).
# Reihenfolge = Prüfreihenfolge: der Name ist Pflichtfeld des Kernformulars, die übrigen
# Merkmale werden nur herangezogen, solange die Zuordnung noch nicht eindeutig ist.
KJR_MATCH_FIELDS = ('name', 'email', 'phone', 'event_ticket_id')

# Toleranz auf den Transaktionszeitstempel bei der Kandidatensuche (Sekunden).
# Domains serialisieren Datumswerte sekundengenau; eine Sekunde Puffer stellt sicher,
# dass die eigenen Anmeldungen sicher IM Fenster liegen. Das Fenster ist bewusst nur eine
# Vorauswahl und nie das Zuordnungskriterium (siehe _kjr_write_attendee_values).
KJR_CREATE_WINDOW_SECONDS = 1

# Muss zu ``website_event.WebsiteEventController.events()`` passen (dort hart als
# ``step = 12`` hinterlegt). Wird nur gebraucht, wenn der Altersfilter aktiv ist und
# die Trefferliste deshalb neu ermittelt werden muss.
KJR_EVENTS_PER_PAGE = 12

# Schnellfilter-Altersgruppen für die öffentliche Veranstaltungsübersicht.
#
# Herleitung (bewusst NICHT frei erfunden): Die einzige belastbare Altersspanne in den
# Stammdaten dieses Projekts ist das Förderfenster der KJR-OA-Zuschussrichtlinie —
# kjr_grant/data/kjr_grant_type_data.xml setzt bei allen Jugendarbeits-Förderarten
# min_age=5 / max_age=27. Die Gruppen decken dieses Fenster lückenlos ab und richten
# sich an den Schnitten aus, die im Ferienprogramm real vorkommen (Schuleintritt,
# Wechsel weiterführende Schule, Volljährigkeit). Der Bereich 18–27 wird als offene
# Gruppe "ab 18" geführt, weil Juleica-/Rettungsschwimmer-Schulungen dort typischerweise
# ohne Obergrenze ausgeschrieben sind.
#
# Angeboten wird eine Gruppe nur, wenn dafür tatsächlich Veranstaltungen mit gepflegter
# Altersangabe existieren (siehe _kjr_age_group_values) — die Buttons bilden damit die
# echten Stammdaten ab und nicht diese statische Liste.
#
# TODO(Kunde): Schnitte gegen das gedruckte Ferienprogramm gegenprüfen lassen. Im
# Datenbestand liegen bisher keine Veranstaltungen mit gepflegter Altersangabe vor, die
# Einteilung stützt sich deshalb allein auf das Förderfenster 5–27. Änderungen betreffen
# ausschließlich diese Liste — die Filterlogik selbst bleibt unberührt.
KJR_AGE_GROUPS = (
    ('5-7', '5–7 Jahre'),
    ('8-10', '8–10 Jahre'),
    ('11-13', '11–13 Jahre'),
    ('14-17', '14–17 Jahre'),
    ('18-', 'ab 18 Jahre'),
)

# Obergrenze für die Eingabe aus dem Query-String (reine Plausibilisierung).
KJR_AGE_MAX = 120


def _truthy(value):
    return bool(value) and str(value).lower() not in ('0', 'false', 'off', 'no')


def _kjr_norm_text(value):
    """Vergleichsform für Freitexte: Groß-/Kleinschreibung und Mehrfach-Leerzeichen egal."""
    return ' '.join(str(value or '').split()).casefold()


def _kjr_norm_phone(value):
    """Vergleichsform für Telefonnummern: nur die Ziffern.

    Odoo kann Telefonnummern beim Speichern umformatieren (Leerzeichen, Klammern,
    Ländervorwahl). Der Vergleich läuft deshalb über die reine Ziffernfolge und wird
    ohnehin nur als zusätzliches Unterscheidungsmerkmal verwendet.
    """
    return ''.join(ch for ch in str(value or '') if ch.isdigit())


class KjrWebsiteEventController(WebsiteEventController):

    # ------------------------------------------------------------------
    # Online-Anmeldung (E1)
    # ------------------------------------------------------------------

    def _kjr_extract_attendee_values(self, registrations):
        """Sammelt die KJR-Felder je Teilnehmer/in aus den geposteten Formulardaten.

        Das Frontend liefert die Felder unter ``<counter>-<feldname>`` (z. B. ``1-birthdate``).
        Rückgabe: Liste von Tupeln ``(counter, werte)`` in Formularreihenfolge.
        """
        # Anzahl Teilnehmer/innen anhand der Standardfelder bestimmen.
        counters = sorted({
            int(key.split('-', 1)[0])
            for key in registrations
            if '-' in key and key.split('-', 1)[0].isdigit()
        })
        result = []
        for counter in counters:
            prefix = '%d-' % counter
            values = {}
            for field in KJR_VALUE_FIELDS:
                key = prefix + field
                if key in registrations and registrations[key] not in (None, ''):
                    values[field] = registrations[key]
            consent_key = prefix + 'parental_consent'
            if consent_key in registrations:
                values['parental_consent'] = _truthy(registrations[consent_key])
            result.append((counter, values))
        return result

    def _kjr_extract_attendee_match_values(self, registrations):
        """Sammelt je Zähler die Kernfelder, an denen die Anmeldung wiedererkannt wird.

        Gleiche Namenskonvention wie in :meth:`_kjr_extract_attendee_values`
        (``<counter>-<feldname>``), aber ausschließlich Felder des Standardformulars
        (siehe ``KJR_MATCH_FIELDS``). Diese Werte schreibt der Standard-Controller
        unverändert auf die erzeugte Anmeldung; sie sind damit das fachliche Merkmal,
        über das die KJR-Zusatzangaben ihrem eigenen Datensatz zugeordnet werden.

        Rückgabe: ``{counter: {feldname: wert}}``.
        """
        result = {}
        for key, value in registrations.items():
            if '-' not in key or value in (None, ''):
                continue
            counter, field = key.split('-', 1)
            if not counter.isdigit() or field not in KJR_MATCH_FIELDS:
                continue
            result.setdefault(int(counter), {})[field] = value
        return result

    def _kjr_find_registration(self, candidates, match):
        """Sucht in ``candidates`` die eine Anmeldung, die zu den Formularwerten passt.

        Es wird stufenweise eingegrenzt: zuerst über den Namen (Pflichtfeld des
        Kernformulars), danach – nur solange noch mehrere Datensätze übrig sind – über
        E-Mail, Telefon und Ticketart.

        Rückgabe: Recordset. Genau EIN Datensatz bedeutet "eindeutig zugeordnet"; jede
        andere Länge (0 oder >1) bedeutet "nicht zuordenbar" — der Aufrufer schreibt
        dann bewusst nichts.
        """
        name = _kjr_norm_text(match.get('name'))
        if not name:
            # Ohne Namen gibt es kein fachliches Merkmal -> keine Zuordnung.
            return candidates.browse()
        found = candidates.filtered(lambda reg: _kjr_norm_text(reg.name) == name)
        if len(found) > 1 and match.get('email'):
            email = _kjr_norm_text(match['email'])
            found = found.filtered(lambda reg: _kjr_norm_text(reg.email) == email)
        if len(found) > 1 and match.get('phone'):
            phone = _kjr_norm_phone(match['phone'])
            found = found.filtered(lambda reg: _kjr_norm_phone(reg.phone) == phone)
        if len(found) > 1 and str(match.get('event_ticket_id') or '').isdigit():
            ticket_id = int(match['event_ticket_id'])
            found = found.filtered(lambda reg: reg.event_ticket_id.id == ticket_id)
        return found

    def _kjr_write_attendee_values(self, event, kjr_values, match_values, tx_start):
        """Schreibt die KJR-Zusatzangaben auf die Anmeldungen DIESER Anfrage.

        Die Zuordnung läuft ausdrücklich NICHT mehr über die Reihenfolge der neu
        erzeugten IDs (Befund K7 des Datenschutz-Audits vom 21.08.2026). PostgreSQL
        arbeitet im Modus READ COMMITTED: meldet sich zeitgleich eine zweite Familie zur
        selben Veranstaltung an und wird deren Transaktion währenddessen festgeschrieben,
        stehen ihre Anmeldungen in genau derselben Ergebnismenge. Ein positionsweises
        ``zip()`` hat dann Geburtsdatum, Ernährungs-/Allergiehinweis, Notfallkontakt und
        Elterntelefon auf die Anmeldung eines fremden Kindes geschrieben.

        Stattdessen zweistufig:

        1. Kandidatenmenge so eng wie möglich fassen: nur diese Veranstaltung, nur
           Anmeldungen aus dem Zeitfenster dieser Transaktion, nur solche desselben
           erzeugenden Benutzers.
        2. Innerhalb dieser Menge wird jede Formularzeile über ihre eigenen Kernfelder
           (Name, bei Bedarf zusätzlich E-Mail, Telefon, Ticketart) genau EINEM Datensatz
           zugeordnet; bereits vergebene Datensätze scheiden aus. Ist die Zuordnung nicht
           eindeutig, wird für diese Zeile NICHTS geschrieben und ein Fehler
           protokolliert. Eine fehlende Allergieangabe fällt in der Geschäftsstelle auf,
           eine falsch zugeordnete nicht.
        """
        # sudo(): öffentliche Besucher/innen dürfen Anmeldungen nicht lesen. Der Zugriff
        # ist bewusst auf die eigene Anfrage eingegrenzt und liest NICHT mehr alle
        # Anmeldungen der Veranstaltung.
        Registration = request.env['event.registration'].sudo()
        domain = [
            ('event_id', '=', event.id),
            ('create_date', '>=', tx_start),
        ]
        candidates = Registration.search(domain + [('create_uid', '=', request.env.uid)])
        if not candidates:
            # Rückfallebene: legt eine künftige Odoo-Version die Anmeldungen unter einem
            # anderen Benutzer an (z. B. als Superuser), greift die create_uid-Bedingung
            # nicht mehr. Die Eindeutigkeitsprüfung unten bleibt davon unberührt.
            candidates = Registration.search(domain)
            if candidates:
                _logger.warning(
                    "KJR-Anmeldung: Eingrenzung über create_uid greift nicht "
                    "(Veranstaltung %s). Die Zuordnung erfolgt allein über die "
                    "Kernfelder des Formulars.", event.id)
        if not candidates:
            # Regulärer Fall, wenn der Standard-Controller gar keine Anmeldung erzeugt hat
            # (z. B. Fehlerseite "keine Plätze frei"). Kein Fehler.
            _logger.info(
                "KJR-Anmeldung: keine neu erzeugte Anmeldung zur Veranstaltung %s "
                "gefunden – es werden keine Zusatzangaben geschrieben.", event.id)
            return

        assigned = set()
        for counter, values in kjr_values:
            if not values:
                continue
            pool = candidates.filtered(lambda reg: reg.id not in assigned)
            found = self._kjr_find_registration(pool, match_values.get(counter) or {})
            if len(found) != 1:
                # Bewusst OHNE personenbezogene Daten im Protokoll (kein Name, keine
                # Gesundheitsangabe) – das Log ist selbst ein Speicherort.
                _logger.error(
                    "KJR-Anmeldung: Zusatzangaben der Formularzeile %s (Veranstaltung %s) "
                    "konnten keiner eindeutigen Anmeldung zugeordnet werden "
                    "(%s Treffer bei %s Anmeldungen dieser Anfrage). Es wurde NICHTS "
                    "geschrieben; Geburtsdatum, Ernährung/Allergie, Notfallkontakt und "
                    "Erziehungsberechtigte sind in der Geschäftsstelle nachzuerfassen.",
                    counter, event.id, len(found), len(candidates))
                continue
            assigned.add(found.id)
            found.write(values)

    @http.route()
    def registration_confirm(self, event, **post):
        # Roh-Post sichern, bevor die Standardverarbeitung läuft.
        kjr_values = self._kjr_extract_attendee_values(post)
        match_values = self._kjr_extract_attendee_match_values(post)

        # Zeitstempel DIESER Transaktion. ``cr.now()`` liefert den Transaktionsbeginn –
        # genau den Wert, den der ORM neu erzeugten Datensätzen als create_date mitgibt
        # (odoo/orm/models.py: ``vals.setdefault('create_date', self.env.cr.now())``).
        # fields.Datetime.now() wäre hier falsch: es liegt NACH dem Transaktionsbeginn und
        # würde die eigenen Anmeldungen aus dem Fenster schneiden.
        tx_start = request.env.cr.now() - timedelta(seconds=KJR_CREATE_WINDOW_SECONDS)

        response = super().registration_confirm(event, **post)

        if any(values for _counter, values in kjr_values):
            self._kjr_write_attendee_values(event, kjr_values, match_values, tx_start)
        return response

    # ------------------------------------------------------------------
    # E14 – Altersfilter auf der öffentlichen Veranstaltungsübersicht
    # ------------------------------------------------------------------

    def _kjr_parse_age_filter(self, value):
        """Wertet den GET-Parameter ``alter`` aus.

        Erlaubte Schreibweisen::

            ?alter=12      -> genau 12 Jahre        -> (12, 12)
            ?alter=6-9     -> Spanne 6 bis 9 Jahre  -> (6, 9)
            ?alter=18-     -> ab 18 Jahre           -> (18, None)

        ``?alter=18+`` wird ebenfalls akzeptiert; ein ``+`` wird im Query-String als
        Leerzeichen übertragen und kommt hier als ``'18 '`` an.

        Rückgabe: Tupel ``(von, bis)`` (``bis`` = ``None`` bei offenem Ende) oder
        ``None``, wenn nichts oder etwas Unbrauchbares übergeben wurde. Unbrauchbare
        Eingaben filtern bewusst NICHT (konservative Variante: lieber alles zeigen).
        """
        text = str(value or '')
        # '+' wird im Query-String als Leerzeichen dekodiert ('18+' -> '18 ').
        open_end_by_plus = text.endswith(' ') and text.strip().isdigit()
        text = text.strip().replace('–', '-')  # Gedankenstrich mit abfangen
        if text.endswith('+'):
            text = text[:-1] + '-'
        elif open_end_by_plus:
            text += '-'
        if not text:
            return None

        parts = text.split('-')
        if len(parts) == 1:
            if not parts[0].isdigit():
                return None
            age = min(int(parts[0]), KJR_AGE_MAX)
            return (age, age)
        if len(parts) != 2:
            return None

        age_from_raw, age_to_raw = parts
        if not age_from_raw.isdigit():
            return None
        age_from = min(int(age_from_raw), KJR_AGE_MAX)
        if age_to_raw == '':
            return (age_from, None)
        if not age_to_raw.isdigit():
            return None
        age_to = min(int(age_to_raw), KJR_AGE_MAX)
        if age_to < age_from:
            age_from, age_to = age_to, age_from
        return (age_from, age_to)

    def _kjr_age_key(self, age_range):
        """Kanonischer Schlüssel einer Altersspanne ('11-13', '18-', '12').

        Damit werden gleichbedeutende Schreibweisen ('18+', '18 ', '18-') auf denselben
        Wert normiert und der passende Schnellfilter-Button wird als aktiv erkannt.
        """
        age_from, age_to = age_range
        if age_to is None:
            return '%d-' % age_from
        if age_from == age_to:
            return '%d' % age_from
        return '%d-%d' % (age_from, age_to)

    def _kjr_age_label(self, key, age_range):
        """Beschriftung eines Altersfilters; nutzt die Gruppenbezeichnung, wenn sie passt."""
        for group_key, group_label in KJR_AGE_GROUPS:
            if group_key == key:
                return group_label
        age_from, age_to = age_range
        if age_to is None:
            return 'ab %d Jahre' % age_from
        if age_from == age_to:
            return '%d Jahre' % age_from
        return '%d–%d Jahre' % (age_from, age_to)

    def _kjr_age_matches(self, event_min, event_max, age_from, age_to):
        """True, wenn sich die Altersspanne der Veranstaltung mit [age_from, age_to] überschneidet.

        ``kjr_min_age``/``kjr_max_age`` = 0 bedeutet laut Modell "keine Prüfung" bzw.
        "keine Obergrenze". Eine Veranstaltung ganz ohne Altersangabe (0/0) passt damit
        immer und wird nie herausgefiltert.
        """
        if event_max and event_max < age_from:
            return False
        if age_to is not None and event_min and event_min > age_to:
            return False
        return True

    def _kjr_age_domain(self, age_from, age_to):
        """Domain-Variante von :meth:`_kjr_age_matches` (gleiche Semantik)."""
        domain = Domain('kjr_max_age', '=', 0) | Domain('kjr_max_age', '>=', age_from)
        if age_to is not None:
            domain &= (Domain('kjr_min_age', '=', 0) | Domain('kjr_min_age', '<=', age_to))
        return domain

    def _kjr_age_group_values(self, count_domain, active_key):
        """Baut die Schnellfilter-Buttons aus den tatsächlich vorhandenen Stammdaten.

        Eine Gruppe wird nur angeboten, wenn es mindestens eine Veranstaltung mit
        gepflegter Altersangabe gibt, die in die Gruppe fällt. Der Zähler am Button
        entspricht der Zahl der Treffer, die der Filter anzeigen würde – inklusive der
        Veranstaltungen ohne Altersangabe, die grundsätzlich immer sichtbar bleiben.

        ``count_domain`` ist die Domain der Übersicht OHNE den Altersfilter, damit die
        Zähler beim Umschalten stabil bleiben (analog zu den Datums-Zählern im Standard).
        """
        Event = request.env['event.event']
        # Eine gruppierte Abfrage statt einer Zählung je Gruppe.
        rows = Event._read_group(count_domain, ['kjr_min_age', 'kjr_max_age'], ['__count'])

        groups = []
        for key, label in KJR_AGE_GROUPS:
            age_range = self._kjr_parse_age_filter(key)
            if not age_range:
                continue
            age_from, age_to = age_range
            total = with_age_info = 0
            for event_min, event_max, count in rows:
                if not self._kjr_age_matches(event_min or 0, event_max or 0, age_from, age_to):
                    continue
                total += count
                if event_min or event_max:
                    with_age_info += count
            # Ohne eine einzige Veranstaltung mit gepflegter Altersangabe wäre der Button
            # sinnlos (er würde schlicht alles anzeigen) -> nicht darstellen.
            if with_age_info or key == active_key:
                groups.append({'key': key, 'label': label, 'count': total})
        return groups

    @http.route()
    def events(self, page=1, slug_tags=None, **searches):
        """Ergänzt die Übersicht um den Altersfilter ``?alter=…``.

        Der Standard-Controller wird zuerst regulär ausgeführt; er liefert alle
        Nebendaten (Datums-/Länder-/Tag-Filter, Kategorien, ``keep_event_url``). Ist der
        Altersfilter aktiv, werden Trefferliste, Trefferzahl und Pager anschließend mit
        der zusätzlichen Alters-Domain neu ermittelt – ein nachträgliches Aussortieren
        der bereits geschnittenen Seite würde die Paginierung zerstören.

        ``alter`` läuft im Standard automatisch in ``searches`` mit und wird deshalb von
        ``pager`` und ``keep_event_url`` bereits in alle Folge-Links übernommen; die
        anderen Filter bleiben dadurch unangetastet.
        """
        response = super().events(page=page, slug_tags=slug_tags, **searches)
        # Der Standard antwortet bei Tag-Kombinationen mit einem 301-Redirect.
        if not getattr(response, 'is_qweb', False):
            return response

        qcontext = response.qcontext
        website = request.website
        Event = request.env['event.event']

        # Bewusst ohne strip(): '18+' kommt als '18 ' an, das Leerzeichen ist die
        # Information "offenes Ende" (siehe _kjr_parse_age_filter).
        age_range = self._kjr_parse_age_filter(searches.get('alter'))
        age_key = self._kjr_age_key(age_range) if age_range else ''

        # ``alter`` wandert im Standard unbesehen in ``searches``, ``keep_event_url`` und
        # den Pager. Dort den kanonischen Wert hinterlegen bzw. eine unbrauchbare Eingabe
        # entfernen, damit alle Folge-Links (Pager, Datums-/Tag-Filter, Suchfeld) sauber
        # bleiben. Die anderen Filter werden dabei nicht angefasst.
        std_searches = qcontext.get('searches')
        keep_args = getattr(qcontext.get('keep_event_url'), 'args', None)
        for container in (std_searches, keep_args):
            if not isinstance(container, dict) or 'alter' not in container:
                continue
            if age_key:
                container['alter'] = age_key
            else:
                container.pop('alter')

        # ``searches`` aus dem qcontext enthält bereits alle Defaults und den ggf. per
        # Fuzzy-Suche korrigierten Suchbegriff – damit ist die Domain identisch zu der,
        # die der Standard-Controller verwendet hat.
        ctx_searches = dict(qcontext.get('searches') or {})
        search_term = ctx_searches.get('search') or ''
        options = self._get_events_search_options(slug_tags, **ctx_searches)
        order = 'date_begin desc' if ctx_searches.get('date') == 'old' else 'date_begin'
        order = 'is_published desc, ' + order + ', id desc'
        detail = Event._search_get_detail(website, order, options)

        # Zähler-Domain: alle übrigen Filter, aber ohne den Altersfilter.
        count_domain = Domain.AND(detail['base_domain'])
        if search_term:
            count_domain &= Domain('name', 'ilike', search_term)

        qcontext['kjr_age_filter'] = age_key
        qcontext['kjr_age_filter_label'] = self._kjr_age_label(age_key, age_range) if age_range else ''
        qcontext['kjr_age_groups'] = self._kjr_age_group_values(count_domain, age_key)

        if not age_range:
            return response

        # Trefferliste mit Altersfilter neu aufbauen (gleiche Mechanik wie im Standard).
        step = KJR_EVENTS_PER_PAGE
        detail['base_domain'] = list(detail['base_domain']) + [self._kjr_age_domain(*age_range)]
        results, event_count = Event._search_fetch(detail, search_term, page * step, order)

        qcontext['event_ids'] = results[(page - 1) * step:page * step]
        qcontext['search_count'] = event_count
        qcontext['pager'] = website.pager(
            url="/event/tags/%s" % slug_tags if slug_tags else "/event",
            url_args=ctx_searches,
            total=event_count,
            page=page,
            step=step,
            scope=5)
        return response
