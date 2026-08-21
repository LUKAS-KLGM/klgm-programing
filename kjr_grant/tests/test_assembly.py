# -*- coding: utf-8 -*-
"""Vollversammlung: geheime Vorstandswahl (§ 34 Abs. 3 BJR-Satzung).

Zwei Regeln werden hier als ausführbare Assertion festgeschrieben:

1. Berechnungsgrundlage der Mehrheit sind AUSSCHLIESSLICH die auf Kandidaturen
   entfallenen Stimmen. Enthaltungen und ungültige Stimmen bleiben nach § 33
   Abs. 2 BJR-Satzung außer Betracht — sie dürfen die Schwelle also weder
   anheben noch ein Ergebnis kippen.
2. Geheim heißt: aus den gespeicherten Daten darf sich NICHT rekonstruieren
   lassen, wer wie gestimmt hat. Gespeichert werden nur die vom Wahlausschuss
   ausgezählten Summen. Diese Tests sind eine Sperre gegen ein späteres,
   gut gemeintes Feld "wer hat für wen gestimmt".

Die Mehrheitsermittlung bei Sachbeschlüssen und die Protokoll-Report-Action sind
in ``test_compliance.py`` abgedeckt.
"""
from odoo.tests.common import TransactionCase
from odoo.tests import tagged

# Protokollspalten des ORM (create_uid/write_uid) zeigen zwangsläufig auf
# res.users und sagen nichts über das Stimmverhalten aus — sie bleiben bei der
# Prüfung auf Personenbezüge außen vor.
LOG_ACCESS_FIELDS = ('create_uid', 'write_uid')


