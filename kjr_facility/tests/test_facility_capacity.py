# -*- coding: utf-8 -*-
"""Tests der Kapazitätsrechnung einer Einrichtung: bed_total und capacity_label.

Hintergrund (Befund 01.09.2026): Die Schlafräume einer Einrichtung standen doppelt
in der Datenbank, bed_total zeigte 84 statt 42 Betten. Die Summenbildung und die
Frage, welche Räume mitzählen, waren bis dahin nicht abgedeckt. Genau das halten
diese Tests fest.
"""
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestKjrFacilityCapacity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # White Label: neutrale Testbezeichnungen, keine Kundennamen.
        cls.haus = cls.env['kjr.facility'].create({
            'name': 'Testhaus', 'facility_type': 'house', 'capacity': 20,
        })
        cls.raeume = cls.env['kjr.facility.room'].create([
            {'name': 'Zimmer 1', 'facility_id': cls.haus.id, 'capacity': 4},
            {'name': 'Zimmer 2', 'facility_id': cls.haus.id, 'capacity': 3},
            {'name': 'Zimmer 3', 'facility_id': cls.haus.id, 'capacity': 2},
        ])

    def test_bed_total_summiert_raeume(self):
        """bed_total ist die Summe der Bettenzahlen aller Räume."""
        self.assertEqual(self.haus.bed_total, 9)

    def test_bed_total_rechnet_bei_kapazitaetsaenderung_nach(self):
        """Ändert sich die Bettenzahl eines Raumes, rechnet bed_total nach.

        Hält den Kommentar an _compute_bed_total fest: gestapelte @api.depends
        überschreiben sich gegenseitig, dadurch hing 'room_ids.capacity' zeitweise
        an _compute_capacity_label und bed_total blieb stehen.
        """
        self.raeume[0].capacity = 6
        self.assertEqual(self.haus.bed_total, 11)

    def test_bed_total_ignoriert_archivierte_raeume(self):
        """Archivierte Räume zählen nicht mehr mit, und zwar sofort.

        room_ids ist ein One2many auf ein Modell mit active-Feld; archivierte
        Räume fallen beim Lesen heraus. Das ist der Hebel, mit dem die
        Geschäftsstelle eine Dublette aus der Summe nimmt, ohne Daten zu
        verlieren.

        Bewusst OHNE invalidate_recordset: 'room_ids.active' steht in
        @api.depends von _compute_bed_total. Fehlt es dort, liefert bed_total
        innerhalb derselben Transaktion weiter den alten Wert - ein Testaufruf
        von invalidate_recordset würde genau diesen Fehler verdecken.
        """
        self.raeume[0].active = False
        self.assertEqual(self.haus.bed_total, 5)

    def test_bed_total_ohne_raeume_ist_null(self):
        """Eine Einrichtung ohne Räume hat 0 Betten, keinen Fehler."""
        leer = self.env['kjr.facility'].create({
            'name': 'Testhaus ohne Zimmer', 'facility_type': 'house',
        })
        self.assertEqual(leer.bed_total, 0)

    def test_capacity_label_haus_gegen_zeltplatz(self):
        """Ein Haus hat Betten, ein Zeltplatz Plätze.

        Ohne diese Unterscheidung warb ein Zeltplatz auf der Website mit „Betten".
        """
        self.assertEqual(self.haus.capacity_label, 'Betten')
        zeltplatz = self.env['kjr.facility'].create({
            'name': 'Testzeltplatz', 'facility_type': 'campsite', 'capacity': 40,
        })
        self.assertEqual(zeltplatz.capacity_label, 'Plätze')

    def test_capacity_label_folgt_dem_einrichtungstyp(self):
        """Wird die Art der Einrichtung geändert, folgt die Beschriftung."""
        self.haus.facility_type = 'campsite'
        self.assertEqual(self.haus.capacity_label, 'Plätze')


