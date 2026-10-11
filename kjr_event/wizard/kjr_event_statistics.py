# -*- coding: utf-8 -*-
"""E2: Statistik-Export je Maßnahme (Kinder- und Jugendhilfestatistik).

Der KJR muss die gesetzliche Kinder- und Jugendhilfestatistik melden und hat sie
im Altsystem von Hand zusammengestellt. Dieser Assistent erzeugt die
Auswertung als CSV zum Download.

Bewusste Festlegungen:
* CSV statt XLSX: xlsxwriter ist keine garantierte Abhängigkeit der Instanz.
* Trennzeichen Semikolon und UTF-8 MIT BOM ("utf-8-sig"), damit Excel unter
  Windows die Umlaute korrekt anzeigt. Die Datei geht an eine Behörde.
* Es werden ausschließlich Felder ausgewertet, die es in diesem Projekt wirklich
  gibt.
* Zahlen werden mit deutschem Dezimalkomma ausgegeben.

Zählmengen (stehen zusätzlich in der Infobox des Assistenten und, wo es darauf
ankommt, in der Spaltenbeschriftung selbst):
* Altersklassen und Geschlecht zählen ALLE nicht stornierten Anmeldungen,
  also auch Entwürfe.
* "davon bestätigt" sind die Status "registriert" und "teilgenommen",
  "davon teilgenommen" nur "teilgenommen", "davon storniert" nur "abgebrochen".
* Die Teilnahmebeiträge (Soll) beruhen auf den bestätigten Anmeldungen
  (registriert und teilgenommen). Entwürfe und Stornos zählen nicht mit. Es ist
  ein Sollwert: aktueller Listenpreis mal Kopfzahl, kein vereinnahmter Betrag
  (Begründung bei ``INCOME_HEADER``).

TODO(Kunde): Der zweite, von der Arbeitsliste erwähnte GaFöG-Export ist NICHT
umgesetzt. Es liegt keine Spezifikation vor (Spaltenfolge, Satzaufbau,
Dateiformat, Abgabeweg). Ein erfundener Export wäre für eine Behördenmeldung
schlechter als keiner. Benötigt wird die Meldevorlage bzw. der Erhebungsbogen
des Landesamts; danach ist der Export analog zu diesem Assistenten in wenigen
Stunden ergänzbar.
"""
import base64
import csv
import io
import json
import logging
from datetime import date, datetime, time

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# Systemparameter mit der JSON-Definition der Altersklassen (E2d). Default siehe
# data/ir_config_parameter_data.xml; dort ist auch das Format dokumentiert.
PARAM_AGE_BUCKETS = 'kjr_event.statistics_age_buckets'

# Standard-Altersklassen der Auswertung: (Spaltenüberschrift, Untergrenze,
# Obergrenze). Obergrenze None = nach oben offen, Untergrenze None = nach unten
# offen. Beide Grenzen sind einschließlich.
#
# Diese sechs Klassen sind der in der Jugendarbeit gebräuchliche Schnitt und
# bleiben der Auslieferungszustand. Die Meldevorlage des Landesamts kennt fünf
# Klassen; welche Einteilung gilt, ist eine offene Kundenfrage. Die Grenzen sind
# deshalb OHNE Codeänderung über PARAM_AGE_BUCKETS änderbar (siehe
# :meth:`_age_buckets`).
DEFAULT_AGE_BUCKETS = [
    ('Alter unter 6', None, 5),
    ('Alter 6 bis 9', 6, 9),
    ('Alter 10 bis 13', 10, 13),
    ('Alter 14 bis 17', 14, 17),
    ('Alter 18 bis 26', 18, 26),
    ('Alter 27 und älter', 27, None),
]

# Grenzen der Plausibilisierung der Konfiguration (rein technisch, kein
# fachlicher Wert): mehr Klassen wären keine Statistik mehr, und ein Alter
# jenseits von 120 ist ein Tippfehler.
MAX_AGE_BUCKETS = 12
MAX_AGE_VALUE = 120

