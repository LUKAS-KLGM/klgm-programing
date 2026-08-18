# -*- coding: utf-8 -*-
"""E14 – Warteliste: Anmeldung bei ausgebuchter Veranstaltung, Nachrücken (FIFO).

Fachliche Leitplanken, die hier als ausführbare Assertion festgeschrieben werden:

* Eine Anmeldung auf eine volle Veranstaltung scheitert nicht, sondern landet auf
  der Warteliste (nur bei aktivierter Warteliste — sonst bleibt der Odoo-Standard).
* Ein Wartelistenplatz belegt KEINEN regulären Platz: ``seats_taken`` darf sich
  durch ihn nicht erhöhen, sonst blockieren sich die Wartenden gegenseitig.
* Nachgerückt wird in der Reihenfolge des Anmeldezeitpunkts (FIFO) und nur, wenn
  wirklich ein Platz frei ist.
* Die angezeigte Wartelistenposition bleibt nach dem Nachrücken lückenlos.
"""
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestKjrEventWaitlist(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Event = cls.env['event.event']
        cls.Registration = cls.env['event.registration']
        cls.event = cls._make_event(waitlist=True, seats_max=2)

    @classmethod
    def _make_event(cls, waitlist=True, seats_max=2, name='Ferienfreizeit (begrenzt)'):
        """Veranstaltung mit begrenzter Platzzahl.

        ``seats_limited`` wird nur gesetzt, wenn die Odoo-Edition das Feld führt —
        genau wie ``event.event._kjr_free_seats()`` es ausliest. Ohne diese Prüfung
        wäre der Test an eine bestimmte Feldausstattung des Kernmoduls gebunden.
        """
        vals = {
            'name': name,
            'date_begin': '2026-08-01 09:00:00',
            'date_end': '2026-08-05 17:00:00',
            'kjr_event_type': 'ferienprogramm',
            'seats_max': seats_max,
            'kjr_waitlist_enabled': waitlist,
        }
        if 'seats_limited' in cls.Event._fields:
            vals['seats_limited'] = True
        return cls.Event.create(vals)

    def _reg(self, event=None, **kw):
        vals = {'event_id': (event or self.event).id, 'name': 'Teilnehmer'}
        vals.update(kw)
        return self.Registration.create(vals)

    # ── Verteilung auf reguläre Plätze bzw. Warteliste ───────────────────────

    def test_registration_within_capacity_takes_a_seat(self):
        """Solange Plätze frei sind, entsteht ein ganz normaler regulärer Platz."""
        first = self._reg(name='Anna')
        second = self._reg(name='Ben')
        self.assertFalse(first.kjr_is_waitlist)
        self.assertFalse(second.kjr_is_waitlist)
        self.assertEqual(self.event.seats_taken, 2)
        self.assertEqual(self.event._kjr_free_seats(), 0)

    def test_registration_on_full_event_goes_to_waitlist(self):
        """Die dritte Anmeldung auf zwei Plätze scheitert nicht, sondern wartet."""
        self._reg(name='Anna')
        self._reg(name='Ben')
        third = self._reg(name='Clara')
        self.assertTrue(third.kjr_is_waitlist,
                        'Bei voller Veranstaltung muss die Anmeldung auf die '
                        'Warteliste gehen statt abgewiesen zu werden.')
        self.assertNotEqual(third.state, 'cancel')

    def test_waitlist_seat_does_not_count_as_taken(self):
        """Ein Wartelistenplatz erhöht die belegten Plätze NICHT.

        Sonst wäre die Veranstaltung nach dem ersten Wartenden rechnerisch
        überbucht und weitere Wartende würden sich gegenseitig blockieren.
        """
        self._reg(name='Anna')
        self._reg(name='Ben')
        taken_before = self.event.seats_taken
        self._reg(name='Clara')
        self._reg(name='Dilan')
        self.event.invalidate_recordset(['seats_taken'])
        self.assertEqual(self.event.seats_taken, taken_before)
        self.assertEqual(self.event.kjr_waitlist_count, 2)

    def test_waitlist_disabled_keeps_standard_behaviour(self):
        """Ohne aktivierte Warteliste greift die Verteilung gar nicht erst.

        Geprüft wird die Verteilstufe (``_kjr_dispatch_waitlist``) und nicht das
        Anlegen selbst: ob der Odoo-Kern eine Überbuchung abweist, ist Verhalten
        des Kernmoduls und nicht Gegenstand dieses Tests.
        """
        event = self._make_event(waitlist=False, seats_max=1, name='Ohne Warteliste')
        self._reg(event=event, name='Anna')
        vals_list = [{'event_id': event.id, 'name': 'Ben'}]
        self.Registration._kjr_dispatch_waitlist(vals_list)
        self.assertNotIn('kjr_is_waitlist', vals_list[0],
                         'Ohne aktivierte Warteliste darf nichts umgelenkt werden.')

    def test_dispatch_flags_only_the_overhanging_registrations(self):
        """Von einem Stapel Anmeldungen wandern nur die überzähligen auf die Warteliste."""
        vals_list = [
            {'event_id': self.event.id, 'name': 'Anna'},
            {'event_id': self.event.id, 'name': 'Ben'},
            {'event_id': self.event.id, 'name': 'Clara'},
        ]
        self.Registration._kjr_dispatch_waitlist(vals_list)
        self.assertNotIn('kjr_is_waitlist', vals_list[0])
        self.assertNotIn('kjr_is_waitlist', vals_list[1])
        self.assertTrue(vals_list[2].get('kjr_is_waitlist'))

    # ── Position auf der Warteliste ──────────────────────────────────────────

    def test_waitlist_positions_are_fifo(self):
        """Die Position folgt dem Anmeldezeitpunkt und beginnt bei 1."""
        self._reg(name='Anna')
        self._reg(name='Ben')
        third = self._reg(name='Clara')
        fourth = self._reg(name='Dilan')
        self.assertEqual(third.kjr_waitlist_position, 1)
        self.assertEqual(fourth.kjr_waitlist_position, 2)

    def test_regular_registration_has_no_position(self):
        """Wer einen regulären Platz hat, steht auf keiner Warteliste (Position 0)."""
        first = self._reg(name='Anna')
        self.assertEqual(first.kjr_waitlist_position, 0)

    # ── Nachrücken ───────────────────────────────────────────────────────────

    def test_promote_from_waitlist_is_fifo_and_keeps_positions_gapless(self):
        """Nachgerückt wird die erste wartende Anmeldung; danach bleibt die
        Nummerierung der übrigen lückenlos ab 1."""
        first = self._reg(name='Anna')
        self._reg(name='Ben')
        third = self._reg(name='Clara')
        fourth = self._reg(name='Dilan')

        # Ein regulärer Platz wird frei.
        first.write({'state': 'cancel'})
        self.event.invalidate_recordset(['seats_taken'])
        self.assertEqual(self.event._kjr_free_seats(), 1)
        self.assertTrue(self.event.kjr_waitlist_ready)

        self.event.action_kjr_promote_from_waitlist()

        self.assertFalse(third.kjr_is_waitlist)
        self.assertEqual(third.state, 'open')
        self.assertTrue(fourth.kjr_is_waitlist,
                        'Es darf immer nur eine Anmeldung nachrücken.')
        # Die Position ist bewusst nicht gespeichert; der Cache der ÜBRIGEN
        # Anmeldung hängt nicht an den Feldern der nachgerückten und muss für
        # die Prüfung ausdrücklich verworfen werden.
        fourth.invalidate_recordset(['kjr_waitlist_position'])
        self.assertEqual(fourth.kjr_waitlist_position, 1,
                         'Nach dem Nachrücken muss die Warteliste lückenlos ab 1 laufen.')
        self.event.invalidate_recordset(['seats_taken'])
        self.assertEqual(self.event.seats_taken, 2)
        self.assertEqual(self.event.kjr_waitlist_count, 1)

    def test_promote_without_free_seat_is_refused(self):
        """Ohne freien Platz wird nicht nachgerückt (sonst wäre die Fahrt überbucht)."""
        self._reg(name='Anna')
        self._reg(name='Ben')
        self._reg(name='Clara')
        self.assertEqual(self.event._kjr_free_seats(), 0)
        self.assertFalse(self.event.kjr_waitlist_ready)
        with self.assertRaises(UserError):
            self.event.action_kjr_promote_from_waitlist()

    def test_promote_requires_someone_on_the_waitlist(self):
        """Steht niemand auf der Warteliste, meldet die Aktion das ausdrücklich."""
        self._reg(name='Anna')
        with self.assertRaises(UserError):
            self.event.action_kjr_promote_from_waitlist()

    def test_promote_single_registration_requires_waitlist_flag(self):
        """Eine reguläre Anmeldung lässt sich nicht "nachrücken"."""
        first = self._reg(name='Anna')
        with self.assertRaises(UserError):
            first.action_kjr_promote_waitlist()

    def test_manual_return_to_waitlist_frees_the_seat(self):
        """Wird jemand zurück auf die Warteliste gesetzt, wird der Platz sofort frei."""
        first = self._reg(name='Anna')
        self._reg(name='Ben')
        self.assertEqual(self.event._kjr_free_seats(), 0)
        first.write({'kjr_is_waitlist': True})
        self.event.invalidate_recordset(['seats_taken'])
        self.assertEqual(self.event._kjr_free_seats(), 1)
        self.assertTrue(first.kjr_is_waitlist)
