# -*- coding: utf-8 -*-
"""Stammdaten der Einrichtungen (Häuser/Zeltplätze), Räume und Ausstattung."""
import logging
import re
from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# Eine Zimmernummer steht am ANFANG des Namens ("Zimmer 12"). Zahlen in einem
# Klammerzusatz ("(12 Betten)", "(1. OG)") sind Bettenzahlen oder Stockwerke und
# dürfen nie als Zimmernummer gelesen werden.
ROOM_NUMBER_RE = re.compile(r'^\D*(\d+)')


class KjrFacility(models.Model):
    _name = 'kjr.facility'
    _description = 'KJR Einrichtung'
    _order = 'sequence, name'
    _inherit = ['mail.thread']

    name = fields.Char(string='Bezeichnung', required=True, tracking=True)
    code = fields.Char(string='Kürzel')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    facility_type = fields.Selection([
        ('house', 'Jugend-/Tagungshaus'),
        ('campsite', 'Zeltplatz'),
        ('other', 'Sonstige'),
    ], string='Art', default='house', required=True)
    color = fields.Integer(string='Kalenderfarbe')
    description_short = fields.Char(string='Kurzbeschreibung')
    description = fields.Html(string='Beschreibung')
    image_1920 = fields.Image(string='Bild', max_width=1920, max_height=1920)
    capacity = fields.Integer(string='Max. Personen', default=0)
    supervision_ratio = fields.Integer(
        string='Betreuungsschlüssel (TN je Betreuer)', default=6,
        help='Empfohlene Betreuung: 1 Betreuer je N Teilnehmer.',
    )
    street = fields.Char(string='Straße')
    zip = fields.Char(string='PLZ')
    city = fields.Char(string='Ort')
    responsible_user_id = fields.Many2one('res.users', string='Verantwortlich', tracking=True)
    # F7: Standard-Uhrzeiten als Stammdaten (Default für neue Buchungen).
    check_in_default_time = fields.Float(
        string='Standard-Anreisezeit', help='Default-Anreisezeit (HH:MM) für neue Buchungen.')
    check_out_default_time = fields.Float(
        string='Standard-Abreisezeit', help='Default-Abreisezeit (HH:MM) für neue Buchungen.')
    # F8: Frei konfigurierbarer Hinweis-Text für die Mail-Templates.
    mail_hint = fields.Html(
        string='Mail-Hinweis',
        help='Optionaler Hinweistext, der in den E-Mails an die Gruppe ausgegeben wird '
             '(z. B. Anfahrt, Schlüsselübergabe, Hausordnung).')
    # B-cross: optionaler Auto-Post-Schalter für erzeugte Rechnungen.
    invoice_auto_post = fields.Boolean(
        string='Rechnung automatisch buchen',
        help='Wenn aktiv, wird die aus einer Buchung erzeugte Rechnung direkt gebucht (validiert).')
    # F1: Buchungsregeln je Einrichtung. Die eigentliche Prüfung passiert in der
    # Buchung bzw. im Website-Formular — hier stehen nur die Stammdaten.
    # TODO(Kunde): Die konkreten Werte je Einrichtung (Mindestbelegung,
    # Mindestaufenthalt, Beschränkung auf organisierte Gruppen) sind vom Betreiber
    # schriftlich zu bestätigen und danach in data/kjr_facility_data.xml zu
    # hinterlegen. Bis dahin bleiben die Defaults bewusst auf 0 = keine Prüfung.
    max_advance_months = fields.Integer(
        string='Max. Buchungsvorlauf (Monate)', default=18,
        help='Buchungen werden höchstens so viele Monate im Voraus angenommen. Der '
             'Wert begrenzt, wie weit das Anreisedatum in der Zukunft liegen darf. '
             '0 = unbegrenzt (keine Prüfung).')
    min_persons = fields.Integer(
        string='Mindestbelegung (Personen)', default=0,
        help='Kleinste Gruppengröße, die die Einrichtung aufnimmt (z. B. ab 20 '
             'Personen). Gezählt werden Teilnehmer und Betreuer zusammen. '
             '0 = keine Prüfung.')
    min_nights = fields.Integer(
        string='Mindestaufenthalt (Nächte)', default=0,
        help='Kleinste Aufenthaltsdauer in Nächten (z. B. mindestens 2 Nächte). '
             '0 = keine Prüfung.')
    requires_organized_group = fields.Boolean(
        string='Nur organisierte Jugend-/Bildungsgruppen', default=False,
        help='Wenn aktiv, wird die Einrichtung ausschließlich an organisierte Jugend-, '
             'Schul- und Bildungsgruppen vergeben (kein privater Familien- oder '
             'Vereinsausflug). Die Buchung erfasst dazu das Kennzeichen '
             '"Organisierte Jugend-/Bildungsgruppe".')
    # F-Verpflegung: Nicht jede Einrichtung verpflegt ihre Gruppen. Beide
    # Einrichtungen des Erstbetreibers sind reine Selbstversorgerhäuser
    # (Betreiberaussage vom 21.08.2026), das Buchungsformular bot bis dahin
    # trotzdem Frühstück/Halb-/Vollpension an — also Leistungen, die der
    # Betreiber gar nicht erbringt. Der Schalter bleibt im Modul, weil es
    # White-Label an weitere Träger geht, von denen manche sehr wohl verpflegen;
    # ersatzlos entfernt wird die Funktion deshalb nicht.
    offers_catering = fields.Boolean(
        string='Verpflegung anbieten', default=False,
        help='Aus (Standard): Die Einrichtung verpflegt nicht, die Gruppe versorgt '
             'sich selbst. Die Verpflegung wird dann überall ausgeblendet: im '
             'Buchungsformular der Website, in der Buchungsmaske im Backend und im '
             'Vertrag; auch die Verpflegungspreise am Tarif werden nicht angezeigt.\n'
             'An: Verpflegungsauswahl (Frühstück, Halb-, Vollpension) und die '
             'zugehörigen Preisfelder werden eingeblendet und können gebucht und '
             'berechnet werden.\n'
             'Der Schalter existiert, weil dieses Modul auch an Träger MIT '
             'eigener Verpflegung geht. Die Vorgabe ist "aus", weil ein '
             'Selbstversorgerhaus der häufigere Fall ist.\n'
             'Hinweis: Der Schalter wirkt NICHT rückwirkend. Bereits erfasste '
             'Buchungen behalten ihre berechneten Verpflegungsbeträge, damit sich '
             'fakturierte Vorgänge nicht nachträglich ändern.')
    room_ids = fields.One2many('kjr.facility.room', 'facility_id', string='Räume')
    equipment_ids = fields.One2many('kjr.facility.equipment', 'facility_id', string='Ausstattung')
    bed_total = fields.Integer(string='Betten gesamt', compute='_compute_bed_total')
    # Ein Zeltplatz hat keine Betten. Ohne diese Unterscheidung warb ein Zeltplatz
    # auf der Website mit „40 Betten" (durch die Projektleitung am 17.08.2026
    # geprueft). Die Zahl stimmt, nur die Beschriftung war falsch.
    capacity_label = fields.Char(
        string='Bezeichnung der Kapazität', compute='_compute_capacity_label',
        help='„Betten" bei Häusern, „Plätze" bei Zeltplätzen, für Website und Listen.',
    )
    booking_count = fields.Integer(string='Buchungen', compute='_compute_booking_count')
    website_published = fields.Boolean(string='Auf Website veröffentlicht', default=True)

    @api.depends('facility_type')
    def _compute_capacity_label(self):
        for rec in self:
            rec.capacity_label = _('Plätze') if rec.facility_type == 'campsite' else _('Betten')

    # Die Abhängigkeit gehört an DIESE Methode: gestapelte @api.depends überschreiben
    # sich gegenseitig (attrsetter '_depends'), dadurch hing 'room_ids.capacity'
    # fälschlich an _compute_capacity_label und 'bed_total' wurde bei einer
    # Kapazitätsänderung nicht neu berechnet.
    # 'room_ids.active' MUSS mit in die Abhängigkeit: ein One2many liefert beim
    # Lesen nur die nicht archivierten Datensätze (odoo/orm/fields_relational.py
    # filtert über Comodel._active_name). Das Archivieren eines Raumes ändert aber
    # keine der übrigen deklarierten Abhängigkeiten — ohne 'room_ids.active' blieb
    # bed_total innerhalb derselben Transaktion auf dem alten Wert stehen.
    @api.depends('room_ids.capacity', 'room_ids.active')
    def _compute_bed_total(self):
        for rec in self:
            rec.bed_total = sum(rec.room_ids.mapped('capacity'))

    def _compute_booking_count(self):
        data = self.env['kjr.facility.booking']._read_group(
            [('facility_id', 'in', self.ids)], groupby=['facility_id'], aggregates=['__count'],
        )
        mapped = {f.id: c for f, c in data}
        for rec in self:
            rec.booking_count = mapped.get(rec.id, 0)

    @api.constrains('max_advance_months', 'min_persons', 'min_nights', 'capacity')
    def _check_booking_rules(self):
        """Buchungsregeln dürfen nie negativ sein — 0 ist der Aus-Schalter."""
        for rec in self:
            if rec.max_advance_months < 0:
                raise ValidationError(_(
                    'Der maximale Buchungsvorlauf darf nicht negativ sein '
                    '(0 = unbegrenzt).'))
            if rec.min_persons < 0:
                raise ValidationError(_(
                    'Die Mindestbelegung darf nicht negativ sein (0 = keine Prüfung).'))
            if rec.min_nights < 0:
                raise ValidationError(_(
                    'Der Mindestaufenthalt darf nicht negativ sein (0 = keine Prüfung).'))
            if rec.capacity and rec.min_persons > rec.capacity:
                raise ValidationError(_(
                    'Die Mindestbelegung (%(min)s) ist größer als die maximale '
                    'Personenzahl (%(max)s) der Einrichtung "%(name)s". '
                    'So kann keine Buchung mehr angelegt werden.',
                    min=rec.min_persons, max=rec.capacity, name=rec.name or ''))

    def action_view_bookings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Buchungen'),
            'res_model': 'kjr.facility.booking',
            'view_mode': 'list,calendar,form',
            'domain': [('facility_id', '=', self.id)],
            'context': {'default_facility_id': self.id},
        }

    # ══════════════════════════════════════════════════════════════════════════
    # DOPPELTE RÄUME ERKENNEN (Befund 01.09.2026)
    # ══════════════════════════════════════════════════════════════════════════
    # Am 01.09.2026 standen die Schlafräume einer Einrichtung doppelt in der
    # Datenbank: ein von Hand gepflegter Satz ohne XML-ID und ein zweiter Satz aus
    # einem Modul-Update. bed_total summiert alle AKTIVEN Räume und zeigte dadurch
    # die doppelte Bettenzahl.
    #
    # URSACHE ist nicht ein fehlendes noupdate: die Seed-Räume haben stabile
    # XML-IDs und data/kjr_facility_data.xml liegt vollständig unter
    # <data noupdate="1">. odoo/tools/convert.py bricht bei noupdate aber nur ab,
    # wenn ir.model.data._load_xmlid(xid) den Datensatz FINDET. Kennt die Instanz
    # die XML-ID noch nicht, greift anschließend
    # 'elif not nodeattr2bool(rec, 'forcecreate', True)' — und weil forcecreate
    # standardmäßig True ist, wird der Datensatz normal ANGELEGT.
    #
    # WARUM AM MODELL UND NICHT (NUR) IM MIGRATIONSSKRIPT: ein Skript unter
    # migrations/<version>/ läuft genau EINMAL, beim Schritt auf diese Version
    # (odoo/modules/migration.py: installierte Version < Ordnerversion <= neue
    # Manifestversion). Ein späterer Vorfall — etwa ein in 19.0.8.0.0 neu
    # ausgelieferter Seed-Raum neben einem von Hand gepflegten Raum ohne XML-ID —
    # würde von einem Skript im Ordner 19.0.7.3.0 nie mehr gemeldet. Deshalb liegt
    # die Prüfung hier und wird zusätzlich von einem ir.cron aufgerufen
    # (data/ir_cron_data.xml: cron_kjr_room_duplicates).

    @staticmethod
    def _room_compare_key(name):
        """Vergleichsschlüssel eines Raumnamens: führende Zimmernummer, sonst Name.

        Verglichen wird nur der Teil VOR der ersten Klammer. Würde der
        Klammerzusatz mittokenisiert, bekäme „Schlafsaal (12 Betten)" den
        Schlüssel „12" und kollidierte mit dem völlig korrekten „Zimmer 12
        (1. OG)" — eine Dublette, die keine ist. Aus demselben Grund zählt nur
        eine Zahl am Namensanfang als Zimmernummer.
        """
        name = (name or '').strip().lower()
        base = name.split('(')[0].strip()
        treffer = ROOM_NUMBER_RE.match(base)
        if treffer:
            return treffer.group(1)
        return ' '.join((base or name).split())

    def _find_duplicate_rooms(self):
        """Räume mit gleichem Vergleichsschlüssel je Einrichtung zusammenstellen.

        Rückgabe: Liste von (Einrichtung, Schlüssel, aktive Räume, archivierte Räume).

        Eine Gruppe gilt nur dann als Dublette, wenn MINDESTENS ZWEI AKTIVE Räume
        denselben Schlüssel tragen. Ein bereits archivierter Satz ist der gewollte
        Endzustand und keine offene Dublette — sonst würde jede Instanz, die
        migrations/19.0.3.1.0 durchlaufen hat, dauerhaft eine Falschmeldung
        bekommen. Archivierte Räume werden der Gruppe nur als Hinweis beigelegt,
        damit eine halb bereinigte Dublette nachvollziehbar bleibt.

        Ohne Datensätze im Recordset werden alle Einrichtungen geprüft (Cron).
        """
        einrichtungen = self if self else self.search([])
        if not einrichtungen:
            return []
        raeume = self.env['kjr.facility.room'].with_context(active_test=False).search(
            [('facility_id', 'in', einrichtungen.ids)], order='id')

        gruppen = defaultdict(lambda: {'aktiv': [], 'archiviert': []})
        for raum in raeume:
            eintrag = gruppen[(raum.facility_id.id, self._room_compare_key(raum.name))]
            eintrag['aktiv' if raum.active else 'archiviert'].append(raum)

        befunde = []
        for (facility_id, schluessel), eintrag in sorted(gruppen.items()):
            if len(eintrag['aktiv']) < 2:
                continue
            befunde.append((
                self.browse(facility_id), schluessel,
                eintrag['aktiv'], eintrag['archiviert'],
            ))
        return befunde

    def report_duplicate_rooms(self, herkunft='Prüfung'):
        """Dubletten ins Log schreiben, ohne irgendetwas zu ändern.

        Reiner Lesevorgang: kein write, kein unlink. Welcher Satz der echte ist,
        kann das Modul nicht wissen — die von Hand gepflegten Daten tragen die
        realen Zimmernummern, die Seed-Daten die aus den Unterlagen abgeleiteten.
        Ein automatisches Archivieren würde im schlechteren Fall die gepflegten
        Daten verdecken. Entschieden wird das in der Geschäftsstelle, diese
        Methode liefert ihr die Liste dazu.
        """
        befunde = self._find_duplicate_rooms()
        for einrichtung, schluessel, aktiv, archiviert in befunde:
            hinweis = ''
            if archiviert:
                hinweis = ' Zusätzlich archiviert (zählt nicht in bed_total): %s.' % ', '.join(
                    '"%s" (id %s)' % (raum.name, raum.id) for raum in archiviert)
            _logger.warning(
                '%s: Einrichtung "%s" (id %s) hat %d AKTIVE Räume mit '
                'übereinstimmender Bezeichnung (Schlüssel "%s"): %s. Es wird NICHTS '
                'geändert. Bitte im Backend prüfen, welcher Satz die realen '
                'Zimmernummern trägt, und den anderen archivieren. bed_total '
                'summiert alle aktiven Räume.%s',
                herkunft, einrichtung.name, einrichtung.id, len(aktiv), schluessel,
                ', '.join(
                    '"%s" (id %s, %s Betten)' % (raum.name, raum.id, raum.capacity)
                    for raum in aktiv
                ),
                hinweis,
            )
        if befunde:
            _logger.warning('%s: %d Dublettengruppe(n) gefunden, keine Daten geändert.',
                            herkunft, len(befunde))
        else:
            _logger.info('%s: keine doppelten Räume gefunden.', herkunft)
        return befunde

    @api.model
    def _cron_room_duplicates(self):
        """Wiederholbare Dublettenprüfung über alle Einrichtungen (ir.cron)."""
        # Kein _() : das ist ein Log-Präfix fuer die Administration, kein Nutzertext.
        return self.search([]).report_duplicate_rooms(
            herkunft='Cron kjr_facility: doppelte Räume')


class KjrFacilityRoom(models.Model):
    _name = 'kjr.facility.room'
    _description = 'Raum / Bettenkontingent'
    _order = 'facility_id, sequence, name'

    facility_id = fields.Many2one('kjr.facility', string='Einrichtung', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Raum', required=True)
    capacity = fields.Integer(string='Betten', default=0)
    active = fields.Boolean(default=True)
    housekeeping_state = fields.Selection([
        ('clean', 'Gereinigt'),
        ('dirty', 'Zu reinigen'),
        ('in_progress', 'In Reinigung'),
        ('blocked', 'Gesperrt'),
    ], string='Reinigungsstatus', default='clean')


class KjrFacilityEquipment(models.Model):
    _name = 'kjr.facility.equipment'
    _description = 'Ausstattung / Zusatzleistung'
    _order = 'facility_id, sequence, name'

    facility_id = fields.Many2one('kjr.facility', string='Einrichtung', ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Bezeichnung', required=True)
    category = fields.Char(string='Kategorie')
    quantity = fields.Integer(string='Bestand', default=0)
    price_per_day = fields.Float(string='Preis/Tag (€)', digits=(8, 2))
    icon = fields.Char(string='FontAwesome-Icon', help='z. B. fa-wifi, fa-fire')
