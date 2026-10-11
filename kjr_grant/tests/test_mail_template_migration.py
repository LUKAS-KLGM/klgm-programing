# -*- coding: utf-8 -*-
"""Tests der Textumstellung aus migrations/19.0.15.7.0/post-migration.py.

Das Skript baut in ``mail.template.body_html`` jedes ``{{ … }}`` im Fließtext auf
``<t t-out="…"/>`` um, weil QWeb ``{{ }}`` nur innerhalb von Attributen
interpoliert. Geprüft wird hier ausschließlich die reine Textfunktion ``_convert``:
sie entscheidet, was umgebaut wird und was stehen bleibt, und genau daran hängt,
ob eine Bestandsinstanz lesbare Mails bekommt oder ihre Vorlagen zerschossen
werden.

Seit demselben Stand zieht das Skript ausserdem den Halbgeviertstrich zwischen
Beginn und Ende der Massnahme nach (``_ersetze_zeitraum_strich``). Auch das ist
eine reine Textfunktion und wird hier ohne Datenbankzugriff geprüft.

Das Migrationsmodul ist kein Python-Paket (der Ordner heißt ``19.0.15.7.0`` und
ist kein gültiger Bezeichner), deshalb wird es über seinen Dateipfad geladen.
"""
import importlib.util

from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.tools.misc import file_path

MIGRATION = 'kjr_grant/migrations/19.0.15.7.0/post-migration.py'


