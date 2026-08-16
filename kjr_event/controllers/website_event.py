# -*- coding: utf-8 -*-
"""Frontend-Erweiterung der Online-Anmeldung um KJR-Felder und den Altersfilter."""
from odoo import http
from odoo.fields import Domain
from odoo.http import request
from odoo.addons.website_event.controllers.main import WebsiteEventController


# Felder, die im Anmeldeformular je Teilnehmer/in erfasst werden können.
KJR_VALUE_FIELDS = (
    'birthdate', 'guardian_name', 'guardian_phone',
    'emergency_contact', 'dietary_requirements', 'dietary_note', 'notes',
)

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


class KjrWebsiteEventController(WebsiteEventController):

    # ------------------------------------------------------------------
    # Online-Anmeldung (E1)
    # ------------------------------------------------------------------

    def _kjr_extract_attendee_values(self, registrations):
        """Sammelt die KJR-Felder je Teilnehmer/in aus den geposteten Formulardaten.

        Das Frontend liefert die Felder unter ``<counter>-<feldname>`` (z. B. ``1-birthdate``).
        Rückgabe: Liste von Wert-Dicts in derselben Reihenfolge wie die Anmeldungen.
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

    @http.route()
    def registration_confirm(self, event, **post):
        # Roh-Post sichern, bevor die Standardverarbeitung läuft.
        kjr_values = self._kjr_extract_attendee_values(post)

        # Anmeldungen vor dem Aufruf zählen, um die neu erzeugten zu identifizieren.
        existing = request.env['event.registration'].sudo().search(
            [('event_id', '=', event.id)]).ids
        before = set(existing)

        response = super().registration_confirm(event, **post)

        if kjr_values:
            new_regs = request.env['event.registration'].sudo().search(
                [('event_id', '=', event.id), ('id', 'not in', list(before))],
                order='id asc')
            # Reihenfolge der neuen Anmeldungen entspricht der Reihenfolge im Formular.
            for reg, (_counter, values) in zip(new_regs, kjr_values):
                if values:
                    reg.write(values)
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