@tagged('post_install', '-at_install')
class TestKjrFacilityRoomDuplicates(TransactionCase):
    """Erkennung doppelter Räume (Befund 01.09.2026).

    Geprüft wird beides: dass eine echte Dublette gemeldet wird und dass die
    bekannten Falschmeldungen ausbleiben.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Facility = cls.env['kjr.facility']
        cls.Room = cls.env['kjr.facility.room']
        # White Label: neutrale Testbezeichnungen, keine Kundennamen.
        cls.haus = cls.Facility.create({'name': 'Testhaus', 'facility_type': 'house'})

    def _raum(self, name, capacity=4, active=True, facility=None):
        return self.Room.create({
            'name': name, 'capacity': capacity, 'active': active,
            'facility_id': (facility or self.haus).id,
        })

    # ── Vergleichsschlüssel ──────────────────────────────────────────────────
    def test_schluessel_ist_die_fuehrende_zimmernummer(self):
        """Die Zimmernummer am Namensanfang ist der Schlüssel."""
        self.assertEqual(self.Facility._room_compare_key('Zimmer 12'), '12')

    def test_schluessel_ignoriert_den_klammerzusatz(self):
        """„Zimmer 12" und „Zimmer 12 (1. OG)" sind dieselbe Sache."""
        self.assertEqual(
            self.Facility._room_compare_key('Zimmer 12 (1. OG)'),
            self.Facility._room_compare_key('Zimmer 12'))

    def test_bettenzahl_in_klammern_ist_keine_zimmernummer(self):
        """Die Zahl im Klammerzusatz darf nie als Zimmernummer gelesen werden.

        Genau hier lag der Fehler: „Schlafsaal (12 Betten)" bekam über die erste
        Ziffernfolge im Namen den Schlüssel „12" und kollidierte mit dem völlig
        korrekten „Zimmer 12 (1. OG)".
        """
        self.assertEqual(
            self.Facility._room_compare_key('Schlafsaal (12 Betten)'), 'schlafsaal')
        self.assertNotEqual(
            self.Facility._room_compare_key('Schlafsaal (12 Betten)'),
            self.Facility._room_compare_key('Zimmer 12 (1. OG)'))

    def test_schluessel_ohne_nummer_ist_der_name(self):
        """Ein Raum ohne Nummer wird über seinen normalisierten Namen verglichen."""
        self.assertEqual(self.Facility._room_compare_key('  Zeltwiese  '), 'zeltwiese')

    # ── Gruppierung ──────────────────────────────────────────────────────────
    def test_echte_dublette_wird_gemeldet(self):
        """Zwei aktive Räume mit derselben Zimmernummer sind eine Dublette."""
        self._raum('Zimmer 12')
        self._raum('Zimmer 12 (1. OG)')
        befunde = self.haus._find_duplicate_rooms()
        self.assertEqual(len(befunde), 1)
        _einrichtung, schluessel, aktiv, archiviert = befunde[0]
        self.assertEqual(schluessel, '12')
        self.assertEqual(len(aktiv), 2)
        self.assertFalse(archiviert)

    def test_platzhalter_mit_bettenzahl_ist_keine_dublette(self):
        """„Schlafsaal (12 Betten)" neben „Zimmer 12 (1. OG)" ist keine Dublette.

        Diese Kombination steht auf jeder Bestandsinstanz: der Platzhalter aus
        dem alten Seed und das echte Zimmer aus der gepflegten Zimmerliste.
        """
        self._raum('Schlafsaal (12 Betten)', capacity=12)
        self._raum('Zimmer 12 (1. OG)')
        self.assertEqual(self.haus._find_duplicate_rooms(), [])

    def test_archivierter_raum_zaehlt_nicht_als_dublette(self):
        """Ein bereits archivierter Satz ist der gewollte Endzustand.

        migrations/19.0.3.1.0 hat die Platzhalter archiviert statt gelöscht.
        Würden archivierte Räume als Gruppenmitglied zählen, meldete jede
        bereinigte Instanz dauerhaft eine Dublette, die keine mehr ist.
        """
        self._raum('Zimmer 12')
        self._raum('Zimmer 12 (1. OG)', active=False)
        self.assertEqual(self.haus._find_duplicate_rooms(), [])

    def test_archivierter_raum_wird_als_hinweis_mitgemeldet(self):
        """Zu einer echten Dublette wird ein archivierter Satz als Hinweis geführt."""
        self._raum('Zimmer 12')
        self._raum('Zimmer 12 (1. OG)')
        archiv = self._raum('Zimmer 12 (DG)', active=False)
        befunde = self.haus._find_duplicate_rooms()
        self.assertEqual(len(befunde), 1)
        _einrichtung, _schluessel, aktiv, archiviert = befunde[0]
        self.assertEqual(len(aktiv), 2)
        self.assertEqual([r.id for r in archiviert], [archiv.id])

    def test_gleiche_nummer_in_zwei_einrichtungen_ist_keine_dublette(self):
        """Zwei Häuser dürfen beide ein „Zimmer 12" haben."""
        zweites = self.Facility.create({'name': 'Testhaus 2', 'facility_type': 'house'})
        self._raum('Zimmer 12')
        self._raum('Zimmer 12', facility=zweites)
        self.assertEqual((self.haus + zweites)._find_duplicate_rooms(), [])

    def test_pruefung_aendert_keine_daten(self):
        """Die Prüfung meldet nur; sie archiviert nichts und löscht nichts."""
        a = self._raum('Zimmer 12')
        b = self._raum('Zimmer 12 (1. OG)')
        self.haus.report_duplicate_rooms(herkunft='Test')
        self.assertTrue(a.active)
        self.assertTrue(b.active)
        self.assertEqual(self.haus.bed_total, 8)