@tagged('post_install', '-at_install')
class TestKjrAssemblyElection(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Decision = cls.env['kjr.assembly.decision']
        cls.Candidate = cls.env['kjr.assembly.candidate']
        cls.assembly = cls.env['kjr.assembly'].create({
            'name': 'Vollversammlung 2026',
            'date': '2026-03-01 18:00:00',
            'location': 'Sonthofen',
        })

    def _election(self, **kw):
        vals = {
            'assembly_id': self.assembly.id,
            'name': 'Wahl des Vorsitzes',
            'decision_type': 'election',
            'election_office': 'Vorsitz',
            'seats': 1,
            'majority_rule': 'absolute',
        }
        vals.update(kw)
        return self.Decision.create(vals)

    def _candidates(self, decision, *votes, **kw):
        withdrawn = kw.get('withdrawn', ())
        return self.Candidate.create([
            {
                'decision_id': decision.id,
                'name': 'Kandidatur %d' % (idx + 1),
                'sequence': 10 * (idx + 1),
                'votes': vote,
                'withdrawn': idx in withdrawn,
            }
            for idx, vote in enumerate(votes)
        ])

    # ══ Mehrheit OHNE Enthaltungen ═══════════════════════════════════════════

    def test_majority_ignores_abstentions_and_invalid_ballots(self):
        """7 : 3 Kandidatenstimmen bei 40 Enthaltungen und 10 ungültigen Stimmen.

        Bemessungsgrundlage sind nur die 10 Kandidatenstimmen → Schwelle 6.
        Zählten Enthaltungen und ungültige Stimmen mit, läge die Schwelle bei 31
        und niemand wäre gewählt.
        """
        decision = self._election(vote_abstain=40, vote_invalid=10, ballots_cast=60)
        self._candidates(decision, 7, 3)
        self.assertEqual(decision.election_valid_votes, 10)
        self.assertEqual(decision.election_majority_needed, 6)
        self.assertEqual(decision.election_state, 'elected')
        self.assertEqual(decision.elected_names, 'Kandidatur 1')

    def test_abstentions_do_not_change_the_outcome(self):
        """Dasselbe Ergebnis, nur mit anderen Enthaltungen — die Wahl bleibt gleich."""
        decision = self._election()
        self._candidates(decision, 7, 3)
        baseline = (decision.election_valid_votes,
                    decision.election_majority_needed,
                    decision.election_state)
        decision.write({'vote_abstain': 99, 'vote_invalid': 99})
        self.assertEqual(
            (decision.election_valid_votes,
             decision.election_majority_needed,
             decision.election_state),
            baseline,
            'Enthaltungen und ungültige Stimmen dürfen die Mehrheit nicht verschieben.')

    def test_absolute_majority_missed_leads_to_runoff(self):
        """4 : 3 : 3 Stimmen, ein Sitz, absolute Mehrheit → Schwelle 6, niemand
        erreicht sie → Stichwahl statt "gewählt mit relativer Mehrheit"."""
        decision = self._election()
        self._candidates(decision, 4, 3, 3)
        self.assertEqual(decision.election_valid_votes, 10)
        self.assertEqual(decision.election_majority_needed, 6)
        self.assertEqual(decision.election_state, 'runoff')
        self.assertFalse(decision.elected_names)

    def test_relative_majority_has_no_fixed_threshold(self):
        """Bei einfacher Mehrheit gewinnt die meiste Stimmenzahl (Schwelle 0)."""
        decision = self._election(majority_rule='relative')
        self._candidates(decision, 4, 3, 3)
        self.assertEqual(decision.election_majority_needed, 0)
        self.assertEqual(decision.election_state, 'elected')
        self.assertEqual(decision.elected_names, 'Kandidatur 1')

    def test_tie_at_the_seat_boundary_requires_a_runoff(self):
        """Stimmengleichheit an der Sitzgrenze: es wird nicht gelost und nicht nach
        Reihenfolge entschieden — es gibt eine Stichwahl."""
        decision = self._election(majority_rule='relative')
        self._candidates(decision, 5, 5)
        self.assertEqual(decision.election_state, 'runoff')
        self.assertFalse(decision.elected_names)

    def test_withdrawn_candidacy_is_out_of_the_count(self):
        """Eine zurückgezogene Kandidatur bleibt dokumentiert, zählt aber nicht mit."""
        decision = self._election()
        cands = self._candidates(decision, 6, 4, withdrawn=(1,))
        self.assertEqual(decision.election_valid_votes, 6)
        self.assertEqual(decision.election_majority_needed, 4)
        self.assertEqual(decision.election_state, 'elected')
        self.assertEqual(decision.elected_names, 'Kandidatur 1')
        self.assertTrue(cands[1].withdrawn)
        self.assertFalse(cands[1].is_elected)

    def test_multi_seat_election(self):
        """Zwei Sitze: die beiden Bestplatzierten oberhalb der Schwelle sind gewählt."""
        decision = self._election(seats=2, majority_rule='relative',
                                  election_office='Beisitz')
        self._candidates(decision, 9, 7, 2)
        self.assertEqual(decision.election_state, 'elected')
        self.assertEqual(decision.elected_names, 'Kandidatur 1, Kandidatur 2')

    def test_only_abstentions_means_the_ballot_failed(self):
        """Nur Enthaltungen/ungültige Stimmen: der Wahlgang ist gescheitert,
        nicht "offen" und erst recht nicht "gewählt"."""
        decision = self._election(vote_abstain=12)
        self._candidates(decision, 0)
        self.assertEqual(decision.election_valid_votes, 0)
        self.assertEqual(decision.election_state, 'failed')

    def test_uncounted_election_stays_open(self):
        """Ohne jede erfasste Stimme ist der Wahlgang schlicht noch nicht ausgezählt."""
        decision = self._election()
        self._candidates(decision, 0, 0)
        self.assertEqual(decision.election_state, 'open')

    def test_resolution_fields_stay_empty_for_elections(self):
        """Eine Wahl wird über das Wahlergebnis ausgewiesen, nicht über Ja/Nein."""
        decision = self._election()
        self._candidates(decision, 7, 3)
        self.assertFalse(decision.result)

    # ══ Wahlgeheimnis: nur Summen, kein Stimmverhalten ═══════════════════════

    def test_candidate_model_has_no_link_to_individual_voters(self):
        """Am Kandidatur-Datensatz gibt es keine Verknüpfung zu Wählenden.

        Erlaubt ist genau ein Kontaktbezug: ``partner_id`` — das ist die
        kandidierende Person selbst, keine Stimmabgabe. Jede weitere Relation zu
        ``res.partner``/``res.users`` (erst recht eine x2many-Liste) würde das
        Wahlgeheimnis technisch aufheben, weil jede Auswertung und jeder
        Datenbank-Export das Stimmverhalten offenlegen könnte.
        """
        voter_links = sorted(
            name for name, field in self.Candidate._fields.items()
            if name not in LOG_ACCESS_FIELDS
            and field.relational and field.comodel_name in ('res.partner', 'res.users')
        )
        self.assertEqual(voter_links, ['partner_id'], (
            'Unerwartete Personenbezüge an der Kandidatur: %s. Ein Feld, das eine '
            'einzelne Stimme einer Person oder einem Verband zuordnet, ist bei einer '
            'geheimen Wahl (§ 34 Abs. 3 BJR-Satzung) unzulässig.' % voter_links))
        self.assertEqual(self.Candidate._fields['partner_id'].type, 'many2one')

    def test_decision_model_has_no_link_to_individual_voters(self):
        """Auch am Wahlgang selbst hängt kein Personenbezug zu Stimmen."""
        voter_links = sorted(
            name for name, field in self.Decision._fields.items()
            if name not in LOG_ACCESS_FIELDS
            and field.relational and field.comodel_name in ('res.partner', 'res.users')
        )
        self.assertFalse(voter_links, (
            'Am Wahlgang dürfen keine Wählenden hängen (geheime Wahl); gefunden: %s'
            % voter_links))

    def test_no_ballot_level_model_exists(self):
        """Es gibt keine Stimmzettel-Einzeldatensätze — nur ausgezählte Summen."""
        forbidden = [
            'kjr.assembly.vote', 'kjr.assembly.ballot', 'kjr.assembly.candidate.vote',
        ]
        present = [name for name in forbidden if name in self.env]
        self.assertFalse(present, (
            'Stimmzettel-Einzeldatensätze (%s) heben die geheime Wahl auf.' % present))

    def test_attendance_is_recorded_without_voting_behaviour(self):
        """Die Anwesenheitsliste belegt die Teilnahme, nicht das Stimmverhalten."""
        member = self.env['res.partner'].create({
            'name': 'Stimmberechtigter Verband e. V.',
            'is_company': True, 'is_kjr_member': True, 'kjr_vr_right': True,
        })
        self.assembly.attendee_ids = [(6, 0, [member.id])]
        decision = self._election()
        self._candidates(decision, 7, 3)
        self.assertIn(member, self.assembly.attendee_ids)
        # Aus dem Wahlgang führt kein Weg zurück auf die anwesende Person.
        self.assertEqual(decision.candidate_ids.mapped('partner_id'),
                         self.env['res.partner'])

    def test_plausibility_hint_is_only_a_hint(self):
        """Abweichende Auszählungen werden gemeldet, aber nicht blockiert —
        die Geschäftsstelle muss auch strittige Ergebnisse erfassen können."""
        decision = self._election(ballots_cast=20)
        self._candidates(decision, 7, 3)
        self.assertTrue(decision.plausibility_hint)
        self.assertEqual(decision.election_state, 'elected')
