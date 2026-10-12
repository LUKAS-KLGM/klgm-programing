# -*- coding: utf-8 -*-
"""Server-API des Aktivitäten-Popups (aufgerufen vom OWL-Service
``kjr_activity_popup`` im Backend).

Berücksichtigt werden
* fällige und überfällige Aktivitäten (``mail.activity``) des angemeldeten
  Benutzers aus allen Apps – also auch Aktivitäten an Projekt-Aufgaben;
* zusätzlich, falls die App Projekt installiert ist, offene Projekt-Aufgaben
  des Benutzers, deren Frist heute erreicht oder überschritten ist.

Jeder Eintrag erscheint höchstens einmal pro Tag (Merker
``kjr.activity.popup.mark``); „Später erinnern“ stellt ihn für eine
einstellbare Zeit zurück.
"""
import logging
import re
from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import html2plaintext, is_html_empty
from odoo.tools.misc import format_date, format_datetime

ACTIVITY = 'activity'
TASK = 'task'
KIND_MODEL = {ACTIVITY: 'mail.activity', TASK: 'project.task'}
TASK_CLOSED_STATES = ('1_done', '1_canceled')

POPUP_MAX_ITEMS = 20          # so viele Einträge zeigt ein Popup höchstens
POPUP_CANDIDATE_LIMIT = 1000  # Obergrenze je Quelle für die Vorauswahl
NOTE_MAX_CHARS = 280
# Selbst angelegte Einträge nicht sofort wieder vorhalten (der Bus meldet die
# eigene neue Aktivität sonst Sekunden später als Popup).
SELF_CREATED_GRACE_MINUTES = 15

PARAM_POLL = 'kjr_activity_popup.poll_minutes'
PARAM_SNOOZE = 'kjr_activity_popup.snooze_minutes'
DEFAULT_POLL = 10
DEFAULT_SNOOZE = 60

_logger = logging.getLogger(__name__)


