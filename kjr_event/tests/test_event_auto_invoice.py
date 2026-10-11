# -*- coding: utf-8 -*-
"""E1: Automatische Schulungsrechnung bei Bestätigung einer Anmeldung.

Fachliche Leitplanken, die hier als ausführbare Zusicherung festgeschrieben
werden:

* Eine kostenlose Veranstaltung erzeugt NIE eine Rechnung.
* Eine kostenpflichtige Veranstaltung mit eingeschaltetem Schalter erzeugt
  GENAU EINE Rechnung je Anmeldung.
* Ein zweiter Statuswechsel erzeugt keine zweite Rechnung (Idempotenz) - das
  Projekt hatte an anderer Stelle schon einen Doppelversand.
* Ist der Schalter aus, passiert nichts. Gleiches gilt für einen Produktpreis
  von 0 und für den Entwurfsstatus.
* Schlägt die Rechnungserzeugung fehl, bleibt die ANMELDUNG bestehen; der
  Fehler landet als Notiz im Chatter.
* Erzeugt wird automatisch, GEBUCHT und VERSENDET wird weiterhin nur bewusst
  von Hand - auch dann, wenn die Instanz ``kjr_event.invoice_auto_post`` bzw.
  ``kjr_event.invoice_auto_send`` fuer die Sammelaktion eingeschaltet hat.

Die meisten Fälle prüfen auf der Auslöser-Ebene mit einem Platzhalter
(``unittest.mock.patch.object``) statt mit einer echten Rechnung. Grund: die
Rechnungserzeugung braucht einen Kontenplan, der im Test-Mandanten nicht
garantiert vorhanden ist. Hier wird die AUSLÖSELOGIK geprüft, also genau das,
was dieses Modul beiträgt. Ein zusätzlicher Integrationstest am Ende erzeugt
eine echte Rechnung und überspringt sich selbst, wenn kein Verkaufsjournal
vorhanden ist (gleiches Vorgehen wie kjr_rental/tests/test_pricing.py).
"""
from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestKjrEventAutoInvoice(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Event = cls.env['event.event']
        cls.Registration = cls.env['event.registration']
        cls.partner = cls.env['res.partner'].create({'name': 'Zahlende Person'})
        cls.product = cls.env['product.product'].create({
            'name': 'Juleica-Schulung (Test)',
            'list_price': 80.0,
            'type': 'service',
        })
        cls.free_product = cls.env['product.product'].create({
            'name': 'Schulung ohne Preis (Test)',
            'list_price': 0.0,
            'type': 'service',
        })

    # ------------------------------------------------------------------
    # Hilfsmittel
    # ------------------------------------------------------------------
    @classmethod
    def _make_event(cls, payment_required=True, auto_invoice=True, product=None,
                    name='Juleica-Schulung (Automatik-Test)'):
        vals = {
            'name': name,
            'is_kjr': True,
            'date_begin': '2026-11-02 09:00:00',
            'date_end': '2026-11-04 17:00:00',
            'kjr_event_type': 'juleica_course',
            'payment_required': payment_required,
            'kjr_auto_invoice': auto_invoice,
        }
        if product is not None:
            vals['training_product_id'] = product.id
        # Automatische Bestaetigung ausschalten, SOFERN die Odoo-Edition das Feld
        # fuehrt (gleiches Vorgehen wie bei 'seats_limited' in den
        # Wartelistentests). Sonst stuende eine neue Anmeldung je nach
        # Konfiguration sofort auf 'bestaetigt' und die Tests zum Entwurf und zum
        # Uebergang wuerden nichts mehr pruefen.
        if 'auto_confirm' in cls.Event._fields:
            vals['auto_confirm'] = False
        return cls.Event.create(vals)

    def _reg(self, event, state='draft', **kw):
        vals = {
            'event_id': event.id,
            'name': 'Teilnehmer',
            'email': 'teilnehmer@example.com',
            'partner_id': self.partner.id,
            'state': state,
        }
        vals.update(kw)
        reg = self.Registration.create(vals)
        if state == 'draft' and reg.state != 'draft':
            # Sicherheitsnetz: hat die Instanz die Anmeldung doch bestaetigt,
            # wird hier auf den gewollten Ausgangszustand zurueckgesetzt. Das
            # geschieht ausserhalb jedes Platzhalters und zaehlt deshalb nicht
            # als Aufruf.
            reg.write({'state': 'draft'})
        return reg

    def _patched_core(self, side_effect=None):
        """Platzhalter für den Rechnungskern; zählt die Aufrufe.

        Gepatcht wird auf dem Modell (``type(recordset)``), weil Odoo-Methoden
        am Recordset-Typ hängen und nicht an der Python-Klasse der Datei.
        """
        return patch.object(
            type(self.Registration), '_kjr_create_training_invoices',
            autospec=True,
            side_effect=side_effect if side_effect else (
                lambda self, allow_send=True, allow_post=True: (
                    self.env['account.move'], {})),
        )

    # ------------------------------------------------------------------
    # Kein Auslöser
    # ------------------------------------------------------------------
    def test_free_event_never_invoices(self):
        """Kostenlose Veranstaltung: Bestätigen erzeugt keine Rechnung."""
        event = self._make_event(payment_required=False, product=self.product)
        reg = self._reg(event)
        with self._patched_core() as core:
            reg.write({'state': 'open'})
        self.assertEqual(core.call_count, 0,
                         'Ohne Zahlungspflicht darf keine Rechnung entstehen.')

    def test_switch_off_never_invoices(self):
        """Schalter aus: Bestätigen erzeugt keine Rechnung."""
        event = self._make_event(auto_invoice=False, product=self.product)
        reg = self._reg(event)
        with self._patched_core() as core:
            reg.write({'state': 'open'})
        self.assertEqual(core.call_count, 0,
                         'Bei ausgeschaltetem Schalter darf nichts passieren.')

    def test_price_zero_never_invoices(self):
        """Produktpreis 0: keine Rechnung über 0,00 Euro."""
        event = self._make_event(product=self.free_product)
        reg = self._reg(event)
        with self._patched_core() as core:
            reg.write({'state': 'open'})
        self.assertEqual(core.call_count, 0,
                         'Ein Betrag von 0 darf keine Rechnung auslösen.')

    def test_without_product_never_invoices(self):
        """Ohne hinterlegtes Schulungsprodukt passiert nichts."""
        event = self._make_event(product=None)
        reg = self._reg(event)
        with self._patched_core() as core:
            reg.write({'state': 'open'})
        self.assertEqual(core.call_count, 0,
                         'Ohne Schulungsprodukt gibt es keinen Rechnungsbetrag.')

    def test_draft_never_invoices(self):
        """Der Entwurf löst nichts aus, auch nicht beim Anlegen."""
        event = self._make_event(product=self.product)
        with self._patched_core() as core:
            self._reg(event, state='draft')
        self.assertEqual(core.call_count, 0,
                         'Nur der Wechsel nach bestätigt/teilgenommen löst aus.')

    def test_waitlist_never_invoices(self):
        """Ein Wartelistenplatz wird nicht fakturiert."""
        event = self._make_event(product=self.product)
        reg = self._reg(event, kjr_is_waitlist=True)
        with self._patched_core() as core:
            # Status und Wartelistenmerker gemeinsam schreiben, sonst räumt die
            # Wartelistenlogik in write() den Merker ab.
            reg.write({'state': 'open', 'kjr_is_waitlist': True})
        self.assertEqual(core.call_count, 0,
                         'Wartelistenplätze belegen keinen Platz und werden nicht fakturiert.')

    # ------------------------------------------------------------------
    # Auslöser
    # ------------------------------------------------------------------
    def test_confirm_invoices_exactly_once(self):
        """Kostenpflichtig, Schalter an: genau EIN Aufruf des Rechnungskerns."""
        event = self._make_event(product=self.product)
        reg = self._reg(event)
        with self._patched_core() as core:
            reg.write({'state': 'open'})
        self.assertEqual(core.call_count, 1)

    def test_created_confirmed_invoices_once(self):
        """Direkt bestätigt angelegt (Website/Auto-Bestätigung): ein Aufruf."""
        event = self._make_event(product=self.product)
        with self._patched_core() as core:
            self._reg(event, state='open')
        self.assertEqual(core.call_count, 1)

    def test_automatic_path_never_sends_and_never_posts(self):
        """Der Automatikpfad ruft den Kern mit allow_send=False UND allow_post=False.

        Erzeugen, Buchen und Versenden bleiben getrennt: wer
        ``kjr_event.invoice_auto_send`` oder ``kjr_event.invoice_auto_post`` fuer
        die Sammelaktion eingeschaltet hat, soll durch die neue Automatik weder
        Rechnungsmails bekommen, die er nie beauftragt hat, noch gebuchte
        Rechnungen, die nur noch per Gutschrift zurueckzudrehen sind.
        """
        event = self._make_event(product=self.product)
        reg = self._reg(event)
        with self._patched_core() as core:
            reg.write({'state': 'open'})
        self.assertEqual(core.call_count, 1)
        _args, kwargs = core.call_args
        self.assertFalse(kwargs.get('allow_send', True),
                         'Der Automatikpfad darf den Versand nicht erlauben.')
        self.assertFalse(kwargs.get('allow_post', True),
                         'Der Automatikpfad darf das Buchen nicht erlauben.')

    # ------------------------------------------------------------------
    # Idempotenz
    # ------------------------------------------------------------------
    def test_second_state_change_invoices_nothing(self):
        """Zweiter Statuswechsel (open -> done): kein weiterer Aufruf."""
        event = self._make_event(product=self.product)
        reg = self._reg(event)
        with self._patched_core() as core:
            reg.write({'state': 'open'})
            self.assertEqual(core.call_count, 1)
            reg.write({'state': 'done'})
            self.assertEqual(
                core.call_count, 1,
                'Der Wechsel von bestätigt nach teilgenommen ist kein neuer Übergang.')

    def test_rewriting_same_state_invoices_nothing(self):
        """Derselbe Status noch einmal geschrieben: kein weiterer Aufruf."""
        event = self._make_event(product=self.product)
        reg = self._reg(event)
        with self._patched_core() as core:
            reg.write({'state': 'open'})
            reg.write({'state': 'open'})
            self.assertEqual(core.call_count, 1)

    def test_existing_invoice_blocks_second_one(self):
        """Mit gesetzter Rechnung fällt die Anmeldung aus den Kandidaten."""
        journal = self.env['account.journal'].search([
            ('type', '=', 'sale'), ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not journal:
            self.skipTest('Kein Verkaufsjournal im Test-Mandanten '
                          '(kein Kontenplan installiert), Rechnung nicht anlegbar.')
        event = self._make_event(product=self.product)
        reg = self._reg(event)
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'journal_id': journal.id,
        })
        reg.sudo().write({'kjr_training_invoice_id': move.id})
        self.assertFalse(
            reg._kjr_auto_invoice_candidates(),
            'Eine bereits fakturierte Anmeldung darf nie erneut Kandidat sein.')
        with self._patched_core() as core:
            reg.write({'state': 'open'})
        self.assertEqual(core.call_count, 0)

    # ------------------------------------------------------------------
    # Robustheit
    # ------------------------------------------------------------------
    def test_failure_keeps_registration(self):
        """Scheitert die Rechnung, bleibt die Anmeldung bestehen und bestätigt."""
        event = self._make_event(product=self.product)
        reg = self._reg(event)

        def boom(self, allow_send=True, allow_post=True):
            raise ValueError('Testfehler')

        with self._patched_core(side_effect=boom):
            reg.write({'state': 'open'})

        self.assertTrue(reg.exists(), 'Die Anmeldung darf nicht verloren gehen.')
        self.assertEqual(reg.state, 'open', 'Die Bestätigung muss bestehen bleiben.')
        self.assertFalse(reg.kjr_training_invoice_id,
                         'Ohne erfolgreiche Erzeugung darf keine Rechnung verknüpft sein.')
        bodies = ' '.join(reg.message_ids.mapped('body'))
        self.assertIn('nicht automatisch erzeugt', bodies,
                      'Der Fehler gehört als Notiz in den Chatter.')

    # ------------------------------------------------------------------
    # Integration (echte Rechnung)
    # ------------------------------------------------------------------
    def test_real_invoice_is_a_draft_without_mail(self):
        """Ende zu Ende: genau eine Rechnung, im Entwurf, ohne Anmeldebestätigung."""
        journal = self.env['account.journal'].search([
            ('type', '=', 'sale'), ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not journal:
            self.skipTest('Kein Verkaufsjournal im Test-Mandanten '
                          '(kein Kontenplan installiert), Rechnungsfall nicht prüfbar.')
        event = self._make_event(product=self.product)
        reg = self._reg(event)
        mails_before = self.env['mail.mail'].search_count([])

        reg.write({'state': 'open'})

        self.assertTrue(reg.kjr_training_invoice_id,
                        'Die Rechnung muss mit der Anmeldung verknüpft sein.')
        move = reg.kjr_training_invoice_id
        self.assertEqual(move.state, 'draft',
                         'Ohne kjr_event.invoice_auto_post bleibt die Rechnung Entwurf.')
        self.assertEqual(move.move_type, 'out_invoice')
        self.assertEqual(
            self.env['account.move'].search_count([
                ('id', 'in', move.ids),
            ]), 1)
        self.assertEqual(
            self.env['mail.mail'].search_count([]), mails_before,
            'Die automatische Rechnung darf keine Anmeldebestätigung auslösen.')

        # Zweiter Statuswechsel erzeugt keine zweite Rechnung.
        reg.write({'state': 'done'})
        self.assertEqual(reg.kjr_training_invoice_id, move)

    def test_auto_post_parameter_does_not_post_on_the_automatic_path(self):
        """Mit kjr_event.invoice_auto_post='1' bleibt die AUTOMATISCHE Rechnung Entwurf.

        Der Parameter gehoert zur von Hand ausgeloesten Sammelaktion. Auf dem
        Automatikpfad wuerde er aus jeder bestaetigten Anmeldung eine gebuchte,
        nummerierte Rechnung machen: nicht mehr loeschbar, nur noch per
        Gutschrift zurueckzudrehen und mit einer verbrauchten Nummer der
        Rechnungssequenz. Zugesagt ist an vier Stellen des Moduls ein Entwurf.
        """
        journal = self.env['account.journal'].search([
            ('type', '=', 'sale'), ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not journal:
            self.skipTest('Kein Verkaufsjournal im Test-Mandanten '
                          '(kein Kontenplan installiert), Rechnungsfall nicht pruefbar.')
        param = self.env['ir.config_parameter'].sudo()
        before = param.get_param('kjr_event.invoice_auto_post')
        param.set_param('kjr_event.invoice_auto_post', '1')
        self.addCleanup(param.set_param, 'kjr_event.invoice_auto_post', before or '0')

        event = self._make_event(product=self.product)
        reg = self._reg(event)
        reg.write({'state': 'open'})

        self.assertTrue(reg.kjr_training_invoice_id,
                        'Die Rechnung muss trotzdem erzeugt werden.')
        self.assertEqual(
            reg.kjr_training_invoice_id.state, 'draft',
            'Der Automatikpfad darf die Rechnung nicht buchen, auch nicht mit '
            'eingeschaltetem kjr_event.invoice_auto_post.')

    def test_automatic_path_runs_with_system_rights_and_event_company(self):
        """Der Automatikpfad erzeugt die Rechnung mit Systemrechten.

        Ausgelöst wird ``_kjr_auto_invoice`` auch dort, wo der auslösende
        Benutzer auf ``account.move`` kein Schreibrecht hat: über die Website
        und im Backend durch eine Sachbearbeitung ohne Buchhaltungsrechte.
        Ohne ``sudo()`` scheitert ``account.move.create`` mit ``AccessError``,
        der Fehlerzweig fängt ihn ab, die Anmeldung bleibt bestehen - und es
        entsteht STILL KEINE Rechnung. Genau dieser stille Ausfall wird hier
        festgeschrieben.

        Geprüft wird am übergebenen Recordset statt über echte Rechte: der
        Rechnungskern muss ein ``sudo``-Recordset bekommen, und die Firma muss
        aus der VERANSTALTUNG kommen, nicht aus dem Benutzer, damit die
        Rechnung nicht in der falschen Firma landet.
        """
        gesehen = {}

        def _merker(self, allow_send=True, allow_post=True):
            gesehen['su'] = self.env.su
            gesehen['company'] = self.env.company
            return self.env['account.move'], {}

        event = self._make_event(product=self.product)
        reg = self._reg(event)
        with self._patched_core(side_effect=_merker):
            reg.write({'state': 'open'})

        self.assertTrue(
            gesehen.get('su'),
            'Die Rechnungserzeugung muss mit Systemrechten laufen (sudo), sonst '
            'entsteht auf dem Website-Pfad still keine Rechnung.')
        self.assertEqual(
            gesehen.get('company'),
            event.company_id or reg.company_id or self.env.company,
            'Die Rechnung muss in der Firma der Veranstaltung entstehen, nicht in '
            'der des auslösenden Benutzers.')
