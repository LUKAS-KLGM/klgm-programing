# -*- coding: utf-8 -*-
"""Tests des Aktivitäten-Popups (Server-API und Merker)."""
from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, freeze_time, new_test_user
from odoo.tools import SQL


@tagged('post_install', '-at_install')
class TestKjrActivityPopup(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ctx = {'mail_activity_quick_update': True, 'mail_create_nolog': True,
               'mail_notrack': True, 'no_reset_password': True}
        cls.env = cls.env(context=dict(cls.env.context, **ctx))
        # Kontakte-Schreibrecht: Wer eine Aktivität an einem Kontakt anlegt,
        # braucht Schreibrecht auf res.partner (_mail_post_access = 'write').
        cls.user = new_test_user(
            cls.env, login='kjr_popup_user',
            groups='base.group_user,base.group_partner_manager', tz='UTC')
        cls.other_user = new_test_user(
            cls.env, login='kjr_popup_other', groups='base.group_user', tz='UTC')
        cls.partner = cls.env['res.partner'].create({'name': 'Testverein Popup'})
        cls.todo = cls.env.ref('mail.mail_activity_data_todo')
        cls.upload = cls.env.ref('mail.mail_activity_data_upload_document')
        cls.Mark = cls.env['kjr.activity.popup.mark'].sudo()
        cls.ICP = cls.env['ir.config_parameter'].sudo()

    # ------------------------------------------------------------------
    # Hilfen
    # ------------------------------------------------------------------
    def _activity(self, deadline, user=None, summary='Rückruf', activity_type=None, **vals):
        return self.env['mail.activity'].create({
            'res_model_id': self.env['ir.model']._get_id('res.partner'),
            'res_id': self.partner.id,
            'activity_type_id': (activity_type or self.todo).id,
            'user_id': (user or self.user).id,
            'date_deadline': deadline,
            'summary': summary,
            **vals,
        })

    def _api(self, user=None):
        user = user or self.user
        # wie im Webclient: Zeitzone des Benutzers im Kontext
        return self.env['mail.activity'].with_user(user).with_context(tz=user.tz)

    def _fetch(self, user=None):
        return self._api(user).kjr_popup_fetch()

    def _ids(self, result, kind='activity'):
        return [i['id'] for i in result['items'] if i['kind'] == kind]

    def _today(self):
        return fields.Date.context_today(self._api())

    # ------------------------------------------------------------------
    # Auswahl
    # ------------------------------------------------------------------
    def test_fetch_due_and_overdue_only(self):
        """Nur eigene, heute fällige oder überfällige, aktive Aktivitäten."""
        today = self._today()
        overdue = self._activity(today - timedelta(days=3), summary='Überfällig')
        due_today = self._activity(today, summary='Heute')
        self._activity(today + timedelta(days=2), summary='Später')
        self._activity(today, user=self.other_user, summary='Fremd')
        archived = self._activity(today, summary='Archiviert')
        archived.active = False

        result = self._fetch()
        self.assertTrue(result['enabled'])
        self.assertEqual(self._ids(result), [overdue.id, due_today.id],
                         'älteste Frist zuerst, keine fremden/künftigen/archivierten')
        first, second = result['items']
        self.assertEqual(first['state'], 'overdue')
        self.assertEqual(first['days_overdue'], 3)
        self.assertEqual(first['title'], 'Überfällig')
        self.assertEqual(first['record_name'], self.partner.display_name)
        self.assertTrue(first['can_done'])
        self.assertEqual(second['state'], 'today')
        self.assertEqual(second['days_overdue'], 0)
        self.assertEqual(result['more'], 0)

    def test_own_new_activity_not_popped_immediately(self):
        """Eine gerade selbst angelegte Aktivität poppt nicht sofort auf,
        sondern erst nach der Schonfrist."""
        act = self.env['mail.activity'].with_user(self.user).create({
            'res_model_id': self.env['ir.model']._get_id('res.partner'),
            'res_id': self.partner.id,
            'activity_type_id': self.todo.id,
            'user_id': self.user.id,
            'date_deadline': self._today(),
            'summary': 'Selbst angelegt',
        })
        self.assertEqual(self._fetch()['items'], [])
        self.assertFalse(self.Mark.search([('user_id', '=', self.user.id)]),
                         'nicht angezeigt -> kein Merker')
        act.flush_recordset()
        self.env.cr.execute(SQL(
            "UPDATE mail_activity SET create_date = create_date - interval '1 hour' WHERE id = %s",
            act.id))
        act.invalidate_recordset(['create_date'])
        self.assertEqual(self._ids(self._fetch()), [act.id])

    def test_note_excerpt_is_plain_text(self):
        """Die Notiz kommt als gekürzter Klartext (kein HTML) ins Popup."""
        today = self._today()
        act = self._activity(today, note='<p>Bitte <b>Unterlagen</b></p><p>prüfen</p>')
        item = self._fetch()['items'][0]
        self.assertEqual(item['id'], act.id)
        self.assertNotIn('<', item['note'])
        self.assertIn('Unterlagen', item['note'])
        self.assertIn('prüfen', item['note'])

    def test_settings_defaults_and_bounds(self):
        """Intervall/Zurückstellen aus Systemparametern, mit Grenzen."""
        result = self._fetch()
        self.assertEqual(result['poll_minutes'], 10)
        self.assertEqual(result['snooze_minutes'], 60)
        self.ICP.set_param('kjr_activity_popup.poll_minutes', '0')
        self.ICP.set_param('kjr_activity_popup.snooze_minutes', 'abc')
        result = self._fetch()
        self.assertEqual(result['poll_minutes'], 1)
        self.assertEqual(result['snooze_minutes'], 60)

    # ------------------------------------------------------------------
    # Einmal pro Tag / Später erinnern
    # ------------------------------------------------------------------
    def test_once_per_day(self):
        """Ein Eintrag erscheint am selben Tag nur einmal, am Folgetag wieder."""
        act = self._activity(self._today())
        self.assertEqual(self._ids(self._fetch()), [act.id])
        self.assertEqual(self._fetch()['items'], [], 'zweiter Abruf am selben Tag: nichts')

        mark = self.Mark.search([('user_id', '=', self.user.id),
                                 ('res_model', '=', 'mail.activity'),
                                 ('res_id', '=', act.id)])
        self.assertEqual(len(mark), 1)
        self.assertEqual(mark.shown_date, self._today())
        mark.shown_date = self._today() - timedelta(days=1)
        self.assertEqual(self._ids(self._fetch()), [act.id], 'neuer Tag: wieder anzeigen')

    def test_marks_are_per_user(self):
        """Wird die Aktivität neu zugewiesen, sieht der neue Benutzer sie am selben Tag."""
        act = self._activity(self._today())
        self.assertEqual(self._ids(self._fetch()), [act.id])
        act.user_id = self.other_user
        self.assertEqual(self._ids(self._fetch(self.other_user)), [act.id])
        self.assertEqual(self._fetch()['items'], [])

    def test_snooze(self):
        """„Später erinnern“: vor Ablauf nichts, danach am selben Tag erneut."""
        act = self._activity(self._today())
        self._fetch()
        self._api().kjr_popup_snooze([['activity', act.id]])
        mark = self.Mark.search([('user_id', '=', self.user.id), ('res_id', '=', act.id),
                                 ('res_model', '=', 'mail.activity')])
        self.assertTrue(mark.snooze_until)
        delta = mark.snooze_until - fields.Datetime.now()
        self.assertTrue(timedelta(minutes=55) < delta <= timedelta(minutes=60))

        # auch an einem neuen Tag bleibt der Eintrag bis zum Ablauf zurückgestellt
        mark.shown_date = self._today() - timedelta(days=1)
        self.assertEqual(self._fetch()['items'], [])

        mark.snooze_until = fields.Datetime.now() - timedelta(minutes=1)
        self.assertEqual(self._ids(self._fetch()), [act.id], 'Zurückstellung abgelaufen')
        mark.invalidate_recordset()
        self.assertFalse(mark.snooze_until, 'Anzeige hebt die Zurückstellung auf')
        self.assertEqual(self._fetch()['items'], [])

    def test_snooze_without_previous_fetch_and_custom_minutes(self):
        """Zurückstellen legt den Merker auch ohne vorherige Anzeige an."""
        self.ICP.set_param('kjr_activity_popup.snooze_minutes', '15')
        act = self._activity(self._today())
        self._api().kjr_popup_snooze([['activity', act.id]])
        mark = self.Mark.search([('user_id', '=', self.user.id), ('res_id', '=', act.id),
                                 ('res_model', '=', 'mail.activity')])
        self.assertTrue(mark.snooze_until <= fields.Datetime.now() + timedelta(minutes=15))
        self.assertEqual(self._fetch()['items'], [])

    def test_snooze_only_own_entries_and_limited(self):
        """Zurückstellen: fremde/erfundene Einträge werden übergangen, Portal-
        Benutzer abgewiesen, mehr als ein Popup fasst wird abgelehnt."""
        own = self._activity(self._today())
        foreign = self._activity(self._today(), user=self.other_user)
        self._api().kjr_popup_snooze(
            [['activity', own.id], ['activity', foreign.id], ['activity', 999999999]])
        marks = self.Mark.search([('user_id', '=', self.user.id)])
        self.assertEqual(marks.mapped('res_id'), [own.id])
        self.assertTrue(marks.snooze_until)

        portal = new_test_user(self.env, login='kjr_popup_portal_snooze',
                               groups='base.group_portal')
        with self.assertRaises(AccessError):
            self._api(portal).kjr_popup_snooze([['activity', own.id]])
        self.assertFalse(self.Mark.search([('user_id', '=', portal.id)]))

        with self.assertRaises(UserError):
            self._api().kjr_popup_snooze([['activity', i] for i in range(1, 22)])

    def test_max_items_and_more(self):
        """Höchstens 20 Einträge je Popup, der Rest folgt beim nächsten Abruf."""
        today = self._today()
        acts = self.env['mail.activity']
        for i in range(25):
            acts |= self._activity(today - timedelta(days=i % 5), summary='A%s' % i)
        first = self._fetch()
        self.assertEqual(len(first['items']), 20)
        self.assertEqual(first['more'], 5)
        second = self._fetch()
        self.assertEqual(len(second['items']), 5)
        self.assertEqual(second['more'], 0)
        self.assertEqual(set(self._ids(first)) | set(self._ids(second)), set(acts.ids))

    @freeze_time('2026-10-12 12:00:00')
    def test_day_in_user_timezone(self):
        """„Heute“ richtet sich nach der Zeitzone des Benutzers."""
        act = self._activity(date(2026, 10, 13))
        self.user.tz = 'UTC'
        self.assertEqual(self._fetch()['items'], [], 'in UTC erst morgen fällig')
        self.user.tz = 'Pacific/Kiritimati'  # UTC+14: dort ist bereits der 13.10.
        result = self._fetch()
        self.assertEqual(self._ids(result), [act.id])
        self.assertEqual(result['items'][0]['state'], 'today')

    # ------------------------------------------------------------------
    # Präferenz / Benutzerkreis
    # ------------------------------------------------------------------
    def test_preference_disabled(self):
        """Abgeschaltet: keine Einträge und kein Merker."""
        self._activity(self._today())
        self.assertTrue(self.user.kjr_activity_popup_enabled, 'Standard: eingeschaltet')
        self.user.with_user(self.user).write({'kjr_activity_popup_enabled': False})
        result = self._fetch()
        self.assertFalse(result['enabled'])
        self.assertEqual(result['items'], [])
        self.assertFalse(self.Mark.search([('user_id', '=', self.user.id)]))

    def test_preference_self_readable(self):
        """Die Präferenz ist für den Benutzer selbst lesbar (Einstellungen)."""
        values = self.user.with_user(self.user).read(['kjr_activity_popup_enabled'])
        self.assertTrue(values[0]['kjr_activity_popup_enabled'])

    def test_portal_user_gets_nothing(self):
        """Portal-Benutzer bekommen kein Popup."""
        portal = new_test_user(self.env, login='kjr_popup_portal', groups='base.group_portal')
        result = self._fetch(portal)
        self.assertFalse(result['enabled'])
        self.assertEqual(result['items'], [])

    # ------------------------------------------------------------------
    # Knöpfe
    # ------------------------------------------------------------------
    def test_done(self):
        """„Erledigt“ schließt die Aktivität wie die Aktivitäten-Leiste."""
        act = self._activity(self._today())
        self.assertTrue(self._api().kjr_popup_done('activity', act.id))
        remaining = self.env['mail.activity'].with_context(active_test=False).search(
            [('id', '=', act.id)])
        self.assertTrue(not remaining or not remaining.active)
        self.assertEqual(self._fetch()['items'], [])

    def test_done_upload_activity_refused(self):
        """Dokument-Aktivitäten lassen sich nicht ohne Upload erledigen."""
        act = self._activity(self._today(), activity_type=self.upload)
        item = self._fetch()['items'][0]
        self.assertFalse(item['can_done'])
        self.assertEqual(item['icon'], 'fa-upload')
        with self.assertRaises(UserError):
            self._api().kjr_popup_done('activity', act.id)
        self.assertTrue(act.exists() and act.active)

    def test_foreign_activity_refused(self):
        """Fremde Aktivitäten lassen sich über das Popup weder erledigen noch öffnen."""
        act = self._activity(self._today(), user=self.other_user)
        with self.assertRaises(AccessError):
            self._api().kjr_popup_done('activity', act.id)
        with self.assertRaises(AccessError):
            self._api().kjr_popup_open('activity', act.id)
        self.assertTrue(act.active)

    def test_invalid_entries_refused(self):
        """Unbekannte Arten und ungültige IDs werden abgewiesen."""
        with self.assertRaises(UserError):
            self._api().kjr_popup_done('res.users', 1)
        with self.assertRaises(UserError):
            self._api().kjr_popup_snooze([['activity', 'x']])
        with self.assertRaises(UserError):
            self._api().kjr_popup_open('activity', 999999999)

    def test_open_returns_document_action(self):
        """„Öffnen“ liefert die Aktion zum Datensatz der Aktivität."""
        act = self._activity(self._today())
        action = self._api().kjr_popup_open('activity', act.id)
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'res.partner')
        self.assertEqual(action['res_id'], self.partner.id)

    # ------------------------------------------------------------------
    # Aufräumen / Assets
    # ------------------------------------------------------------------
    def test_autovacuum_removes_old_marks(self):
        """Alte, nicht mehr zurückgestellte Merker werden gelöscht."""
        today = fields.Date.today()
        old = self.Mark.create({'user_id': self.user.id, 'res_model': 'mail.activity',
                                'res_id': 1, 'shown_date': today - timedelta(days=30)})
        snoozed = self.Mark.create({
            'user_id': self.user.id, 'res_model': 'mail.activity', 'res_id': 2,
            'shown_date': today - timedelta(days=30),
            'snooze_until': fields.Datetime.now() + timedelta(hours=1)})
        recent = self.Mark.create({'user_id': self.user.id, 'res_model': 'mail.activity',
                                   'res_id': 3, 'shown_date': today})
        self.Mark._gc_old_marks()
        self.assertFalse(old.exists())
        self.assertTrue(snoozed.exists())
        self.assertTrue(recent.exists())

    def test_backend_assets_registered(self):
        """Service, Dialog und Stile hängen im Backend-Bundle."""
        paths = [asset[0] for asset in
                 self.env['ir.asset']._get_asset_paths('web.assets_backend', {})]
        for name in ('activity_popup_service.js', 'activity_popup_dialog.js',
                     'activity_popup_dialog.xml', 'activity_popup.scss'):
            self.assertTrue(
                any(p.endswith('kjr_activity_popup/static/src/' + name) for p in paths),
                name)