def _load_migration():
    """Migrationsskript als Modul laden, ohne es auszuführen."""
    spec = importlib.util.spec_from_file_location(
        'kjr_grant_mail_migration', file_path(MIGRATION),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged('post_install', '-at_install')
class TestKjrMailTemplateMigration(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.migration = _load_migration()

    def test_platzhalter_im_fliesstext_wird_umgebaut(self):
        """Im Textknoten gehört <t t-out="…"/>; genau das war der Fehler aus
        19.0.15.3.0, der im Chatter sichtbar „{{ object.name }}" stehen ließ."""
        neu, ersetzt, uebersprungen = self.migration._convert(
            '<p>Hallo {{ object.name }}</p>')
        self.assertEqual(neu, '<p>Hallo <t t-out="object.name"/></p>')
        self.assertEqual(ersetzt, 1)
        self.assertEqual(uebersprungen, 0)

    def test_platzhalter_im_attribut_bleibt_stehen(self):
        """In einem HTML-Attribut ist ``{{ }}`` für QWeb korrekt. Ein Umbau dort
        bräuchte t-attf-; das Skript lässt solche Stellen bewusst liegen und
        zählt sie, damit sie von Hand nachgesehen werden können."""
        quelle = '<a href="{{ object.url }}">x</a>'
        neu, ersetzt, uebersprungen = self.migration._convert(quelle)
        self.assertEqual(neu, quelle)
        self.assertEqual(ersetzt, 0)
        self.assertEqual(uebersprungen, 1)

    def test_zweiter_lauf_aendert_nichts(self):
        """Idempotenz: Migrationsskripte laufen bei jedem Versionssprung erneut
        über denselben Bestand, ein zweiter Durchgang darf nichts mehr anfassen."""
        einmal = self.migration._convert('<p>Hallo {{ object.name }}</p>')[0]
        zweimal, ersetzt, uebersprungen = self.migration._convert(einmal)
        self.assertEqual(zweimal, einmal)
        self.assertEqual(ersetzt, 0)
        self.assertEqual(uebersprungen, 0)

    def test_anfuehrungszeichen_im_ausdruck_bleiben_gueltig(self):
        """Der Ausdruck landet in einem Attributwert. Enthält er einfache
        Anführungszeichen, wird doppelt gequotet; enthält er doppelte, wird
        einfach gequotet; enthält er beide, werden die doppelten maskiert."""
        self.assertEqual(
            self.migration._convert("<p>{{ object.get('a') }}</p>")[0],
            '<p><t t-out="object.get(\'a\')"/></p>',
        )
        self.assertEqual(
            self.migration._convert('<p>{{ object.get("a") }}</p>')[0],
            '<p><t t-out=\'object.get("a")\'/></p>',
        )
        self.assertIn('&quot;', self.migration._convert(
            '<p>{{ a.get("x", \'y\') }}</p>')[0])

    # ── Halbgeviertstrich der Zeitraumzeile ─────────────────────────────────
    def test_zeitraumstrich_wird_getauscht(self):
        """Der ausgelieferte Zeitraum-Halbgeviertstrich wird zu „bis". Ohne
        diesen Nachzug stünde in der Eingangsbestätigung auf Demo und Produktion
        weiterhin ein Strich, den die Projektregel in kundensichtbarem Text
        verbietet."""
        quelle = ('<td><t t-out="object.measure_start"/> – '
                  '<t t-out="object.measure_end"/></td>')
        neu, ersetzt = self.migration._ersetze_zeitraum_strich(quelle)
        self.assertEqual(ersetzt, 1)
        self.assertNotIn('–', neu)
        self.assertIn('<t t-out="object.measure_start"/> bis '
                      '<t t-out="object.measure_end"/>', neu)

    def test_zeitraumstrich_zweiter_lauf_aendert_nichts(self):
        """Idempotenz: nach dem Tausch enthält der Rumpf die alte Zeichenkette
        nicht mehr, ein zweiter Durchgang fasst nichts an."""
        einmal = self.migration._ersetze_zeitraum_strich(
            '<p><t t-out="object.measure_start"/> – '
            '<t t-out="object.measure_end"/></p>')[0]
        zweimal, ersetzt = self.migration._ersetze_zeitraum_strich(einmal)
        self.assertEqual(zweimal, einmal)
        self.assertEqual(ersetzt, 0)

    def test_gepflegter_text_bleibt_unangetastet(self):
        """Hat die Geschäftsstelle den Satz umformuliert, passt der
        Exakt-Vergleich nicht mehr - dann wird NICHTS geschrieben. Ein
        Suchen-und-Ersetzen auf „–" allein würde fremde Formulierungen
        verändern."""
        gepflegt = '<p>Vom <t t-out="object.measure_start"/> – bis Ende</p>'
        neu, ersetzt = self.migration._ersetze_zeitraum_strich(gepflegt)
        self.assertEqual(neu, gepflegt)
        self.assertEqual(ersetzt, 0)

    def test_alter_platzhalterstand_wird_nach_dem_umbau_erreicht(self):
        """Zusammenspiel der beiden Schritte: Eine Instanz aus der Zeit vor
        19.0.15.3.0 hat den Zeitraum noch als ``{{ … }}`` gespeichert. Erst der
        Umbau erzeugt die Zeichenkette, auf die der Strich-Tausch passt - daher
        die Reihenfolge in ``migrate``."""
        alt = '<td>{{ object.measure_start }} – {{ object.measure_end }}</td>'
        umgebaut = self.migration._convert(alt)[0]
        neu, ersetzt = self.migration._ersetze_zeitraum_strich(umgebaut)
        self.assertEqual(ersetzt, 1)
        self.assertNotIn('–', neu)

    def test_ausgelieferte_vorlagen_haben_keinen_halbgeviertstrich(self):
        """Gegenprobe an den ausgelieferten Vorlagen: im Rumpf darf kein
        Halbgeviertstrich mehr stehen, sonst liefe die Neuinstallation der
        Bestandsinstanz davon."""
        for vorlage in self._ausgelieferte_vorlagen():
            self.assertNotIn(
                '–', str(vorlage.body_html or ''),
                'Vorlage "%s" hat wieder einen Halbgeviertstrich im Rumpf.'
                % vorlage.name,
            )

    def _ausgelieferte_vorlagen(self):
        xmlids = self.env['ir.model.data'].search([
            ('module', '=', 'kjr_grant'), ('model', '=', 'mail.template'),
        ])
        vorlagen = self.env['mail.template'].browse(xmlids.mapped('res_id')).exists()
        self.assertTrue(vorlagen, 'Es sind keine Mailvorlagen ausgeliefert.')
        return vorlagen

    def test_ausgelieferte_vorlagen_haben_keine_platzhalter_im_rumpf(self):
        """Gegenprobe an den ausgelieferten Vorlagen: im Rumpf darf kein ``{{``
        mehr stehen. In Betreff, Absender und Empfänger ist es dagegen richtig,
        denn die laufen über die Engine inline_template."""
        for vorlage in self._ausgelieferte_vorlagen():
            self.assertNotIn(
                '{{', str(vorlage.body_html or ''),
                'Vorlage "%s" hat wieder einen Platzhalter im Rumpf.' % vorlage.name,
            )
