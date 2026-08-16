# -*- coding: utf-8 -*-
"""E2 – Statistik-Export je Maßnahme (Kinder- und Jugendhilfestatistik).

Der KJR muss die gesetzliche Kinder- und Jugendhilfestatistik melden und hat sie
im Altsystem (Nupian) von Hand zusammengestellt. Dieser Assistent erzeugt die
Auswertung als CSV zum Download.

Bewusste Festlegungen:
* CSV statt XLSX – xlsxwriter ist keine garantierte Abhängigkeit der Instanz.
* Trennzeichen Semikolon und UTF-8 MIT BOM ("utf-8-sig"), damit Excel unter
  Windows die Umlaute korrekt anzeigt. Die Datei geht an eine Behörde.
* Es werden ausschließlich Felder ausgewertet, die es in diesem Projekt wirklich
  gibt. Ein Geschlecht wird an der Anmeldung (event.registration) derzeit NICHT
  erfasst – die Spalte entfällt deshalb, statt einen Platzhalter zu erfinden.
* Zahlen werden mit deutschem Dezimalkomma ausgegeben.
"""
import base64
import csv
import io
from datetime import date, datetime, time

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

# Altersgruppen der Auswertung: (Spaltenüberschrift, Untergrenze, Obergrenze)
# Obergrenze None = nach oben offen. Beide Grenzen sind einschließlich.
# TODO Kundenentscheidung: Die amtliche Statistik kennt je nach Meldebogen
# abweichende Altersklassen. Bis zur Klärung wird der konservative, in der
# Jugendarbeit gebräuchliche Schnitt verwendet.
AGE_BUCKETS = [
    ('Alter unter 6', None, 5),
    ('Alter 6–9', 6, 9),
    ('Alter 10–13', 10, 13),
    ('Alter 14–17', 14, 17),
    ('Alter 18–26', 18, 26),
    ('Alter 27 und älter', 27, None),
]


