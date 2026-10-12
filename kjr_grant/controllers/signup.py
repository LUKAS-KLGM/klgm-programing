# -*- coding: utf-8 -*-
"""Registrierung (/web/signup): Privatperson oder für einen Verein / Verband.

Das Formular (views/auth_signup_templates.xml) fragt die Art der Registrierung
ab. Bei „für einen Verein“ prüft dieser Controller die Vereinsangaben und reicht
sie unter AFFILIATION_KEY an res.users.signup weiter; dort entsteht die
Vereinsregistrierung „beantragt“ (models/res_users.py). Rechte entstehen erst
durch die Genehmigung der Geschäftsstelle.

Mit Token (Einladung, Passwort zurücksetzen) gibt es nie Vereinsangaben: das
Template blendet die Wahl aus, dieser Controller ignoriert sie und
res.users.signup entfernt den Schlüssel noch einmal vor super().

Der Spam-Schutz (kjr_website_antispam) nimmt die Registrierung ausdrücklich aus;
das bleibt so.

Seit 19.0.17.0.0 zusätzlich (Vereinsblock): Auswahl des Dachverbands aus den
KJR-Mitgliedsverbänden (freiwillig), Ankreuzfeld „Ich bin Delegierte/r meines
Verbands“ und Telefon (Pflicht bei Delegierten). In die Delegiertenliste kommt
die Person erst mit der Genehmigung (models/kjr_affiliation_request.py).
"""
import re

from odoo import _
from odoo.exceptions import UserError
from odoo.http import request
from odoo.addons.auth_signup.controllers.main import AuthSignupHome
from odoo.addons.kjr_grant.controllers.portal import PHONE_RE
from odoo.addons.kjr_grant.models.kjr_affiliation_request import SIGNUP_PARENT_DOMAIN
from odoo.addons.kjr_grant.models.res_users import AFFILIATION_KEY

KJR_SIGNUP_PARAMS = ('kjr_signup_type', 'kjr_club_name', 'kjr_club_function', 'kjr_club_place',
                     'kjr_club_parent_id', 'kjr_club_delegate', 'kjr_club_phone')
CLUB_NAME_MAX, CLUB_FUNCTION_MAX, CLUB_PLACE_MAX = 120, 80, 120
CLUB_NAME_MIN = 2
URL_RE = re.compile(r'(https?://|www\.)', re.I)


class KjrAuthSignupHome(AuthSignupHome):

    def get_auth_signup_qcontext(self):
        qcontext = super().get_auth_signup_qcontext()
        # qcontext übernimmt nur SIGN_UP_REQUEST_PARAMS (web/controllers/home.py);
        # die globale Menge NICHT ändern, sie gilt auch für /web/login.
        if not qcontext.get('token'):
            for key in KJR_SIGNUP_PARAMS:
                if key in request.params:
                    qcontext[key] = (request.params.get(key) or '').strip()
            # Löschfrist für den Datenschutzhinweis: dieselbe Auslegung wie der
            # Lösch-Cron (int, Rückfall 180, 0 = keine Löschung).
            qcontext['kjr_retention_days'] = request.env[
                'kjr.affiliation.request'].sudo()._kjr_retention_days()
            # Auswahlliste Dachverband: nur Name und ID (sudo, Public-User).
            qcontext['kjr_parent_options'] = [
                (p.id, p.name) for p in self._kjr_signup_parent_options()]
        return qcontext

    @staticmethod
    def _kjr_signup_parent_options():
        """Wählbare Dachverbände: aktive KJR-Mitgliedsverbände, nach Name."""
        return request.env['res.partner'].sudo().search(SIGNUP_PARENT_DOMAIN, order='name')

    def _prepare_signup_values(self, qcontext):
        values = super()._prepare_signup_values(qcontext)
        if qcontext.get('token'):
            return values  # Einladung / Passwort-Reset: nie Vereinsangaben
        signup_type = qcontext.get('kjr_signup_type')
        if not signup_type or signup_type == 'private':
            # Ohne Feld (Odoo-Standardtests, Fremdaufrufe) = Privatperson.
            return values
        if signup_type != 'club':
            raise UserError(_('Bitte wählen Sie, ob Sie sich als Privatperson oder für einen '
                              'Verein registrieren.'))
        name = ' '.join((qcontext.get('kjr_club_name') or '').split())
        function = ' '.join((qcontext.get('kjr_club_function') or '').split())
        place = ' '.join((qcontext.get('kjr_club_place') or '').split())
        if not name:
            raise UserError(_('Bitte geben Sie den Namen Ihres Vereins oder Verbands an.'))
        if len(name) < CLUB_NAME_MIN:
            # Abkürzungen wie „SV“ sind erlaubt; ein einzelnes Zeichen nicht.
            raise UserError(_('Bitte geben Sie den vollständigen Namen Ihres Vereins oder '
                              'Verbands an.'))
        if (len(name) > CLUB_NAME_MAX or len(function) > CLUB_FUNCTION_MAX
                or len(place) > CLUB_PLACE_MAX):
            raise UserError(_('Eine Angabe zum Verein ist zu lang.'))
        if any(URL_RE.search(v) for v in (name, function, place)):
            raise UserError(_('Bitte keine Internetadressen in den Angaben zum Verein.'))
        parent_id = 0
        raw_parent = (qcontext.get('kjr_club_parent_id') or '').strip()
        if raw_parent:
            try:
                parent_id = int(raw_parent)
            except ValueError:
                parent_id = -1
            if parent_id not in self._kjr_signup_parent_options().ids:
                raise UserError(_('Bitte wählen Sie Ihren Dachverband aus der Liste oder lassen '
                                  'Sie das Feld leer.'))
        delegate = bool(qcontext.get('kjr_club_delegate'))
        phone = ' '.join((qcontext.get('kjr_club_phone') or '').split())
        if delegate and not phone:
            raise UserError(_('Als Delegierte/r geben Sie bitte eine Telefonnummer an, damit die '
                              'Geschäftsstelle Sie vor der Vollversammlung erreichen kann.'))
        if phone and not PHONE_RE.match(phone):
            raise UserError(_('Telefon bitte nur mit Ziffern und den Zeichen + ( ) / - angeben '
                              '(z. B. 08321 1234-0).'))
        values[AFFILIATION_KEY] = {
            'name': name, 'function': function, 'place': place,
            'parent_id': parent_id or False, 'delegate': delegate, 'phone': phone,
        }
        return values