# Beschriftung der Beitragsspalte. Rechenweg UND Zählmenge stehen bewusst IN der
# Beschriftung: eine Summe, deren Basis man nicht kennt, ist in einer
# Behördenmeldung nicht nachvollziehbar.
#
# BEWUSST "SOLL" UND NICHT "EINNAHMEN": gerechnet wird der AKTUELLE Listenpreis
# des Schulungsprodukts mal der Anzahl bestätigter und teilgenommener
# Anmeldungen. Das ist ein Sollwert, kein Zufluss. Tatsächliche Zahlungen,
# Teilzahlungen und Erstattungen (``event.registration.amount_paid`` /
# ``kjr_payment_state``) gehen NICHT ein; sie sind in diesem Modul von Hand
# gepflegte Felder und damit keine belastbare Grundlage für eine Behördenmeldung.
# Ein Wort "Einnahmen" würde dort einen Zufluss behaupten, den die Zahl nicht
# belegt - und nach einer Preisänderung am Produkt fällt derselbe Export für
# dasselbe Jahr anders aus. Beides steht jetzt in der Beschriftung.
#
# TODO(KJR): Ob das Landesamt Soll- oder Ist-Werte erwartet, ist eine offene
# Kundenfrage. Werden Ist-Werte verlangt, braucht es zuerst eine verlässliche
# Quelle für die vereinnahmten Beträge (Zahlungsabgleich), nicht nur eine andere
# Spaltenbeschriftung.
INCOME_HEADER = ('Teilnahmebeiträge Soll (€, aktueller Listenpreis x bestätigte '
                 'und teilgenommene Anmeldungen)')

# Zählmenge der Geschlechtsspalten, wörtlich in jeder Spaltenbeschriftung. Die
# Nachbarspalte "Anmeldungen gesamt" zählt ALLE Status einschließlich Storno, die
# Geschlechtsspalten zählen die nicht stornierten. Ohne diesen Zusatz summieren
# sich die Spalten in einer Behördenmeldung sichtbar auf eine andere Zahl als die
# Gesamtspalte, und die Empfängerin muss die Differenz erraten.
GENDER_BASIS = ' (Basis: nicht storniert)'


