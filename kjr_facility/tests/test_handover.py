# -*- coding: utf-8 -*-
"""Übergabeprotokoll Anreise/Abreise (Haus, Zeltplatz).

Fachliche Leitplanke, übernommen aus dem Rückgabeprotokoll in kjr_rental: Das
Protokoll dokumentiert den ZUSTAND und ist KEINE Freigabebedingung. Ein Mangel
darf den Abschluss der Buchung nicht verhindern — er verlangt nur einen Vermerk.
Andernfalls kreuzt das Personal wahrheitswidrig "in Ordnung" an und das
Protokoll verliert genau den Nachweiswert, für den es gebaut wird.

Daraus die drei geprüften Regeln:

* Feststellung OHNE Vermerk  -> wird abgewiesen (unvollständige Dokumentation),
* Feststellung MIT Vermerk   -> Erfassung und Abschluss der Buchung gehen durch,
* gar kein erfasstes Protokoll -> blockiert nichts (Nacherfassung, Papierprotokoll).
"""
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestKjrFacilityHandover(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Gruppe Übergabe'})
        cls.facility = cls.env['kjr.facility'].create({
            'name': 'Selbstversorgerhaus Test', 'facility_type': 'house',
            'capacity': 42, 'supervision_ratio': 5,
        })

    def _booking(self, state='checked_in', **kw):
        """Buchung OHNE Tarif: der berechenbare Betrag bleibt 0,00 €, damit
        ``action_done`` keine Rechnung verlangt und der Test wirklich das
        Übergabeprotokoll prüft."""
        vals = {
            'facility_id': self.facility.id,
            'partner_id': self.partner.id,
            'check_in': '2026-08-01',
            'check_out': '2026-08-05',
            'participant_count': 10,
            'leader_count': 2,
        }
        vals.update(kw)
        booking = self.env['kjr.facility.booking'].create(vals)
        # Status direkt setzen: die Workflow-Actions versenden Mails und legen
        # PDF-Dokumente an — beides ist hier nicht Gegenstand des Tests.
        booking.state = state
        return booking

    # ── Anreiseprotokoll ─────────────────────────────────────────────────────

    def test_arrival_protocol_without_findings_passes(self):
        """Zustand "ordnungsgemäß": das Protokoll geht ohne Vermerk durch."""
        booking = self._booking(state='confirmed', handover_in_condition='ok',
                                handover_in_received_by='Gruppenleitung')
        booking.action_handover_arrival()
        self.assertTrue(booking.handover_in_date,
                        'Das Übergabedatum wird beim Festschreiben gesetzt.')
        self.assertEqual(booking.handover_in_user_id, self.env.user)

    def test_arrival_damage_without_description_is_refused(self):
        """"Schaden festgestellt" ohne Schadensbeschreibung wird abgewiesen."""
        booking = self._booking(state='confirmed', handover_in_damage=True)
        with self.assertRaises(UserError):
            booking.action_handover_arrival()

    def test_arrival_damage_with_description_passes(self):
        """Mit Beschreibung ist die Feststellung dokumentiert — Erfassung geht durch."""
        booking = self._booking(
            state='confirmed', handover_in_damage=True,
            handover_in_damage_note='Vorschaden Fensterbank Aufenthaltsraum, '
                                    'bei Übergabe gemeinsam festgestellt.')
        booking.action_handover_arrival()
        self.assertTrue(booking.handover_in_date)

    def test_arrival_defect_requires_some_note(self):
        """Kleinere Mängel verlangen irgendeinen Vermerk, der sie beschreibt."""
        booking = self._booking(state='confirmed', handover_in_condition='minor')
        with self.assertRaises(UserError):
            booking.action_handover_arrival()
        booking.handover_in_note = 'Zwei Rollos im Schlafsaal klemmen.'
        booking.action_handover_arrival()
        self.assertTrue(booking.handover_in_date)

    def test_arrival_protocol_needs_a_binding_booking(self):
        """Vor der verbindlichen Buchung gibt es nichts zu übergeben."""
        booking = self._booking(state='reserved', handover_in_condition='ok')
        with self.assertRaises(UserError):
            booking.action_handover_arrival()

    # ── Abreiseprotokoll ─────────────────────────────────────────────────────

    def test_departure_damage_without_description_is_refused(self):
        booking = self._booking(handover_out_damage=True,
                                handover_out_cleaning_ok=True)
        with self.assertRaises(UserError):
            booking.action_handover_departure()

    def test_departure_uncleaned_without_note_is_refused(self):
        """Fehlt das Häkchen "Gereinigt übergeben", ist das eine Abweichung —
        sie verlangt einen Vermerk, hindert die Rücknahme aber nicht."""
        booking = self._booking(handover_out_condition='ok',
                                handover_out_cleaning_ok=False)
        with self.assertRaises(UserError):
            booking.action_handover_departure()
        booking.handover_out_note = 'Küche ungereinigt, Nachreinigung vereinbart.'
        booking.action_handover_departure()
        self.assertTrue(booking.handover_out_date)

    def test_departure_marks_rooms_for_housekeeping(self):
        """Die Rücknahme setzt die Räume der Buchung auf "Zu reinigen"."""
        room = self.env['kjr.facility.room'].create({
            'name': 'Schlafsaal Übergabe', 'facility_id': self.facility.id,
            'capacity': 20,
        })
        booking = self._booking(handover_out_condition='ok',
                                handover_out_cleaning_ok=True,
                                room_ids=[(6, 0, [room.id])])
        booking.action_handover_departure()
        self.assertEqual(room.housekeeping_state, 'dirty')

    # ── Abschluss der Buchung ────────────────────────────────────────────────

    def test_done_is_blocked_while_a_finding_is_undocumented(self):
        """Eine Feststellung ohne Vermerk verhindert den Abschluss."""
        booking = self._booking(handover_out_damage=True,
                                handover_out_cleaning_ok=True)
        with self.assertRaises(UserError):
            booking.action_done()
        self.assertEqual(booking.state, 'checked_in')

    def test_done_passes_once_the_finding_is_documented(self):
        """MIT Vermerk lässt sich die Buchung abschließen — der Mangel selbst
        ist KEIN Hinderungsgrund."""
        booking = self._booking(
            handover_out_condition='major',
            handover_out_damage=True,
            handover_out_cleaning_ok=False,
            handover_out_damage_note='Tür Geräteraum aufgebrochen, Schloss ersetzt.',
            handover_out_note='Nachreinigung Küche durch Hausmeisterservice.')
        booking.action_done()
        self.assertEqual(booking.state, 'done',
                         'Ein dokumentierter Mangel darf den Abschluss nicht verhindern.')

    def test_done_without_any_protocol_is_not_blocked(self):
        """Ohne erfasstes Protokoll blockiert nichts (Nacherfassung, Papierprotokoll);
        es wird lediglich im Chatter darauf hingewiesen."""
        booking = self._booking()
        self.assertFalse(booking._handover_recorded('out'))
        booking.action_done()
        self.assertEqual(booking.state, 'done')
        bodies = booking.message_ids.mapped('body')
        self.assertTrue(any('Übergabeprotokoll' in (body or '') for body in bodies),
                        'Der fehlende Protokolleintrag muss im Chatter vermerkt werden.')

    def test_done_with_clean_protocol_passes(self):
        """Vollständig in Ordnung erfasstes Protokoll: Abschluss ohne Beanstandung."""
        booking = self._booking(handover_out_condition='ok',
                                handover_out_cleaning_ok=True,
                                handover_out_handed_by='Gruppenleitung')
        self.assertTrue(booking._handover_recorded('out'))
        self.assertFalse(booking._handover_findings('out'))
        booking.action_done()
        self.assertEqual(booking.state, 'done')

    # ── Hilfslogik ───────────────────────────────────────────────────────────

    def test_recorded_detects_any_entry(self):
        """Schon ein einzelner Eintrag gilt als erfasstes Protokoll."""
        booking = self._booking()
        self.assertFalse(booking._handover_recorded('in'))
        booking.handover_in_note = '   '
        self.assertFalse(booking._handover_recorded('in'),
                         'Reine Leerzeichen sind kein Vermerk.')
        booking.handover_in_note = 'Einweisung Heizung erfolgt.'
        self.assertTrue(booking._handover_recorded('in'))

    def test_findings_list_is_complete(self):
        """Alle Abweichungen erscheinen in der Feststellungsliste."""
        booking = self._booking(handover_out_condition='major',
                                handover_out_damage=True,
                                handover_out_cleaning_ok=False)
        findings = booking._handover_findings('out')
        self.assertEqual(len(findings), 3, findings)
        # Bei der Anreise gibt es kein Reinigungshäkchen.
        booking.handover_in_condition = 'minor'
        self.assertEqual(len(booking._handover_findings('in')), 1)
