# -*- coding: utf-8 -*-
"""Ersetzt die aus Nupian übernommenen Veranstaltungsfragen durch die sechs
Standardfragen aus kjr_event (Rückmeldung Theresa 14.10.2026, Aufgabe 111).

Autor:   KLGM UG (haftungsbeschraenkt), https://www.klgm-consulting.de
Lizenz:  OPL-1
Stand:   2026-10-22
Voraussetzung: kjr_event >= 19.0.5.11.0 (liefert die Standardfragen
kjr_event.event_question_kjr_*).

AUSFUEHREN DARF DAS SKRIPT NUR EINE BERECHTIGTE PERSON auf dem Server bzw.
einer Server-Kopie, nach einem Snapshot. Nicht durch den Assistenten.

Betriebsarten (Umgebungsvariablen):
    (keine)          Dry-Run: listet je Frage die Zuordnung, schreibt nichts.
    KJR_FIX_WRITE=1  ordnet zu, löscht die alten Fragen und committet.

Aufruf (auf dem Server):
    odoo shell -d <db> --no-http < kjr_event_questions_t1013.py
    KJR_FIX_WRITE=1 odoo shell -d <db> --no-http < kjr_event_questions_t1013.py

Regeln:
* Betroffen sind alle Fragen außer Name/E-Mail/Telefon/Firma (Kernfragen)
  und den Standardfragen selbst.
* Thema per Stichwort: schwimm -> Schwimmen, Kost/Ernähr -> Kost,
  Ticket/Deutschlandticket/Nahverkehr -> Ticket, Kleingruppe -> Kleingruppe,
  Pferd/Reit -> Pferde, Handy -> Handynummer. Jede Veranstaltung, die eine alte
  Frage zum Thema hatte, bekommt die passende Standardfrage.
* Alles ohne Treffer (Fahrgemeinschaft, nur Lieblingsessen) entfällt
  ersatzlos (Antwort Theresa 15.10.: "alles nicht Genannte kommt raus").
* Eine alte Frage MIT gespeicherten Antworten wird nicht gelöscht, sondern
  archiviert und von den Veranstaltungen gelöst (Antworten bleiben lesbar).
  Stand Prod 22.10.2026: 0 Antworten.
"""
import os

WRITE = os.environ.get('KJR_FIX_WRITE') == '1'

TOPICS = [
    ('kjr_event.event_question_kjr_swimming', ('schwimm',)),
    ('kjr_event.event_question_kjr_ticket', ('ticket', 'nahverkehr')),
    ('kjr_event.event_question_kjr_small_group', ('kleingruppe',)),
    ('kjr_event.event_question_kjr_horses', ('pferd', 'reit')),
    ('kjr_event.event_question_kjr_mobile', ('handy',)),
    ('kjr_event.event_question_kjr_diet', ('kost', 'ernährt', 'ernaehrt')),
]
CORE_TYPES = ('name', 'email', 'phone', 'company_name')

env = env  # noqa: F821 - von odoo shell bereitgestellt
Question = env['event.question'].with_context(active_test=False, lang='de_DE')
standard = {xmlid: env.ref(xmlid) for xmlid, _keys in TOPICS}
old_questions = Question.search([('question_type', 'not in', CORE_TYPES)]) \
    - Question.browse([q.id for q in standard.values()])

Answer = env['event.registration.answer']
for question in old_questions.sorted('id'):
    title = (question.title or '').lower()
    targets = [standard[xmlid] for xmlid, keys in TOPICS if any(k in title for k in keys)]
    events = question.event_ids
    answers = Answer.search_count([('question_id', '=', question.id)])
    print('Frage %s %r | Veranstaltungen %s | Antworten %s -> %s' % (
        question.id, question.title, events.ids, answers,
        ', '.join(t.title for t in targets) or 'entfällt'))
    if not WRITE:
        continue
    for target in targets:
        target.event_ids = [(4, ev.id) for ev in events]
    if answers:
        question.write({'event_ids': [(5, 0, 0)], 'active': False})
    else:
        question.unlink()

if WRITE:
    env.cr.commit()
    print('Geschrieben.')
else:
    env.cr.rollback()
    print('Dry-Run, nichts geschrieben.')
