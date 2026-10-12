# -*- coding: utf-8 -*-
"""Spam-Schutz für öffentliche Formulare: Honeypot und signiertes Zeittoken.

Anker ist der Standard-Hook ``ir.http._verify_request_recaptcha_token(action)``
(odoo/addons/base/models/ir_http.py). Ihn rufen auf:

- ``ir.http._dispatch`` für Routen mit ``captcha=...`` (Website-Formulare:
  ``website_form``),
- ``website_event`` vor dem Anlegen der Anmeldungen
  (``website_event_registration``, Fehler -> Weiterleitung mit
  ``registration_error_code=recaptcha_failed``),
- ``kjr_rental`` im POST-Zweig der Spielmobil-Anfrage (``kjr_spielmobil``).

google_recaptcha und website_cf_turnstile hängen sich an denselben Hook und
rufen zuerst ``super()`` auf. Dieses Modul macht es genauso: erst die
Captcha-Prüfungen der Kette, danach Honeypot und Zeittoken.

Geprüft wird nur, was in ``kjr_website_antispam.actions`` steht (fnmatch-Muster,
kommagetrennt). Login, Registrierung und Passwort-Zurücksetzen rufen den Hook
mit eigenen Aktionen auf oder gar nicht und sind damit nie betroffen.

Mindestzeit: Das Token belegt nur, wann es ausgestellt wurde. Bei Formularen,
die der Server vorausgefüllt ausliefert, kann ein echter Mensch sehr schnell
absenden. Der Teilnehmerdialog der Veranstaltungsanmeldung
(``website_event_registration``) wird erst nach Ticketauswahl und Klick per
jsonrpc gerendert, für angemeldete Benutzer und wiedererkannte Besucher füllt
der Kern Name, E-Mail und Telefon vor; ein Klick auf "Registrierung bestätigen"
genügt. Für die Aktionen aus ``kjr_website_antispam.min_seconds_exempt``
(Standard: genau diese Aktion) gilt deshalb KEINE Mindestzeit; Honeypot,
Signatur und Höchstalter werden weiter geprüft.

Datenschutz: Das Log nennt nur Aktion, Grund und Modus. Keine IP-Adresse,
keine Formularwerte, kein Token.
"""
import fnmatch
import logging
import time

from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools.misc import consteq, hmac

_logger = logging.getLogger(__name__)

# Namen der Request-Parameter. Bewusst OHNE '-': website_event
# (_process_attendees_form) und die KJR-Extraktion werten nur Schlüssel der
# Form '<index>-<feld>' aus und übergehen diese beiden damit.
HONEYPOT_PARAM = 'kjr_hp'
TOKEN_PARAM = 'kjr_ts'

# Geltungsbereich der HMAC-Signatur (odoo.tools.misc.hmac, Schlüssel ist
# database.secret). Ein Token aus einem anderen Zusammenhang passt nie.
HMAC_SCOPE = 'kjr_website_antispam'

PARAM_MODE = 'kjr_website_antispam.mode'
PARAM_MIN_SECONDS = 'kjr_website_antispam.min_seconds'
PARAM_MIN_SECONDS_EXEMPT = 'kjr_website_antispam.min_seconds_exempt'
PARAM_MAX_AGE_HOURS = 'kjr_website_antispam.max_age_hours'
PARAM_ACTIONS = 'kjr_website_antispam.actions'

MODES = ('enforce', 'log', 'off')
DEFAULT_MODE = 'enforce'
# 2 s statt der ursprünglich geplanten 3 s: weniger Fehlalarme bei schnell
# ausgefüllten bzw. erneut abgesendeten Formularen; Formular-Bots senden meist
# im Bruchteil einer Sekunde.
DEFAULT_MIN_SECONDS = 2
DEFAULT_MAX_AGE_HOURS = 24
DEFAULT_ACTIONS = 'website_form,website_event_registration,kjr_*'
# Aktionen ohne Mindestzeit (fnmatch, kommagetrennt), siehe Moduldocstring.
DEFAULT_MIN_SECONDS_EXEMPT = 'website_event_registration'

