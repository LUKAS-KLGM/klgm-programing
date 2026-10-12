# -*- coding: utf-8 -*-
from odoo import fields, models


class MailMail(models.Model):
    """Kennung für abgekoppelt abgelegte Mails zu einer Anmeldung.

    Die Einwilligungs-Erinnerung enthält den Signierlink (Bearer-Link) und wird
    deshalb OHNE Bezug zur Anmeldung abgelegt (``model``/``res_id`` leer, siehe
    ``models/kjr_event_document.py``, ``_kjr_send_template(detach=True)``). Damit
    findet die DSGVO-Anonymisierung sie nicht mehr über ``model``/``res_id``.
    Schlägt der Versand fehl, löscht Odoo die mail.mail nicht (``auto_delete``
    greift nur nach erfolgreichem Versand); Name des Kindes, Veranstaltung,
    Empfängeradresse und Signierlink blieben sonst über die Frist hinaus stehen.

    Dieses Feld trägt nur die technische ID der Anmeldung (keine
    Personendaten) und liegt auf mail.mail, NICHT auf mail.message: mail.mail
    ist nur für die Administration lesbar (mail/security/ir.model.access.csv,
    base.group_system), der Bezug wird also nicht wieder für alle Leser der
    Anmeldung sichtbar. Es wird auch nicht als E-Mail-Header versendet.
    Ausgewertet in ``event.event._kjr_purge_registration_copies``.
    """
    _inherit = 'mail.mail'

    kjr_detached_registration_id = fields.Integer(
        string='KJR: zugehörige Anmeldung (abgekoppelt)',
        index='btree_not_null', copy=False, readonly=True,
        help='Technische ID der Veranstaltungsanmeldung, zu der diese Mail ohne '
             'Datensatzbezug abgelegt wurde (Einwilligungs-Erinnerung mit '
             'Signierlink). Dient nur der Löschung bei der Anonymisierung.')