class KjrEventStatisticsWizard(models.TransientModel):
    _name = 'kjr.event.statistics.wizard'
    _description = 'KJR Statistik-Export Maßnahmen'

    def _default_date_from(self):
        return date(fields.Date.context_today(self).year, 1, 1)

    def _default_date_to(self):
        return date(fields.Date.context_today(self).year, 12, 31)

    def _selection_kjr_event_type(self):
        """Übernimmt die Auswahlwerte des bestehenden Feldes an event.event.

        Bewusst kein eigener Wertevorrat: die Liste darf nur an einer Stelle
        gepflegt werden (models/event_event.py).
        """
        field = self.env['event.event']._fields.get('kjr_event_type')
        if not field:
            return []
        selection = field.selection
        if isinstance(selection, str):
            selection = getattr(self.env['event.event'], selection)()
        elif callable(selection):
            selection = selection(self.env['event.event'])
        return [(key, label) for key, label in selection]

    def _gender_levels(self):
        """Stufen des Feldes ``event.registration.kjr_gender``.

        Zur Laufzeit gelesen, aus demselben Grund wie bei
        :meth:`_selection_kjr_event_type`: der Wertevorrat darf nur an einer
        Stelle gepflegt werden (models/event_registration.py). Fehlt das Feld,
        bleibt die Liste leer und die Geschlechtsspalten entfallen vollständig,
        statt den Export abzubrechen.
        """
        info = self.env['event.registration'].fields_get(
            ['kjr_gender'], ['selection']).get('kjr_gender') or {}
        return [(key, label) for key, label in (info.get('selection') or [])]

    # ------------------------------------------------------------------
    # E2d – Konfigurierbare Altersklassen
    # ------------------------------------------------------------------
    def _age_bucket_label(self, low, high):
        """Spaltenbeschriftung einer Altersklasse ohne gepflegtes "label"."""
        if low is None and high is None:
            return 'Alle Altersstufen'
        if low is None:
            return 'Alter unter %d' % (high + 1)
        if high is None:
            return 'Alter %d und älter' % low
        return 'Alter %d bis %d' % (low, high)

    def _age_buckets_fallback(self, reason):
        """Rückfall auf die Standardklassen MIT Protokollwarnung.

        Eine stille Teilauswertung wäre in einer Behördenmeldung der
        schlimmere Fehler als ein sichtbarer Rückfall auf den Standard.
        """
        _logger.warning(
            'Systemparameter %s ist unbrauchbar (%s). Es gelten die %d '
            'Standard-Altersklassen.',
            PARAM_AGE_BUCKETS, reason, len(DEFAULT_AGE_BUCKETS))
        return list(DEFAULT_AGE_BUCKETS)

    def _age_buckets(self):
        """Altersklassen des Exports: Systemparameter, sonst Standard.

        Die Vorlage des Landesamts kennt fünf Klassen, der Kunde hat sich noch
        nicht entschieden (offene Kundenfrage). Die Grenzen müssen deshalb ohne
        Codeänderung änderbar sein. Jede unbrauchbare Konfiguration fällt auf
        die Standardklassen zurück UND schreibt eine Warnung ins Protokoll.

        Geprüft wird: nicht leere Liste mit höchstens MAX_AGE_BUCKETS Einträgen,
        je Eintrag ein Objekt mit ganzzahligen Grenzen zwischen 0 und
        MAX_AGE_VALUE, "von" nur beim ersten und "bis" nur beim letzten Eintrag
        weglassbar, von <= bis sowie lückenloser und überschneidungsfreier
        Anschluss (nächstes "von" = vorheriges "bis" + 1).

        Zusätzlich muss die Einteilung den GESAMTEN Wertebereich abdecken: die
        erste Klasse beginnt bei 0 oder ist nach unten offen, die letzte ist nach
        oben offen. Andernfalls fiele eine Anmeldung ausserhalb der Klassen in
        keine einzige Spalte und fehlte in der Meldung lautlos, obwohl sie in
        "Anmeldungen gesamt" mitgezählt wird.

        :return: Liste von Tupeln ``(Beschriftung, Untergrenze, Obergrenze)``
            mit ``None`` für eine offene Grenze.
        """
        raw = self.env['ir.config_parameter'].sudo().get_param(PARAM_AGE_BUCKETS)
        if raw in (None, False, '') or not str(raw).strip():
            # Nicht gepflegt ist kein Fehler: der Standard gilt, ohne Warnung.
            return list(DEFAULT_AGE_BUCKETS)
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError) as error:
            return self._age_buckets_fallback('kein gültiges JSON: %s' % error)
        if not isinstance(parsed, list) or not parsed:
            return self._age_buckets_fallback('keine nicht leere Liste')
        if len(parsed) > MAX_AGE_BUCKETS:
            return self._age_buckets_fallback(
                '%d Klassen, erlaubt sind höchstens %d' % (len(parsed), MAX_AGE_BUCKETS))

        result = []
        last_index = len(parsed) - 1
        previous_high = None
        for index, item in enumerate(parsed):
            position = index + 1
            if not isinstance(item, dict):
                return self._age_buckets_fallback('Eintrag %d ist kein Objekt' % position)
            low = item.get('von')
            high = item.get('bis')
            for name, value in (('von', low), ('bis', high)):
                if value is None:
                    continue
                # bool ist in Python eine Unterklasse von int: true/false wäre
                # sonst stillschweigend 1/0.
                if isinstance(value, bool) or not isinstance(value, int):
                    return self._age_buckets_fallback(
                        '"%s" in Eintrag %d ist keine ganze Zahl' % (name, position))
                if not 0 <= value <= MAX_AGE_VALUE:
                    return self._age_buckets_fallback(
                        '"%s" in Eintrag %d liegt außerhalb von 0 bis %d'
                        % (name, position, MAX_AGE_VALUE))
            label = item.get('label')
            if label is not None and (not isinstance(label, str) or not label.strip()):
                return self._age_buckets_fallback(
                    '"label" in Eintrag %d ist kein nicht leerer Text' % position)
            if low is None and index != 0:
                return self._age_buckets_fallback(
                    '"von" fehlt in Eintrag %d; nach unten offen darf nur die erste '
                    'Klasse sein' % position)
            if high is None and index != last_index:
                return self._age_buckets_fallback(
                    '"bis" fehlt in Eintrag %d; nach oben offen darf nur die letzte '
                    'Klasse sein' % position)
            if low is not None and high is not None and low > high:
                return self._age_buckets_fallback(
                    '"von" ist größer als "bis" in Eintrag %d' % position)
            if index == 0 and low not in (None, 0):
                return self._age_buckets_fallback(
                    'die erste Klasse beginnt bei %r; sie muss bei 0 beginnen oder '
                    'nach unten offen sein ("von" weglassen), sonst würden jüngere '
                    'Teilnehmende in keiner Spalte gezählt' % low)
            if index == last_index and high is not None:
                return self._age_buckets_fallback(
                    'die letzte Klasse endet bei %d; sie muss nach oben offen sein '
                    '("bis" weglassen), sonst würden ältere Teilnehmende in keiner '
                    'Spalte gezählt' % high)
            if index > 0 and low != previous_high + 1:
                return self._age_buckets_fallback(
                    'Eintrag %d schließt nicht lückenlos und überschneidungsfrei an '
                    '(erwartet "von" = %d, gelesen %r)'
                    % (position, previous_high + 1, low))
            previous_high = high
            result.append((
                label.strip() if label else self._age_bucket_label(low, high),
                low, high))
        return result

    date_from = fields.Date(
        string='Zeitraum von', required=True, default=_default_date_from,
        help='Ausgewertet werden alle KJR-Veranstaltungen, deren Beginn in diesen '
             'Zeitraum fällt.',
    )
    date_to = fields.Date(
        string='Zeitraum bis', required=True, default=_default_date_to,
        help='Ausgewertet werden alle KJR-Veranstaltungen, deren Beginn in diesen '
             'Zeitraum fällt.',
    )
    event_ids = fields.Many2many(
        'event.event',
        'kjr_event_statistics_event_rel', 'wizard_id', 'event_id',
        string='Veranstaltungen',
        domain="[('is_kjr', '=', True)]",
        help='Leer lassen = alle KJR-Veranstaltungen im gewählten Zeitraum. '
             'Eine Auswahl schränkt zusätzlich zum Zeitraum ein.',
    )
    kjr_event_type = fields.Selection(
        selection='_selection_kjr_event_type',
        string='KJR-Art',
        help='Optional: nur Veranstaltungen dieser Art auswerten.',
    )
    group_by = fields.Selection([
        ('event', 'Je Veranstaltung'),
        ('type', 'Je Veranstaltungstyp'),
        ('total', 'Gesamtjahr'),
    ], string='Gliederung', required=True, default='event',
        help='"Je Veranstaltung" liefert die Detailzeilen (Meldebogen je Maßnahme), '
             'die beiden anderen Varianten die verdichteten Summen.')

    export_file = fields.Binary(string='Auswertung (CSV)', readonly=True, attachment=False)
    export_filename = fields.Char(string='Dateiname', readonly=True)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for wiz in self:
            if wiz.date_from and wiz.date_to and wiz.date_from > wiz.date_to:
                raise ValidationError(_('"Zeitraum von" muss vor "Zeitraum bis" liegen.'))

    # ------------------------------------------------------------------
    # Datenbeschaffung
    # ------------------------------------------------------------------
    def _period_bounds_utc(self):
        """Tagesgrenzen des Zeitraums in UTC.

        date_begin ist ein Datetime-Feld und wird in UTC gespeichert. Ohne
        Umrechnung würde eine Veranstaltung, die am 1. Januar um 00:30 Ortszeit
        beginnt, in UTC noch auf den 31. Dezember fallen und aus der
        Jahresauswertung herausfallen.
        """
        self.ensure_one()
        tz = pytz.timezone(self.env.user.tz or 'Europe/Berlin')
        start = tz.localize(datetime.combine(self.date_from, time.min))
        end = tz.localize(datetime.combine(self.date_to, time.max))
        return (start.astimezone(pytz.utc).replace(tzinfo=None),
                end.astimezone(pytz.utc).replace(tzinfo=None))

    def _get_events(self):
        """Liefert die auszuwertenden Veranstaltungen (nach Beginn sortiert)."""
        self.ensure_one()
        start, end = self._period_bounds_utc()
        domain = [
            ('is_kjr', '=', True),
            ('date_begin', '>=', start),
            ('date_begin', '<=', end),  # Endtag einschließlich
        ]
        if self.kjr_event_type:
            domain.append(('kjr_event_type', '=', self.kjr_event_type))
        if self.event_ids:
            domain.append(('id', 'in', self.event_ids.ids))
        return self.env['event.event'].search(domain, order='date_begin, id')

    def _registration_state_keys(self):
        """Ermittelt die tatsächlich vorhandenen Status-Schlüssel der Anmeldung.

        Bewusst dynamisch gelesen, damit der Export auch dann läuft, wenn ein
        weiteres Modul den Wertevorrat von event.registration.state erweitert.
        """
        selection = self.env['event.registration'].fields_get(
            ['state'], ['selection'])['state']['selection']
        keys = [key for key, _label in selection]
        confirmed = [k for k in ('open', 'done') if k in keys]
        cancelled = [k for k in ('cancel',) if k in keys]
        attended = [k for k in ('done',) if k in keys]
        return confirmed, cancelled, attended

    def _collect_data(self, events, buckets, genders):
        """Sammelt alle Kennzahlen mit wenigen gebündelten Abfragen (kein N+1).

        Die Altersverteilung UND die Geschlechtsverteilung zählen dieselbe
        Menge: alle nicht stornierten Anmeldungen, also auch Entwürfe. Beide
        werden in EINER Abfrage gelesen. Die Teilnahmebeiträge beruhen dagegen
        auf den bestätigten Anmeldungen; das steht in der Spaltenbeschriftung.

        :return: dict {event_id: dict mit Kennzahlen}
        """
        self.ensure_one()
        confirmed_states, cancelled_states, attended_states = self._registration_state_keys()
        gender_keys = [key for key, _label in genders]

        data = {
            ev.id: {
                'total': 0,
                'confirmed': 0,
                'cancelled': 0,
                'attended': 0,
                'ages': [0] * len(buckets),
                'no_birthdate': 0,
                'genders': {key: 0 for key in gender_keys},
                'gender_none': 0,
            }
            for ev in events
        }

        # 1) Anmeldungen je Veranstaltung und Status: aggregiert in der Datenbank.
        groups = self.env['event.registration']._read_group(
            [('event_id', 'in', events.ids)],
            groupby=['event_id', 'state'],
            aggregates=['__count'],
        )
        for event, state, count in groups:
            entry = data.get(event.id)
            if entry is None:
                continue
            entry['total'] += count
            if state in confirmed_states:
                entry['confirmed'] += count
            if state in cancelled_states:
                entry['cancelled'] += count
            if state in attended_states:
                entry['attended'] += count

        # 2) Alters- und Geschlechtsverteilung: eine gebündelte Abfrage über alle
        #    Anmeldungen. Stornierte Anmeldungen zählen hier bewusst nicht mit.
        fields_to_read = ['event_id', 'kjr_age', 'has_birthdate']
        if gender_keys:
            fields_to_read.append('kjr_gender')
        age_domain = [('event_id', 'in', events.ids)]
        if cancelled_states:
            age_domain.append(('state', 'not in', cancelled_states))
        for row in self.env['event.registration'].search_read(age_domain, fields_to_read):
            entry = data.get(row['event_id'] and row['event_id'][0])
            if entry is None:
                continue
            if gender_keys:
                value = row.get('kjr_gender')
                # Leer = nicht erfasst; ein unbekannter Schlüssel (anderes Modul)
                # landet bewusst ebenfalls in "nicht erfasst", damit die Summe der
                # Spalten weiterhin der Anzahl der NICHT STORNIERTEN Anmeldungen
                # entspricht. Nicht der Spalte "Anmeldungen gesamt": die zählt
                # alle Status einschließlich Storno. Deshalb trägt jede
                # Geschlechtsspalte ihre Zählmenge in der Beschriftung
                # (``GENDER_BASIS``).
                if value in entry['genders']:
                    entry['genders'][value] += 1
                else:
                    entry['gender_none'] += 1
            if not row.get('has_birthdate'):
                entry['no_birthdate'] += 1
                continue
            age = row.get('kjr_age') or 0
            for idx, (_label, low, high) in enumerate(buckets):
                if (low is None or age >= low) and (high is None or age <= high):
                    entry['ages'][idx] += 1
                    break
        return data

    # ------------------------------------------------------------------
    # Formatierung
    # ------------------------------------------------------------------
    def _fmt_date(self, value):
        """Datum/Zeit-Feld als deutsches Datum in der Zeitzone des Benutzers."""
        if not value:
            return ''
        if isinstance(value, date) and not hasattr(value, 'hour'):
            return value.strftime('%d.%m.%Y')
        return fields.Datetime.context_timestamp(self, value).strftime('%d.%m.%Y')

    @api.model
    def _fmt_amount(self, value):
        """Betrag mit deutschem Dezimalkomma."""
        return ('%.2f' % (value or 0.0)).replace('.', ',')

    def _event_duration_days(self, event):
        if not event.date_begin or not event.date_end:
            return ''
        begin = fields.Datetime.context_timestamp(self, event.date_begin).date()
        end = fields.Datetime.context_timestamp(self, event.date_end).date()
        return max((end - begin).days + 1, 1)

    def _event_location(self, event):
        if 'address_id' in event._fields and event.address_id:
            return event.address_id.display_name or ''
        return ''

    def _event_zip(self, event):
        """PLZ des Veranstaltungsorts (eigene Spalte für das Landesamt).

        Quelle ist der Veranstaltungsort-Kontakt (``address_id``, ein
        res.partner). Ohne gepflegte PLZ bleibt die Spalte LEER: ein Platzhalter
        wie "unbekannt" wäre in einer Behördenmeldung ein erfundener Wert.
        """
        if 'address_id' in event._fields and event.address_id:
            return event.address_id.zip or ''
        return ''

    def _event_seats(self, event):
        """Plätze: nur aussagekräftig, wenn die Veranstaltung begrenzt ist."""
        limited = event.seats_limited if 'seats_limited' in event._fields else bool(event.seats_max)
        if not limited or not event.seats_max:
            return 'unbegrenzt'
        return event.seats_max

    def _event_fee(self, event):
        """Teilnahmebeitrag laut hinterlegtem Schulungsprodukt.

        Ohne Produkt (z. B. kostenfreies Ferienprogramm) bleibt der Beitrag 0,00.

        UND ohne Zahlungspflicht ebenfalls 0,00, aus demselben Grund wie bei
        :meth:`_event_income`: ist an der Veranstaltung ``payment_required``
        nicht gesetzt, wird für diese Maßnahme nichts fakturiert - ein
        hinterlegtes Produkt ist dann nur eine Vorbereitung. Ohne diese Prüfung
        widersprach sich die Meldung in derselben Zeile: Spalte
        "Teilnahmebeitrag" wies 50,00 aus, die Beitragssumme daneben 0,00.
        """
        if not event.payment_required:
            return 0.0
        product = event.training_product_id
        return product.lst_price if product else 0.0

    def _event_income(self, event, entry):
        """Teilnahmebeiträge SOLL = Beitrag mal Anzahl der BESTÄTIGTEN Anmeldungen.

        Bestätigt sind die Status "registriert" und "teilgenommen"; Entwürfe und
        Stornos zählen nicht. Ohne Zahlungspflicht ist der Wert 0,00, auch wenn
        ein Schulungsprodukt hinterlegt ist: dann wird für diese Maßnahme nichts
        fakturiert.

        Es ist ein SOLLWERT, kein Zufluss: Rechenweg und Zählmenge stehen
        deshalb wörtlich in der Spaltenbeschriftung (``INCOME_HEADER``, dort auch
        die Begründung und die offene Kundenfrage).
        """
        if not event.payment_required:
            return 0.0
        return self._event_fee(event) * entry['confirmed']

    # ------------------------------------------------------------------
    # CSV-Aufbau
    #
    # Detail- und Aggregatkopf MÜSSEN dieselbe Spaltenzahl haben wie die
    # zugehörige Datenzeile und die Summenzeile. Verrutscht eine Spalte, fällt
    # das in einer CSV nicht auf, die Behörde liest dann falsche Werte. Dafür
    # gibt es eigene Tests (tests/test_event_statistics.py).
    # ------------------------------------------------------------------
    def _gender_headers(self, genders):
        """Spaltengruppe Geschlecht: je Stufe eine Spalte plus "nicht erfasst".

        Die Stufe "keine Angabe" des Formulars heißt: bewusst nicht angegeben.
        Die zusätzliche Spalte "Geschlecht nicht erfasst" steht für das LEERE
        Feld (gar nicht erhoben, z. B. bei abgetippten Papieranmeldungen).
        Beides getrennt auszuweisen ist der Grund, warum das Feld die Stufe
        "keine Angabe" überhaupt hat. Die Spalte hieß bis 19.0.5.7.0
        "Geschlecht ohne Angabe" und stand damit direkt neben "Geschlecht keine
        Angabe": zwei Spalten, deren unterschiedliche Bedeutung an einem
        einzigen Wort hing und beim Übertragen in den Erhebungsbogen nicht
        auseinanderzuhalten war.

        Ohne Stufenliste (das Feld fehlt oder ist für den ausführenden Benutzer
        nicht lesbar) entfällt die GANZE Spaltengruppe, auch die Spalte für das
        leere Feld. Eine 0 in "nicht erfasst" wäre dort die Aussage "bei
        niemandem fehlt die Angabe", obwohl das Merkmal überhaupt nicht erhoben
        wird - in einer Behördenmeldung ein erfundener Wert.
        """
        if not genders:
            return []
        return ([('Geschlecht %s' % label) + GENDER_BASIS for _key, label in genders]
                + ['Geschlecht nicht erfasst' + GENDER_BASIS])

    def _gender_values(self, source, genders):
        """Zahlen der Geschlechtsspalten, strikt in der Reihenfolge der Stufenliste.

        Bewusst über ``genders`` und nicht über die Schlüsselreihenfolge des
        dicts: Kopf und Zeile dürfen auch dann nicht auseinanderlaufen, wenn das
        dict irgendwann anders aufgebaut wird. Eine Stufe, die im dict fehlt,
        zählt als 0 und nicht als fehlende Spalte.

        Ohne Stufenliste keine Werte - genau wie :meth:`_gender_headers` keine
        Spalten liefert. Kopf und Zeile bleiben damit auch in diesem Fall
        gleich lang.
        """
        if not genders:
            return []
        return ([source['genders'].get(key, 0) for key, _label in genders]
                + [source['gender_none']])

    def _detail_header(self, buckets, genders):
        return ([
            'Veranstaltung', 'KJR-Art', 'Beginn', 'Ende', 'Dauer in Tagen', 'Ort',
            'PLZ', 'Plätze', 'Anmeldungen gesamt', 'davon bestätigt',
            'davon storniert', 'davon teilgenommen',
        ] + [label for label, _low, _high in buckets] + [
            'ohne Geburtsdatum',
        ] + self._gender_headers(genders) + [
            'Mindestteilnehmerzahl', 'Mindestteilnehmerzahl erreicht',
            'Teilnahmebeitrag (€)', INCOME_HEADER,
            'Zahlungspflichtig', 'Kooperationspartner',
        ])

    def _aggregate_header(self, group_label, buckets, genders):
        # Bewusst OHNE Ort und PLZ: eine Gruppe fasst mehrere Veranstaltungen
        # und damit mehrere Orte zusammen, ein einzelner Ort wäre dort falsch.
        return ([
            group_label, 'Anzahl Veranstaltungen', 'Erster Beginn', 'Letztes Ende',
            'Veranstaltungstage gesamt', 'Anmeldungen gesamt', 'davon bestätigt',
            'davon storniert', 'davon teilgenommen',
        ] + [label for label, _low, _high in buckets] + [
            'ohne Geburtsdatum',
        ] + self._gender_headers(genders) + [
            INCOME_HEADER, 'Mindestteilnehmerzahl erreicht (Anzahl)',
        ])

    def _detail_row(self, event, entry, type_labels, genders):
        return ([
            event.name or '',
            type_labels.get(event.kjr_event_type, ''),
            self._fmt_date(event.date_begin),
            self._fmt_date(event.date_end),
            self._event_duration_days(event),
            self._event_location(event),
            self._event_zip(event),
            self._event_seats(event),
            entry['total'],
            entry['confirmed'],
            entry['cancelled'],
            entry['attended'],
        ] + entry['ages'] + [
            entry['no_birthdate'],
        ] + self._gender_values(entry, genders) + [
            event.kjr_seats_min or 0,
            'ja' if event.kjr_seats_min_reached else 'nein',
            self._fmt_amount(self._event_fee(event)),
            self._fmt_amount(self._event_income(event, entry)),
            'ja' if event.payment_required else 'nein',
            event.cooperation_partner_id.display_name if event.cooperation_partner_id else '',
        ])

    def _empty_bucket(self, buckets, genders):
        return {
            'events': 0,
            'date_begin': None,
            'date_end': None,
            'days': 0,
            'total': 0,
            'confirmed': 0,
            'cancelled': 0,
            'attended': 0,
            'ages': [0] * len(buckets),
            'no_birthdate': 0,
            'genders': {key: 0 for key, _label in genders},
            'gender_none': 0,
            'income': 0.0,
            'min_reached': 0,
        }

    def _add_to_bucket(self, bucket, event, entry):
        bucket['events'] += 1
        if event.date_begin and (not bucket['date_begin'] or event.date_begin < bucket['date_begin']):
            bucket['date_begin'] = event.date_begin
        if event.date_end and (not bucket['date_end'] or event.date_end > bucket['date_end']):
            bucket['date_end'] = event.date_end
        days = self._event_duration_days(event)
        bucket['days'] += days if isinstance(days, int) else 0
        for key in ('total', 'confirmed', 'cancelled', 'attended', 'no_birthdate',
                    'gender_none'):
            bucket[key] += entry[key]
        for idx, value in enumerate(entry['ages']):
            bucket['ages'][idx] += value
        for key in bucket['genders']:
            bucket['genders'][key] += entry['genders'].get(key, 0)
        bucket['income'] += self._event_income(event, entry)
        if event.kjr_seats_min_reached:
            bucket['min_reached'] += 1

    def _aggregate_row(self, label, bucket, genders):
        return ([
            label,
            bucket['events'],
            self._fmt_date(bucket['date_begin']),
            self._fmt_date(bucket['date_end']),
            bucket['days'],
            bucket['total'],
            bucket['confirmed'],
            bucket['cancelled'],
            bucket['attended'],
        ] + bucket['ages'] + [
            bucket['no_birthdate'],
        ] + self._gender_values(bucket, genders) + [
            self._fmt_amount(bucket['income']),
            bucket['min_reached'],
        ])

    def _detail_summary_row(self, total_bucket, genders):
        """Summenzeile unter den Detailzeilen.

        Die Leerfelder sind positionsgleich zum Detailkopf: KJR-Art, Beginn,
        Ende, Ort, PLZ und Plätze lassen sich über mehrere Veranstaltungen nicht
        summieren, ebenso der Teilnahmebeitrag (Einzelbetrag je Maßnahme). Die
        TEILNAHMEBEITRÄGE dagegen werden summiert.
        """
        return ([
            'SUMME',                      # Veranstaltung
            '',                           # KJR-Art
            '',                           # Beginn
            '',                           # Ende
            total_bucket['days'],         # Dauer in Tagen
            '',                           # Ort
            '',                           # PLZ
            '',                           # Plätze
            total_bucket['total'],
            total_bucket['confirmed'],
            total_bucket['cancelled'],
            total_bucket['attended'],
        ] + total_bucket['ages'] + [
            total_bucket['no_birthdate'],
        ] + self._gender_values(total_bucket, genders) + [
            '',                           # Mindestteilnehmerzahl
            '%s von %s' % (total_bucket['min_reached'], total_bucket['events']),
            '',                           # Teilnahmebeitrag (Einzelbetrag)
            self._fmt_amount(total_bucket['income']),
            '',                           # Zahlungspflichtig
            '',                           # Kooperationspartner
        ])

    def _build_rows(self, events, data, buckets, genders):
        """Baut Kopf- und Datenzeilen samt Summenzeile je nach Gliederung."""
        self.ensure_one()
        total_bucket = self._empty_bucket(buckets, genders)
        type_labels = dict(self._selection_kjr_event_type())
        # Gebündelt vorladen, damit die Zeilenschleife unten keine Einzelabfragen
        # je Veranstaltung auslöst (Compute-Felder und verknüpfte Datensätze).
        events.mapped('kjr_seats_min_reached')
        events.mapped('training_product_id').mapped('lst_price')
        events.mapped('cooperation_partner_id').mapped('display_name')
        if 'address_id' in events._fields:
            addresses = events.mapped('address_id')
            addresses.mapped('display_name')
            addresses.mapped('zip')

        if self.group_by == 'event':
            rows = [self._detail_header(buckets, genders)]
            for event in events:
                entry = data[event.id]
                rows.append(self._detail_row(event, entry, type_labels, genders))
                self._add_to_bucket(total_bucket, event, entry)
            rows.append(self._detail_summary_row(total_bucket, genders))
            return rows

        if self.group_by == 'type':
            type_buckets = {}
            order = []
            for event in events:
                key = event.kjr_event_type or False
                if key not in type_buckets:
                    type_buckets[key] = self._empty_bucket(buckets, genders)
                    order.append(key)
                entry = data[event.id]
                self._add_to_bucket(type_buckets[key], event, entry)
                self._add_to_bucket(total_bucket, event, entry)
            rows = [self._aggregate_header('Veranstaltungstyp', buckets, genders)]
            for key in order:
                label = type_labels.get(key) or 'Ohne KJR-Art'
                rows.append(self._aggregate_row(label, type_buckets[key], genders))
            rows.append(self._aggregate_row('SUMME', total_bucket, genders))
            return rows

        # group_by == 'total': eine einzige verdichtete Zeile plus Summenzeile.
        for event in events:
            self._add_to_bucket(total_bucket, event, data[event.id])
        label = '%s bis %s' % (self._fmt_date(self.date_from), self._fmt_date(self.date_to))
        rows = [self._aggregate_header('Zeitraum', buckets, genders)]
        rows.append(self._aggregate_row(label, total_bucket, genders))
        rows.append(self._aggregate_row('SUMME', total_bucket, genders))
        return rows

    # ------------------------------------------------------------------
    # Aktion
    # ------------------------------------------------------------------
    def action_generate(self):
        """Erzeugt die CSV, speichert sie am Assistenten und öffnet ihn erneut."""
        self.ensure_one()
        events = self._get_events()
        if not events:
            raise UserError(_(
                'Für den Zeitraum %(start)s bis %(end)s wurden keine KJR-Veranstaltungen '
                'gefunden. Bitte den Zeitraum, die KJR-Art oder die Auswahl der '
                'Veranstaltungen prüfen. Hinweis: Ausgewertet werden nur '
                'Veranstaltungen, die als KJR-Veranstaltung markiert sind.',
                start=self._fmt_date(self.date_from), end=self._fmt_date(self.date_to)))

        # Altersklassen und Geschlechtsstufen EINMAL je Export ermitteln: so wird
        # eine etwaige Warnung zur Konfiguration auch nur einmal protokolliert,
        # und Kopf, Zeilen und Summen können nicht auseinanderlaufen.
        buckets = self._age_buckets()
        genders = self._gender_levels()

        data = self._collect_data(events, buckets, genders)
        rows = self._build_rows(events, data, buckets, genders)

        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=';', quotechar='"',
                            quoting=csv.QUOTE_MINIMAL, lineterminator='\r\n')
        writer.writerows(rows)
        # UTF-8 MIT BOM: nur so erkennt Excel unter Windows die Kodierung und
        # stellt die Umlaute korrekt dar.
        content = buffer.getvalue().encode('utf-8-sig')
        buffer.close()

        self.write({
            'export_file': base64.b64encode(content),
            'export_filename': 'KJR_Jugendhilfestatistik_%s_%s.csv' % (
                self.date_from.strftime('%Y-%m-%d'), self.date_to.strftime('%Y-%m-%d')),
        })
        # Standard-Odoo-Muster: denselben Assistenten neu öffnen, der Download
        # hängt dann als Datei-Feld im Formular.
        return {
            'type': 'ir.actions.act_window',
            'name': _('Statistik-Export'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': dict(self.env.context),
        }