# Obergrenze für die Länge eines Tokens ('<Sekunden>.<64 Hex-Zeichen>').
# Längere Werte werden gar nicht erst signaturgeprüft.
MAX_TOKEN_LENGTH = 128


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    # ------------------------------------------------------------------
    # Hook
    # ------------------------------------------------------------------
    @api.model
    def _verify_request_recaptcha_token(self, action):
        """Erst die Captcha-Kette (reCAPTCHA/Turnstile), dann der KJR-Schutz."""
        super()._verify_request_recaptcha_token(action)
        if self._kjr_antispam_applies(action):
            self._kjr_antispam_check(action)
        else:
            # Nicht geprüft (Aktion nicht gelistet, Modus 'off', GET): die
            # beiden Felder trotzdem aus den Parametern nehmen. Sonst landen sie
            # z. B. beim Website-Formular als "Weitere Angaben" im Datensatz.
            self._kjr_antispam_discard_params()

    # ------------------------------------------------------------------
    # Konfiguration
    # ------------------------------------------------------------------
    @api.model
    def _kjr_antispam_mode(self):
        """'enforce' | 'log' | 'off' aus kjr_website_antispam.mode.

        Fehlt der Parameter oder ist der Wert unbekannt, gilt 'enforce'
        (fail-closed: ein Tippfehler schaltet den Schutz nicht ab).
        """
        value = self.env['ir.config_parameter'].sudo().get_param(PARAM_MODE) or DEFAULT_MODE
        value = str(value).strip().lower()
        return value if value in MODES else DEFAULT_MODE

    @api.model
    def _kjr_antispam_int_param(self, key, default, allow_zero=True):
        """Ganzzahliger Systemparameter; ungültige oder negative Werte -> default."""
        raw = self.env['ir.config_parameter'].sudo().get_param(key)
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            return default
        if value < 0 or (value == 0 and not allow_zero):
            return default
        return value

    @api.model
    def _kjr_antispam_patterns(self, key, default):
        """Kommagetrennte fnmatch-Muster aus einem Systemparameter."""
        raw = self.env['ir.config_parameter'].sudo().get_param(key, default)
        return [part.strip() for part in str(raw or '').split(',') if part.strip()]

    @api.model
    def _kjr_antispam_min_seconds(self, action=None):
        """Mindestzeit zwischen Token und Absenden; 0 = keine Mindestzeit.

        Für Aktionen aus kjr_website_antispam.min_seconds_exempt gilt 0
        (vorausgefüllter, serverseitig gerenderter Teilnehmerdialog, siehe
        Moduldocstring). Ohne ``action`` gilt der allgemeine Wert.
        """
        if action and any(
                fnmatch.fnmatchcase(action, pattern)
                for pattern in self._kjr_antispam_patterns(
                    PARAM_MIN_SECONDS_EXEMPT, DEFAULT_MIN_SECONDS_EXEMPT)):
            return 0
        return self._kjr_antispam_int_param(PARAM_MIN_SECONDS, DEFAULT_MIN_SECONDS)

    @api.model
    def _kjr_antispam_max_age_seconds(self):
        """Höchstalter des Tokens in Sekunden.

        0, leer oder ungültig ergibt den Standard (24 h): ein Token ohne
        Ablauf liesse sich einmal abgreifen und unbegrenzt wiederverwenden.
        """
        hours = self._kjr_antispam_int_param(
            PARAM_MAX_AGE_HOURS, DEFAULT_MAX_AGE_HOURS, allow_zero=False)
        return hours * 3600

    @api.model
    def _kjr_antispam_actions(self):
        """Liste der fnmatch-Muster aus kjr_website_antispam.actions."""
        return self._kjr_antispam_patterns(PARAM_ACTIONS, DEFAULT_ACTIONS)

    # ------------------------------------------------------------------
    # Token
    # ------------------------------------------------------------------
    @api.model
    def _kjr_antispam_token(self, timestamp=None):
        """Signiertes Zeittoken '<Unix-Sekunden>.<HMAC-SHA256>'.

        ``timestamp`` ist nur für Tests gedacht; im Betrieb gilt die aktuelle
        Zeit. sudo-Umgebung, weil hmac() database.secret liest und der Aufruf
        auch als öffentlicher Benutzer (Website, jsonrpc) kommt.
        """
        ts = int(time.time()) if timestamp is None else int(timestamp)
        return '%d.%s' % (ts, hmac(self.env(su=True), HMAC_SCOPE, str(ts)))

    @api.model
    def _kjr_antispam_token_age(self, token):
        """Alter des Tokens in Sekunden oder None, wenn es ungültig ist."""
        if not token or not isinstance(token, str) or len(token) > MAX_TOKEN_LENGTH:
            return None
        ts_part, sep, signature = token.partition('.')
        if not sep or not ts_part.isdigit() or not signature:
            return None
        try:
            ts = int(ts_part)
            expected = hmac(self.env(su=True), HMAC_SCOPE, str(ts))
            # Bytes vergleichen: compare_digest wirft bei Nicht-ASCII-str.
            if str(ts) != ts_part or not consteq(
                    signature.encode('utf-8'), expected.encode('ascii')):
                return None
        except (TypeError, ValueError, OverflowError):
            return None
        return int(time.time()) - ts

    # ------------------------------------------------------------------
    # Prüfung
    # ------------------------------------------------------------------
    @api.model
    def _kjr_antispam_applies(self, action):
        """True, wenn der KJR-Schutz für diese Aktion in diesem Request greift."""
        if not action or self._kjr_antispam_mode() == 'off':
            return False
        if not request:
            return False
        try:
            method = request.httprequest.method
        except (AttributeError, RuntimeError):
            return False
        if method != 'POST':
            return False
        return any(fnmatch.fnmatchcase(action, pattern)
                   for pattern in self._kjr_antispam_actions())

    @api.model
    def _kjr_antispam_discard_params(self):
        """Nimmt Honeypot und Token aus request.params (ohne Prüfung)."""
        if not request:
            return
        params = getattr(request, 'params', None)
        if params is None:
            return
        params.pop(HONEYPOT_PARAM, None)
        params.pop(TOKEN_PARAM, None)

    @api.model
    def _kjr_antispam_reason(self, honeypot, token, action=None):
        """Grund der Abweisung oder None, wenn alles in Ordnung ist.

        ``action`` bestimmt nur die Mindestzeit (Ausnahmen siehe
        _kjr_antispam_min_seconds).
        """
        if honeypot and str(honeypot).strip():
            return 'honeypot'
        if not token:
            return 'token_missing'
        age = self._kjr_antispam_token_age(token if isinstance(token, str) else str(token))
        if age is None:
            return 'token_invalid'
        min_seconds = self._kjr_antispam_min_seconds(action)
        if min_seconds and age < min_seconds:
            return 'too_fast'
        if age > self._kjr_antispam_max_age_seconds():
            return 'expired'
        return None

    @api.model
    def _kjr_antispam_precheck(self, action):
        """Vorabprüfung ohne Nebenwirkung: Grund der Abweisung oder None.

        Für äußere Controller, die VOR super() wissen müssen, ob der Hook die
        Anfrage abweisen wird (Veranstaltungsanmeldung mit bereits gefülltem
        Warenkorb: website_event_sale verwirft die Fehler-Weiterleitung des
        Kerns und geht trotzdem in den Checkout, siehe README.md, „Grenzen").

        Liefert nur im Modus 'enforce' einen Grund. Nimmt nichts aus
        request.params, protokolliert nichts und prüft nur den KJR-Teil
        (Honeypot und Zeittoken); reCAPTCHA/Turnstile bleiben unberührt, ihre
        Einmal-Token werden also nicht verbraucht. Die eigentliche Prüfung
        (mit Log und Entfernen der Parameter) läuft danach wie gewohnt im Hook.
        """
        if not self._kjr_antispam_applies(action) or self._kjr_antispam_mode() != 'enforce':
            return None
        params = getattr(request, 'params', None) or {}
        return self._kjr_antispam_reason(
            params.get(HONEYPOT_PARAM, '') or '', params.get(TOKEN_PARAM, '') or '',
            action=action)

    @api.model
    def _kjr_antispam_check(self, action):
        """Prüft Honeypot und Token des laufenden Requests.

        Beide Parameter werden in JEDEM Fall aus request.params entfernt, damit
        sie nicht in Datensätze (Website-Formular) oder Folgecode gelangen.
        Modus 'enforce' wirft UserError, Modus 'log' protokolliert nur.
        """
        mode = self._kjr_antispam_mode()
        honeypot = request.params.pop(HONEYPOT_PARAM, '') or ''
        token = request.params.pop(TOKEN_PARAM, '') or ''
        reason = self._kjr_antispam_reason(honeypot, token, action=action)
        if not reason:
            return
        # Nur Aktion, Grund und Modus. Keine IP, keine Werte, kein Token.
        _logger.info('Spam-Schutz: Aktion %s abgewiesen (%s), Modus %s', action, reason, mode)
        if mode == 'enforce':
            raise UserError(_(
                'Die Anfrage konnte nicht verarbeitet werden. Bitte laden Sie die '
                'Seite neu und senden Sie das Formular erneut.'))