@tagged('post_install', '-at_install')
class TestKjrActivityPopupTasks(TransactionCase):
    """Aufgaben-Fristen – nur, wenn die App Projekt installiert ist."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'project.task' not in cls.env:
            return
        ctx = {'mail_create_nolog': True, 'mail_notrack': True,
               'mail_activity_quick_update': True, 'no_reset_password': True}
        cls.env = cls.env(context=dict(cls.env.context, **ctx))
        cls.user = new_test_user(
            cls.env, login='kjr_popup_task_user',
            groups='base.group_user,project.group_project_user', tz='UTC')
        # nur interner Benutzer, ohne Projekt-Gruppe: darf zugewiesene
        # Aufgaben lesen, aber nicht ändern
        cls.employee = new_test_user(
            cls.env, login='kjr_popup_task_employee', groups='base.group_user', tz='UTC')
        cls.project = cls.env['project.project'].create({'name': 'Popup-Projekt'})
        # Sichtbarkeit „Eingeladene interne Benutzer“: lesbar nur für Follower
        cls.private_project = cls.env['project.project'].create({
            'name': 'Geschlossenes Popup-Projekt',
            'privacy_visibility': 'followers',
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Testverein Aufgaben-Popup'})

    def setUp(self):
        super().setUp()
        if 'project.task' not in self.env:
            self.skipTest('Projekt ist nicht installiert')

    def _task(self, deadline, project=None, user=None, **vals):
        return self.env['project.task'].create({
            'name': vals.pop('name', 'Protokoll verschicken'),
            'project_id': (project or self.project).id,
            'user_ids': [(6, 0, (user or self.user).ids)],
            'date_deadline': deadline,
            **vals,
        })

    def _api(self, user=None):
        user = user or self.user
        return self.env['mail.activity'].with_user(user).with_context(tz=user.tz)

    def test_due_tasks_included(self):
        """Offene, fällige Aufgaben erscheinen; erledigte und künftige nicht."""
        now = fields.Datetime.now()
        due = self._task(now - timedelta(days=2), name='Überfällige Aufgabe')
        self._task(now + timedelta(days=3), name='Künftige Aufgabe')
        self._task(now - timedelta(days=1), name='Erledigte Aufgabe', state='1_done')
        result = self._api().kjr_popup_fetch()
        task_items = [i for i in result['items'] if i['kind'] == 'task']
        self.assertEqual([i['id'] for i in task_items], [due.id])
        self.assertEqual(task_items[0]['state'], 'overdue')
        self.assertEqual(task_items[0]['record_name'], self.project.display_name)
        self.assertEqual(self._api().kjr_popup_fetch()['items'], [], 'einmal pro Tag')

    def test_task_done_and_open(self):
        """„Erledigt“ setzt die Aufgabe auf erledigt, „Öffnen“ zeigt sie."""
        task = self._task(fields.Datetime.now() - timedelta(hours=1))
        action = self._api().kjr_popup_open('task', task.id)
        self.assertEqual((action['res_model'], action['res_id']), ('project.task', task.id))
        self._api().kjr_popup_done('task', task.id)
        self.assertEqual(task.state, '1_done')

    def test_task_of_other_user_refused(self):
        """Nicht zugewiesene Aufgaben lassen sich über das Popup nicht erledigen."""
        task = self._task(fields.Datetime.now(), user_ids=[(5, 0, 0)])
        with self.assertRaises(AccessError):
            self._api().kjr_popup_done('task', task.id)

    def test_task_in_follower_only_project(self):
        """Zugewiesene Aufgabe in einem Projekt nur für Follower, dem der
        Benutzer nicht folgt: Popup erscheint trotzdem (mit Projektname), und
        die eigenen Aktivitäten gehen nicht verloren."""
        employee = self.employee
        self.assertNotIn(employee.partner_id, self.private_project.message_partner_ids)
        self.assertFalse(self.private_project.with_user(employee).has_access('read'),
                         'Voraussetzung: Projekt für den Benutzer nicht lesbar')
        task = self._task(fields.Datetime.now() - timedelta(days=1),
                          project=self.private_project, user=employee,
                          name='Aufgabe im geschlossenen Projekt')
        activity = self.env['mail.activity'].create({
            'res_model_id': self.env['ir.model']._get_id('res.partner'),
            'res_id': self.partner.id,
            'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
            'user_id': employee.id,
            'date_deadline': fields.Date.context_today(self._api(employee)),
            'summary': 'Eigene Aktivität',
        })
        result = self._api(employee).kjr_popup_fetch()
        by_kind = {i['kind']: i for i in result['items']}
        self.assertEqual(by_kind['activity']['id'], activity.id)
        self.assertEqual(by_kind['task']['id'], task.id)
        self.assertEqual(by_kind['task']['record_name'], self.private_project.display_name)

    def test_task_done_hidden_without_write_access(self):
        """Ohne Schreibrecht auf die Aufgabe kein „Erledigt“; ein direkter
        Aufruf wird verständlich abgewiesen."""
        task = self._task(fields.Datetime.now() - timedelta(hours=2), user=self.employee)
        item = next(i for i in self._api(self.employee).kjr_popup_fetch()['items']
                    if i['kind'] == 'task')
        self.assertEqual(item['id'], task.id)
        self.assertFalse(item['can_done'])
        with self.assertRaises(UserError):
            self._api(self.employee).kjr_popup_done('task', task.id)
        self.assertNotEqual(task.state, '1_done')

        own = self._task(fields.Datetime.now() - timedelta(hours=2), name='Eigene Aufgabe')
        item = next(i for i in self._api().kjr_popup_fetch()['items']
                    if i['kind'] == 'task' and i['id'] == own.id)
        self.assertTrue(item['can_done'], 'Projekt-Benutzer darf erledigen')
