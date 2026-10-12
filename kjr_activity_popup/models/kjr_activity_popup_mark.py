# -*- coding: utf-8 -*-
"""Serverseitiger Merker für das Aktivitäten-Popup.

Pro Benutzer und Eintrag (Aktivität bzw. Projekt-Aufgabe) wird festgehalten,
an welchem Tag das Popup ihn zuletzt gezeigt hat und bis wann er
zurückgestellt ist („Später erinnern“). Damit erscheint jeder Eintrag
höchstens einmal pro Tag – auch bei mehreren offenen Browser-Tabs und
unabhängig davon, in welchem Tab das Popup erschienen ist.

Der Merker wird ausschließlich vom Server (sudo) gepflegt; Benutzer haben
keine direkten Zugriffsrechte auf das Modell.
"""
from datetime import timedelta

from odoo import api, fields, models
from odoo.tools import SQL


class KjrActivityPopupMark(models.Model):
    _name = 'kjr.activity.popup.mark'
    _description = 'Aktivitäten-Popup: Anzeige-Merker'
    _order = 'id'

    user_id = fields.Many2one(
        'res.users', string='Benutzer', required=True, index=True,
        ondelete='cascade')
    res_model = fields.Char(string='Modell', required=True)
    res_id = fields.Many2oneReference(
        string='Datensatz-ID', model_field='res_model', required=True)
    shown_date = fields.Date(
        string='Zuletzt angezeigt am',
        help='Tag (in der Zeitzone des Benutzers), an dem das Popup den '
             'Eintrag zuletzt gezeigt hat.')
    snooze_until = fields.Datetime(
        string='Zurückgestellt bis',
        help='„Später erinnern“: vor diesem Zeitpunkt wird der Eintrag nicht '
             'erneut angezeigt, danach auch am selben Tag noch einmal.')

    _unique_user_target = models.Constraint(
        'UNIQUE(user_id, res_model, res_id)',
        'Pro Benutzer und Eintrag gibt es nur einen Popup-Merker.',
    )

    # ------------------------------------------------------------------
    # Regeln
    # ------------------------------------------------------------------
    @api.model
    def _kjr_is_due(self, mark, today, now):
        """Soll der Eintrag zu ``mark`` jetzt (wieder) angezeigt werden?

        * zurückgestellt und Frist noch nicht abgelaufen -> nein
        * zurückgestellt und Frist abgelaufen            -> ja
        * nicht zurückgestellt                           -> ja, wenn heute
          noch nicht angezeigt
        """
        if not mark:
            return True
        if mark.snooze_until:
            return mark.snooze_until <= now
        return mark.shown_date != today

    # ------------------------------------------------------------------
    # Schreiben (atomar per INSERT ... ON CONFLICT)
    # ------------------------------------------------------------------
    @api.model
    def _kjr_claim(self, user, keys, today, now):
        """Markiert ``keys`` (Liste von ``(res_model, res_id)``) für ``user``
        als heute angezeigt – aber nur die, die noch fällig sind.

        Der Abgleich geschieht in einer einzigen SQL-Anweisung. Laufen zwei
        Abrufe (z. B. zwei Tabs) gleichzeitig, bekommt nur einer den Eintrag:
        der zweite scheitert in REPEATABLE READ mit einem Serialisierungsfehler,
        Odoo wiederholt die Anfrage, und dann greift die WHERE-Bedingung nicht
        mehr.

        :return: Menge der tatsächlich beanspruchten ``(res_model, res_id)``
        """
        if not keys:
            return set()
        self.flush_model()
        values = SQL(', ').join(
            SQL('(%s, %s, %s, %s, NULL, %s, %s, %s, %s)',
                user.id, res_model, res_id, today,
                self.env.uid, now, self.env.uid, now)
            for res_model, res_id in keys
        )
        rows = self.env.execute_query(SQL(
            """
            INSERT INTO kjr_activity_popup_mark AS m
                   (user_id, res_model, res_id, shown_date, snooze_until,
                    create_uid, create_date, write_uid, write_date)
            VALUES %(values)s
            ON CONFLICT (user_id, res_model, res_id) DO UPDATE
               SET shown_date = EXCLUDED.shown_date,
                   snooze_until = NULL,
                   write_uid = EXCLUDED.write_uid,
                   write_date = EXCLUDED.write_date
             WHERE (m.snooze_until IS NOT NULL AND m.snooze_until <= %(now)s)
                OR (m.snooze_until IS NULL
                    AND m.shown_date IS DISTINCT FROM EXCLUDED.shown_date)
            RETURNING m.res_model, m.res_id
            """,
            values=values, now=now,
        ))
        self.invalidate_model()
        return {(res_model, res_id) for res_model, res_id in rows}

    @api.model
    def _kjr_snooze(self, user, keys, minutes, now):
        """Stellt ``keys`` für ``user`` um ``minutes`` Minuten zurück."""
        if not keys:
            return
        self.flush_model()
        until = now + timedelta(minutes=minutes)
        today = fields.Date.context_today(self)
        values = SQL(', ').join(
            SQL('(%s, %s, %s, %s, %s, %s, %s, %s, %s)',
                user.id, res_model, res_id, today, until,
                self.env.uid, now, self.env.uid, now)
            for res_model, res_id in keys
        )
        self.env.execute_query(SQL(
            """
            INSERT INTO kjr_activity_popup_mark AS m
                   (user_id, res_model, res_id, shown_date, snooze_until,
                    create_uid, create_date, write_uid, write_date)
            VALUES %s
            ON CONFLICT (user_id, res_model, res_id) DO UPDATE
               SET snooze_until = EXCLUDED.snooze_until,
                   write_uid = EXCLUDED.write_uid,
                   write_date = EXCLUDED.write_date
            """,
            values,
        ))
        self.invalidate_model()

    # ------------------------------------------------------------------
    # Aufräumen
    # ------------------------------------------------------------------
    @api.autovacuum
    def _gc_old_marks(self):
        """Merker, die älter als eine Woche und nicht mehr zurückgestellt sind,
        haben keine Wirkung mehr (ein neuer Tag zeigt den Eintrag ohnehin
        wieder) und werden gelöscht – auch die zu erledigten oder gelöschten
        Aktivitäten."""
        limit_date = fields.Date.today() - timedelta(days=7)
        now = fields.Datetime.now()
        self.sudo().search([
            ('shown_date', '<', limit_date),
            '|', ('snooze_until', '=', False), ('snooze_until', '<', now),
        ]).unlink()
