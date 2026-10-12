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
"""
import re

from odoo import _
from odoo.exceptions import UserError
from odoo.http import request
from odoo.addons.auth_signup.controllers.main import AuthSignupHome
from odoo.addons.kjr_grant.models.res_users import AFFILIATION_KEY

KJR_SIGNUP_PARAMS = ('kjr_signup_type', 'kjr_club_name', 'kjr_club_function', 'kjr_club_place')
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
        return qcontext

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
        values[AFFILIATION_KEY] = {'name': name, 'function': function, 'place': place}
        return values