class MailActivity(models.Model):
    _inherit = 'mail.activity'

    # ------------------------------------------------------------------
    # Öffentliche RPC-Methoden
    # ------------------------------------------------------------------
    @api.model
    def kjr_popup_fetch(self):
        """Liefert die jetzt anzuzeigenden Einträge und beansprucht sie
        (Merker „heute angezeigt“).

        :return: ``{'enabled', 'poll_minutes', 'snooze_minutes', 'items',
                   'more'}``
        """
        settings = self._kjr_popup_settings()
        result = dict(settings, enabled=False, items=[], more=0)
        user = self.env.user
        if not user._is_internal() or not user.kjr_activity_popup_enabled:
            return result
        result['enabled'] = True

        today = fields.Date.context_today(self)
        now = fields.Datetime.now()
        candidates = self._kjr_popup_candidates(today)
        if not candidates:
            return result

        Mark = self.env['kjr.activity.popup.mark'].sudo()
        marks = Mark.search([
            ('user_id', '=', user.id),
            ('res_model', 'in', list({c['key'][0] for c in candidates})),
            ('res_id', 'in', list({c['key'][1] for c in candidates})),
        ])
        by_key = {(m.res_model, m.res_id): m for m in marks}
        eligible = [c for c in candidates
                    if Mark._kjr_is_due(by_key.get(c['key']), today, now)]
        # Darstellungsdaten VOR dem Beanspruchen bilden: Ein einzelner
        # Datensatz, den der Benutzer nicht lesen darf, wird übersprungen
        # (ohne Merker) und blockiert nicht das ganze Popup.
        chosen, items, consumed = [], {}, 0
        for candidate in eligible:
            if len(chosen) >= POPUP_MAX_ITEMS:
                break
            consumed += 1
            item = self._kjr_popup_safe_item(candidate, today)
            if item is not None:
                chosen.append(candidate)
                items[candidate['key']] = item
        claimed = Mark._kjr_claim(user, [c['key'] for c in chosen], today, now)
        result['items'] = [items[c['key']] for c in chosen if c['key'] in claimed]
        result['more'] = max(0, len(eligible) - consumed)
        return result

    @api.model
    def kjr_popup_snooze(self, entries):
        """„Später erinnern“ für ``entries`` (Liste von ``[kind, id]``,
        höchstens so viele, wie ein Popup zeigt).

        Nur für interne Benutzer und nur für Einträge, die ihnen zugewiesen
        sind; andere Schlüssel (inzwischen umverteilt, gelöscht, fremd oder
        erfunden) werden stillschweigend übergangen, damit „Alle erinnern“
        nicht an einem einzelnen Eintrag scheitert.
        """
        if not self.env.user._is_internal():
            raise AccessError(_('Erinnerungen stehen nur internen Benutzern zur Verfügung.'))
        if not isinstance(entries, (list, tuple)):
            raise UserError(_('Ungültige Erinnerung.'))
        if len(entries) > POPUP_MAX_ITEMS:
            raise UserError(_('Es lassen sich höchstens %s Einträge auf einmal zurückstellen.',
                              POPUP_MAX_ITEMS))
        try:
            pairs = [(kind, res_id) for kind, res_id in entries]
        except (TypeError, ValueError):
            raise UserError(_('Ungültige Erinnerung.')) from None
        keys = list(dict.fromkeys(self._kjr_popup_key(kind, res_id) for kind, res_id in pairs))
        keys = self._kjr_popup_assigned_keys(keys)
        if not keys:
            return True
        minutes = self._kjr_popup_settings()['snooze_minutes']
        self.env['kjr.activity.popup.mark'].sudo()._kjr_snooze(
            self.env.user, keys, minutes, fields.Datetime.now())
        return True

    @api.model
    def kjr_popup_done(self, kind, res_id):
        """Markiert einen Eintrag als erledigt – mit den normalen Rechten des
        Benutzers (wie über die Aktivitäten-Leiste bzw. die Aufgabe)."""
        record = self._kjr_popup_record(kind, res_id)
        if kind == ACTIVITY:
            if record.activity_category == 'upload_file':
                raise UserError(_(
                    'Diese Aktivität verlangt ein hochgeladenes Dokument. '
                    'Bitte über „Öffnen“ im Datensatz erledigen.'))
            record.action_done()
        else:
            if not record.has_access('write'):
                raise UserError(_(
                    'Sie dürfen diese Aufgabe nicht ändern. '
                    'Bitte über „Öffnen“ ansehen oder die Projektleitung fragen.'))
            record.write({'state': '1_done'})
        return True

    @api.model
    def kjr_popup_open(self, kind, res_id):
        """Aktion zum Öffnen des Eintrags (Datensatz bzw. Aufgabe)."""
        record = self._kjr_popup_record(kind, res_id)
        if kind == ACTIVITY:
            return record.action_open_document()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'project.task',
            'res_id': record.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------
    @api.model
    def _kjr_popup_settings(self):
        """Abfrage-Intervall und Zurückstell-Dauer (Systemparameter)."""
        ICP = self.env['ir.config_parameter'].sudo()

        def _int(key, default, minimum, maximum):
            try:
                value = int(ICP.get_param(key, default))
            except (TypeError, ValueError):
                value = default
            return min(max(value, minimum), maximum)

        return {
            'poll_minutes': _int(PARAM_POLL, DEFAULT_POLL, 1, 240),
            'snooze_minutes': _int(PARAM_SNOOZE, DEFAULT_SNOOZE, 5, 24 * 60),
        }

    @api.model
    def _kjr_popup_tasks_available(self):
        return 'project.task' in self.env

    @api.model
    def _kjr_popup_key(self, kind, res_id):
        if not isinstance(kind, str) or kind not in KIND_MODEL \
                or (kind == TASK and not self._kjr_popup_tasks_available()):
            raise UserError(_('Unbekannte Art von Erinnerung.'))
        try:
            res_id = int(res_id)
        except (TypeError, ValueError):
            raise UserError(_('Ungültige Erinnerung.')) from None
        if res_id <= 0:
            raise UserError(_('Ungültige Erinnerung.'))
        return KIND_MODEL[kind], res_id

    @api.model
    def _kjr_popup_record(self, kind, res_id):
        """Datensatz zu ``kind``/``res_id`` – nur, wenn er dem angemeldeten
        Benutzer zugewiesen ist. Die eigentlichen Rechte prüft Odoo danach
        beim Lesen/Schreiben wie gewohnt."""
        res_model, res_id = self._kjr_popup_key(kind, res_id)
        record = self.env[res_model].browse(res_id).exists()
        if not record:
            raise UserError(_('Dieser Eintrag existiert nicht mehr.'))
        uid = self.env.uid
        if kind == ACTIVITY:
            assigned = record.sudo().user_id.id == uid
        else:
            assigned = uid in record.sudo().user_ids.ids
        if not assigned:
            raise AccessError(_('Dieser Eintrag ist Ihnen nicht zugewiesen.'))
        return record

    @api.model
    def _kjr_popup_assigned_keys(self, keys):
        """Nur die Schlüssel ``(res_model, res_id)`` aus ``keys``, deren
        Eintrag existiert und dem angemeldeten Benutzer zugewiesen ist
        (Aktivität: ``user_id``, Aufgabe: ``user_ids``). Reihenfolge bleibt.

        Mit ``sudo`` gesucht wie in :meth:`_kjr_popup_record`; zurück kommen
        nur Modell und ID, keine Inhalte.
        """
        uid = self.env.uid
        ids_by_model = {}
        for res_model, res_id in keys:
            ids_by_model.setdefault(res_model, []).append(res_id)
        allowed = set()
        for res_model, res_ids in ids_by_model.items():
            field = 'user_id' if res_model == KIND_MODEL[ACTIVITY] else 'user_ids'
            records = self.env[res_model].sudo().search([
                ('id', 'in', res_ids),
                (field, 'in', [uid]),
            ])
            allowed.update((res_model, rid) for rid in records.ids)
        return [key for key in keys if key in allowed]

    @api.model
    def _kjr_popup_end_of_today_utc(self, today):
        """Beginn des morgigen Tages in der Zeitzone des Benutzers, als naiver
        UTC-Zeitpunkt (Format der Datetime-Felder)."""
        tz = self.env.tz
        local = tz.localize(datetime.combine(today + timedelta(days=1), time.min))
        return local.astimezone(pytz.utc).replace(tzinfo=None)

    @api.model
    def _kjr_popup_candidates(self, today):
        """Alle heute fälligen/überfälligen Einträge des Benutzers, älteste
        Frist zuerst."""
        uid = self.env.uid
        grace_start = fields.Datetime.now() - timedelta(minutes=SELF_CREATED_GRACE_MINUTES)

        def _just_created_by_me(record):
            return record.create_uid.id == uid and record.create_date >= grace_start

        candidates = []
        activities = self.search([
            ('user_id', '=', uid),
            ('date_deadline', '<=', today),
        ], order='date_deadline ASC, id ASC', limit=POPUP_CANDIDATE_LIMIT)
        for activity in activities:
            if _just_created_by_me(activity):
                continue
            candidates.append({
                'kind': ACTIVITY,
                'key': ('mail.activity', activity.id),
                'record': activity,
                'due': activity.date_deadline,
            })

        if self._kjr_popup_tasks_available():
            Task = self.env['project.task']
            domain = [
                ('user_ids', 'in', [uid]),
                ('date_deadline', '!=', False),
                ('date_deadline', '<', self._kjr_popup_end_of_today_utc(today)),
                ('state', 'not in', TASK_CLOSED_STATES),
            ]
            if 'is_template' in Task._fields:
                domain.append(('is_template', '=', False))
            tasks = Task.search(domain, order='date_deadline ASC, id ASC',
                                limit=POPUP_CANDIDATE_LIMIT)
            for task in tasks:
                if _just_created_by_me(task):
                    continue
                candidates.append({
                    'kind': TASK,
                    'key': ('project.task', task.id),
                    'record': task,
                    'due': fields.Datetime.context_timestamp(self, task.date_deadline).date(),
                })

        candidates.sort(key=lambda c: (c['due'], c['kind'] != ACTIVITY, c['key'][1]))
        return candidates

    @api.model
    def _kjr_popup_safe_item(self, candidate, today):
        """Wie :meth:`_kjr_popup_item`, liefert aber ``None`` statt eines
        AccessError (Eintrag wird dann übersprungen)."""
        try:
            return self._kjr_popup_item(candidate, today)
        except AccessError:
            # nur Modell und ID, keine personenbezogenen Daten
            _logger.info('Aktivitäten-Popup: Eintrag %s,%s übersprungen (keine Leserechte).',
                         *candidate['key'])
            return None

    @api.model
    def _kjr_popup_item(self, candidate, today):
        """Darstellungsdaten eines Eintrags für das Popup."""
        record = candidate['record']
        due = candidate['due']
        days_overdue = max(0, (today - due).days)
        item = {
            'key': '%s,%s' % candidate['key'],
            'kind': candidate['kind'],
            'id': record.id,
            'state': 'overdue' if days_overdue else 'today',
            'days_overdue': days_overdue,
        }
        if candidate['kind'] == ACTIVITY:
            activity = record
            model_name = ''
            if activity.res_model:
                model_name = self.env['ir.model']._get(activity.res_model).display_name
            note = ''
            if activity.note and not is_html_empty(activity.note):
                note = re.sub(r'\s+', ' ', html2plaintext(activity.note)).strip()
            if len(note) > NOTE_MAX_CHARS:
                note = note[:NOTE_MAX_CHARS - 1].rstrip() + '…'
            item.update({
                'title': activity.summary or activity.activity_type_id.name or _('Aktivität'),
                'type_name': activity.activity_type_id.name or _('Aktivität'),
                'icon': activity.icon or 'fa-tasks',
                'record_name': activity.res_name or '',
                'model_name': model_name,
                'deadline': format_date(self.env, activity.date_deadline),
                'note': note,
                'can_done': activity.activity_category != 'upload_file',
            })
        else:
            task = record
            # Den Projektnamen bewusst mit sudo lesen: Zugewiesene dürfen ihre
            # Aufgabe lesen, ein Projekt mit Sichtbarkeit „Eingeladene interne
            # Benutzer“ (followers) aber nur als dessen Follower. Gezeigt wird
            # nur der Name des Projekts der eigenen Aufgabe.
            project = task.sudo().project_id
            item.update({
                'title': task.name or _('Aufgabe'),
                'type_name': _('Aufgaben-Frist'),
                'icon': 'fa-tasks',
                'record_name': project.display_name or '',
                'model_name': _('Projekt') if project else _('Aufgabe'),
                'deadline': format_datetime(
                    self.env, task.date_deadline,
                    tz=self.env.tz.zone, dt_format='short'),
                'note': '',
                # Interne Benutzer ohne Projekt-Gruppe dürfen zugewiesene
                # Aufgaben nur lesen (access_task_on_partner) -> kein „Erledigt“.
                'can_done': task.has_access('write'),
            })
        return item