class KjrEventStatisticsWizard(models.TransientModel):
    _name = 'kjr.event.statistics.wizard'
    _description = 'KJR – Statistik-Export Maßnahmen'

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

    def _collect_data(self, events):
        """Sammelt alle Kennzahlen mit wenigen gebündelten Abfragen (kein N+1).

        :return: dict {event_id: dict mit Kennzahlen}
        """
        self.ensure_one()
        confirmed_states, cancelled_states, attended_states = self._registration_state_keys()

        data = {
            ev.id: {
                'total': 0,
                'confirmed': 0,
                'cancelled': 0,
                'attended': 0,
                'ages': [0] * len(AGE_BUCKETS),
                'no_birthdate': 0,
            }
            for ev in events
        }

        # 1) Anmeldungen je Veranstaltung und Status – aggregiert in der Datenbank.
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

        # 2) Altersverteilung – eine gebündelte Abfrage über alle Anmeldungen.
        #    Stornierte Anmeldungen zählen hier bewusst nicht mit.
        age_domain = [('event_id', 'in', events.ids)]
        if cancelled_states:
            age_domain.append(('state', 'not in', cancelled_states))
        for row in self.env['event.registration'].search_read(
                age_domain, ['event_id', 'kjr_age', 'has_birthdate']):
            entry = data.get(row['event_id'] and row['event_id'][0])
            if entry is None:
                continue
            if not row.get('has_birthdate'):
                entry['no_birthdate'] += 1
                continue
            age = row.get('kjr_age') or 0
            for idx, (_label, low, high) in enumerate(AGE_BUCKETS):
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

    def _event_seats(self, event):
        """Plätze: nur aussagekräftig, wenn die Veranstaltung begrenzt ist."""
        limited = event.seats_limited if 'seats_limited' in event._fields else bool(event.seats_max)
        if not limited or not event.seats_max:
            return 'unbegrenzt'
        return event.seats_max

    def _event_fee(self, event):
        """Teilnahmebeitrag laut hinterlegtem Schulungsprodukt.

        Ohne Produkt (z. B. kostenfreies Ferienprogramm) bleibt der Beitrag 0,00.
        """
        product = event.training_product_id
        return product.lst_price if product else 0.0

    # ------------------------------------------------------------------
    # CSV-Aufbau
    # ------------------------------------------------------------------
    def _detail_header(self):
        return ([
            'Veranstaltung', 'KJR-Art', 'Beginn', 'Ende', 'Dauer in Tagen', 'Ort',
            'Plätze', 'Anmeldungen gesamt', 'davon bestätigt', 'davon storniert',
            'davon teilgenommen',
        ] + [label for label, _low, _high in AGE_BUCKETS] + [
            'ohne Geburtsdatum', 'Mindestteilnehmerzahl', 'Mindestteilnehmerzahl erreicht',
            'Teilnahmebeitrag (€)', 'Zahlungspflichtig', 'Kooperationspartner',
        ])

    def _aggregate_header(self, group_label):
        return ([
            group_label, 'Anzahl Veranstaltungen', 'Erster Beginn', 'Letztes Ende',
            'Veranstaltungstage gesamt', 'Anmeldungen gesamt', 'davon bestätigt',
            'davon storniert', 'davon teilgenommen',
        ] + [label for label, _low, _high in AGE_BUCKETS] + [
            'ohne Geburtsdatum', 'Mindestteilnehmerzahl erreicht (Anzahl)',
        ])

    def _detail_row(self, event, entry, type_labels):
        return ([
            event.name or '',
            type_labels.get(event.kjr_event_type, ''),
            self._fmt_date(event.date_begin),
            self._fmt_date(event.date_end),
            self._event_duration_days(event),
            self._event_location(event),
            self._event_seats(event),
            entry['total'],
            entry['confirmed'],
            entry['cancelled'],
            entry['attended'],
        ] + entry['ages'] + [
            entry['no_birthdate'],
            event.kjr_seats_min or 0,
            'ja' if event.kjr_seats_min_reached else 'nein',
            self._fmt_amount(self._event_fee(event)),
            'ja' if event.payment_required else 'nein',
            event.cooperation_partner_id.display_name if event.cooperation_partner_id else '',
        ])

    def _empty_bucket(self):
        return {
            'events': 0,
            'date_begin': None,
            'date_end': None,
            'days': 0,
            'total': 0,
            'confirmed': 0,
            'cancelled': 0,
            'attended': 0,
            'ages': [0] * len(AGE_BUCKETS),
            'no_birthdate': 0,
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
        for key in ('total', 'confirmed', 'cancelled', 'attended', 'no_birthdate'):
            bucket[key] += entry[key]
        for idx, value in enumerate(entry['ages']):
            bucket['ages'][idx] += value
        if event.kjr_seats_min_reached:
            bucket['min_reached'] += 1

    def _aggregate_row(self, label, bucket):
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
            bucket['min_reached'],
        ])

    def _build_rows(self, events, data):
        """Baut Kopf- und Datenzeilen samt Summenzeile je nach Gliederung."""
        self.ensure_one()
        total_bucket = self._empty_bucket()
        type_labels = dict(self._selection_kjr_event_type())
        # Gebündelt vorladen, damit die Zeilenschleife unten keine Einzelabfragen
        # je Veranstaltung auslöst (Compute-Felder und verknüpfte Datensätze).
        events.mapped('kjr_seats_min_reached')
        events.mapped('training_product_id').mapped('lst_price')
        events.mapped('cooperation_partner_id').mapped('display_name')
        if 'address_id' in events._fields:
            events.mapped('address_id').mapped('display_name')

        if self.group_by == 'event':
            rows = [self._detail_header()]
            for event in events:
                entry = data[event.id]
                rows.append(self._detail_row(event, entry, type_labels))
                self._add_to_bucket(total_bucket, event, entry)
            summary = ([
                'SUMME', '', '', '', total_bucket['days'], '',
                '',
                total_bucket['total'],
                total_bucket['confirmed'],
                total_bucket['cancelled'],
                total_bucket['attended'],
            ] + total_bucket['ages'] + [
                total_bucket['no_birthdate'], '',
                '%s von %s' % (total_bucket['min_reached'], total_bucket['events']),
                '', '', '',
            ])
            rows.append(summary)
            return rows

        if self.group_by == 'type':
            buckets = {}
            order = []
            for event in events:
                key = event.kjr_event_type or False
                if key not in buckets:
                    buckets[key] = self._empty_bucket()
                    order.append(key)
                entry = data[event.id]
                self._add_to_bucket(buckets[key], event, entry)
                self._add_to_bucket(total_bucket, event, entry)
            rows = [self._aggregate_header('Veranstaltungstyp')]
            for key in order:
                label = type_labels.get(key) or 'Ohne KJR-Art'
                rows.append(self._aggregate_row(label, buckets[key]))
            rows.append(self._aggregate_row('SUMME', total_bucket))
            return rows

        # group_by == 'total' – eine einzige verdichtete Zeile plus Summenzeile.
        for event in events:
            self._add_to_bucket(total_bucket, event, data[event.id])
        label = '%s – %s' % (self._fmt_date(self.date_from), self._fmt_date(self.date_to))
        rows = [self._aggregate_header('Zeitraum')]
        rows.append(self._aggregate_row(label, total_bucket))
        rows.append(self._aggregate_row('SUMME', total_bucket))
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

        data = self._collect_data(events)
        rows = self._build_rows(events, data)

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
