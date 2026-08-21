# -*- coding: utf-8 -*-
"""
Portal-Controller für kjr_grant — /my/ Routen für eingeloggte User.

Routen:
  GET      /my/kjr-antraege[/page/<n>]      Portal-Liste
  GET      /my/kjr-antraege/<id>            Portal-Detailansicht
  POST     /service/antrag/<id>/upload          Datei-Upload für bestehenden Antrag
  GET/POST /my/verband                      Verbandsdaten pflegen (Mitgliedsverband)
"""
import base64
import logging
import os
import re

from markupsafe import Markup

from odoo import http, Command, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import AccessError, MissingError

# E-Mail-Regel des Antragsformulars wiederverwenden, damit im Portal nicht eine
# zweite, abweichende Prüfung entsteht (dasselbe Muster wie in website.py, das
# BIC_RE/IBAN_LENGTHS aus dem Modell zieht).
from odoo.addons.kjr_grant.controllers.website import EMAIL_RE, _parse_int

_logger = logging.getLogger(__name__)
ITEMS_PER_PAGE = 10
ALLOWED_EXTENSIONS = {'.pdf', '.xlsx', '.xls', '.csv', '.docx', '.doc', '.jpg', '.jpeg', '.png'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

# ══════════════════════════════════════════════════════════════════════════════
# VERBANDSDATEN IM PORTAL (/my/verband)
# ══════════════════════════════════════════════════════════════════════════════
# Hier schreibt ein Portalnutzer auf res.partner. Alles, was er ändern darf,
# steht in diesen beiden Listen — an write() geht NIE das rohe post-Dict,
# sondern ausschließlich ein aus diesen Listen zusammengebautes Wertedict.
#
# Bewusst NICHT enthalten und damit gesperrt: name, is_kjr_member,
# kjr_member_type, kjr_member_number, kjr_vr_right, kjr_vr_votes,
# kjr_active_since, vat, is_company, parent_id, user_ids und sämtliche
# property_*-Felder. Das sind Feststellungen des KJR bzw. buchhalterische
# Einstellungen; sie ändert nur die Geschäftsstelle. Die Seite ZEIGT sie an
# (siehe _verband_member_info), damit der Verband sieht, was hinterlegt ist.
#
# ACHTUNG: readonly im Template schützt nicht — die Whitelist hier ist der
# einzige wirksame Schutz gegen ein handgebautes POST.
#
# `mobile` steht bewusst NICHT mehr in der Liste: Odoo 19 hat das Feld an
# res.partner entfernt (nur noch `phone`). Es aufzuführen hätte nur den Anschein
# erweckt, die Seite pflege eine Mobilnummer.
VERBAND_WRITABLE_FIELDS = (
    'street', 'street2', 'zip', 'city', 'phone', 'email', 'website',
)
# Ohne Anschrift und E-Mail kann die Geschäftsstelle weder Bescheide zustellen
# noch Rückfragen stellen — deshalb Pflicht. Telefon bleibt freiwillig.
# TODO(KJR): Pflichtumfang bestätigen lassen. Konservativ gewählt (Anschrift +
# E-Mail), damit ein Verband seine Erreichbarkeit im Portal nicht leeren kann.
# Offen: soll auch eine Telefonnummer Pflicht sein (Rückfragen zu Anträgen
# laufen laut Discovery überwiegend telefonisch)?
VERBAND_REQUIRED_FIELDS = ('street', 'zip', 'city', 'email')

# Ansprechpersonen und Delegierte (Kontakte unterhalb des Verbands).
CONTACT_WRITABLE_FIELDS = ('name', 'function', 'email', 'phone')
CONTACT_REQUIRED_FIELDS = ('name',)

# Hängt an einer Ansprechperson ein PORTALZUGANG, darf der Verband an ihr nur
# noch diese Felder ändern. Grund ist keine Formalie, sondern eine echte
# Übernahmemöglichkeit: res.users erbt seine Adressdaten von res.partner
# (_inherits), user.email IST partner.email. Wer die E-Mail-Adresse einer
# fremden Person mit Portalzugang auf die eigene umschreiben könnte, ruft
# anschließend /web/reset_password mit deren Login auf und bekommt die
# Zurücksetzen-Mail selbst zugestellt — er hätte damit den Zugang der anderen
# Person übernommen, ohne je deren Passwort gekannt zu haben. Der Name bleibt
# aus demselben Grund gesperrt: er ist der Anzeigename des Kontos und macht eine
# solche Übernahme unauffällig. Funktion und Telefon bleiben pflegbar — das ist
# der Alltagsfall (Vorstandswechsel, neue Durchwahl).
CONTACT_WRITABLE_FIELDS_WITH_PORTAL_ACCESS = ('function', 'phone')
# Dieselbe Sperre für den Verbandssatz selbst: Ist der Portalzugang direkt auf
# der Organisation angelegt (statt auf einer Person), wäre die E-Mail sonst der
# offene Weg zur Kontoübernahme über „Passwort vergessen".
VERBAND_LOCKED_FIELDS_WITH_PORTAL_ACCESS = ('email',)

# Beschriftungen für Fehlermeldungen UND für den Chatter-Eintrag — eine Quelle,
# damit die Geschäftsstelle im Chatter dieselben Begriffe liest wie der Verband
# im Formular.
PARTNER_FIELD_LABELS = {
    'street':   'Straße und Hausnummer',
    'street2':  'Adresszusatz',
    'zip':      'PLZ',
    'city':     'Ort',
    'phone':    'Telefon',
    'email':    'E-Mail',
    'website':  'Website',
    'name':     'Name',
    'function': 'Funktion im Verband',
}

# PLZ-Plausibilität, bewusst grob: 4 oder 5 Ziffern. Fünf für Deutschland, vier
# für Österreich — das Oberallgäu grenzt an Tirol und Vorarlberg, einzelne
# Verbände haben dort ihren Sitz. Keine Prüfung gegen ein Ortsverzeichnis; es
# geht nur darum, Tippfehler und Freitext abzufangen.
#
# TODO(KJR): Gibt es tatsächlich Mitgliedsverbände mit Sitz außerhalb
# Deutschlands? Solange das offen ist, bleibt die Prüfung so, wie sie ist — aber
# das Formular kennt KEIN Land (country_id steht weder in der Whitelist noch im
# Template). Eine österreichische Anschrift würde damit ohne Landeskennung
# gespeichert und in Bescheiden und Etiketten als Inlandsanschrift adressiert.
# Entscheidung der Geschäftsstelle: entweder country_id ergänzen und die
# PLZ-Prüfung am gewählten Land ausrichten — oder auf 5 Ziffern begrenzen und
# den Österreich-Fall hier und in der Fehlermeldung streichen.
ZIP_RE = re.compile(r'^\d{4,5}$')
# Telefon: bewusst tolerant (Ziffern, Leerzeichen, + ( ) / - .), aber keine
# Buchstaben und keine Ein-Zeichen-Eingaben.
PHONE_RE = re.compile(r'^[0-9 +()/.\-]{5,32}$')

# Meldungen nach erfolgreichem Speichern. Der Redirect (Post/Redirect/Get) trägt
# nur den SCHLÜSSEL in der URL; ausgegeben wird ausschließlich der Text aus
# diesem Dict — nie der Parameterwert selbst.
VERBAND_MESSAGES = {
    'saved': 'Ihre Verbandsdaten wurden gespeichert. Die Geschäftsstelle sieht die '
             'Änderung in der Verlaufsnotiz Ihres Verbands.',
    'unchanged': 'Es gab nichts zu speichern — die Angaben waren unverändert.',
    'contact_created': 'Die Ansprechperson wurde angelegt.',
    'contact_saved': 'Die Ansprechperson wurde gespeichert.',
    'contact_saved_locked': 'Die Ansprechperson wurde gespeichert. Name und '
                            'E-Mail-Adresse blieben dabei unverändert: für diese Person '
                            'besteht ein Portalzugang, und beide Angaben gehören zu '
                            'diesem Zugang. Ändern kann sie die KJR-Geschäftsstelle.',
    'contact_archived': 'Die Ansprechperson wurde aus Ihrer Liste genommen. Gelöscht wurde '
                        'dabei nichts: der Eintrag ist nur stillgelegt, bereits gestellte '
                        'Anträge und Protokolleinträge bleiben unverändert, und die '
                        'Geschäftsstelle kann die Person jederzeit wieder aufnehmen.',
}


class KjrPortalController(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'kjr_grant_count' in counters:
            partner = request.env.user.partner_id
            values['kjr_grant_count'] = request.env['kjr.grant.application'].search_count([
                ('partner_id', 'child_of', [partner.commercial_partner_id.id]),
            ])
        if 'kjr_verband_count' in counters:
            # Kein Mengenzähler, sondern ein Ja/Nein: entweder der eingeloggte
            # Nutzer gehört zu einem Mitgliedsverband (1) oder nicht (0). Bei 0
            # blendet das Template die Kachel AUS (siehe portal_my_home_kjr_verband
            # in views/portal_templates.xml) — Kooperationspartner, Mieter und
            # Entleiher sollen in „Mein Konto" keine Rubrik sehen, die es für sie
            # nicht gibt. Wer /my/verband trotzdem direkt aufruft, bekommt die
            # freundliche Hinweisseite (_render_verband_no_member) statt 404.
            values['kjr_verband_count'] = 1 if self._kjr_verband() else 0
        return values

    @http.route(
        ['/my/kjr-antraege', '/my/kjr-antraege/page/<int:page>'],
        type='http', auth='user', website=True,
    )
    def portal_my_kjr_grants(self, page=1, sortby='date', filterby='all', **kw):
        partner = request.env.user.partner_id
        domain = [('partner_id', 'child_of', [partner.commercial_partner_id.id])]

        filter_options = {
            'all':       {'label': _('Alle'),        'domain': []},
            'draft':     {'label': _('Entwürfe'),    'domain': [('state', '=', 'draft')]},
            'submitted': {'label': _('Eingereicht'), 'domain': [('state', 'in', ('submitted', 'in_review'))]},
            'approved':  {'label': _('Bewilligt'),   'domain': [('state', '=', 'approved')]},
            'paid':      {'label': _('Ausgezahlt'),  'domain': [('state', '=', 'paid')]},
            'rejected':  {'label': _('Abgelehnt'),   'domain': [('state', '=', 'rejected')]},
        }
        if filterby in filter_options:
            domain += filter_options[filterby]['domain']

        sort_options = {
            'date':  {'label': _('Datum'),   'order': 'date_submitted desc, name desc'},
            'name':  {'label': _('Nummer'),  'order': 'name asc'},
            'state': {'label': _('Status'),  'order': 'state asc, name desc'},
        }
        order = sort_options.get(sortby, sort_options['date'])['order']

        grant_model = request.env['kjr.grant.application']
        count = grant_model.search_count(domain)
        pager = portal_pager(
            url='/my/kjr-antraege',
            url_args={'sortby': sortby, 'filterby': filterby},
            total=count, page=page, step=ITEMS_PER_PAGE,
        )
        grants = grant_model.search(
            domain, order=order, limit=ITEMS_PER_PAGE, offset=pager['offset'],
        )
        return request.render('kjr_grant.portal_my_kjr_grants', {
            'grants': grants, 'pager': pager,
            'sortby': sortby, 'filterby': filterby,
            'searchbar_sortings': sort_options, 'searchbar_filters': filter_options,
            'page_name': 'kjr_grant', 'default_url': '/my/kjr-antraege',
        })

    @http.route('/my/kjr-antraege/<int:app_id>', type='http', auth='user', website=True)
    def portal_my_kjr_grant_detail(self, app_id, **kw):
        try:
            grant = self._document_check_access('kjr.grant.application', app_id)
        except (AccessError, MissingError):
            return request.redirect('/my')
        return request.render('kjr_grant.portal_kjr_grant_detail', {
            'grant': grant, 'page_name': 'kjr_grant',
        })

    @http.route(
        '/service/antrag/<int:app_id>/upload',
        type='http', auth='user', website=True, methods=['POST'], csrf=True,
    )
    def kjr_upload_attachment(self, app_id, **kw):
        try:
            application = self._document_check_access('kjr.grant.application', app_id)
        except (AccessError, MissingError):
            return request.redirect('/my')
        if application.state in ('draft', 'submitted'):
            attachment_ids = []
            for field_name in ['tn_list_file', 'report_file', 'receipt_file',
                               'other_file_1', 'other_file_2']:
                for file_obj in request.httprequest.files.getlist(field_name):
                    if not file_obj or not file_obj.filename:
                        continue
                    filename = os.path.basename(file_obj.filename)
                    _, ext = os.path.splitext(filename)
                    if ext.lower() not in ALLOWED_EXTENSIONS:
                        continue
                    file_obj.seek(0, 2)
                    size = file_obj.tell()
                    file_obj.seek(0)
                    if size > MAX_FILE_SIZE:
                        continue
                    try:
                        att = request.env['ir.attachment'].sudo().create({
                            'name': filename,
                            'type': 'binary',
                            'datas': base64.b64encode(file_obj.read()),
                            'res_model': 'kjr.grant.application',
                            'res_id': application.id,
                            'mimetype': file_obj.content_type or 'application/octet-stream',
                        })
                        attachment_ids.append(att.id)
                    except Exception as e:
                        _logger.warning('Upload fehlgeschlagen (%s): %s', filename, e)
            if attachment_ids:
                application.sudo().message_post(
                    body='Unterlagen nachgereicht.',
                    attachment_ids=attachment_ids,
                    subtype_xmlid='mail.mt_note',
                )
        return request.redirect(f'/my/kjr-antraege/{app_id}')

    # ══════════════════════════════════════════════════════════════════════════
    # VERBANDSDATEN — /my/verband
    # ══════════════════════════════════════════════════════════════════════════

    def _kjr_verband(self):
        """Der Verbandssatz, den der angemeldete Nutzer pflegen darf — oder leer.

        Der Zielsatz wird IMMER aus der Session abgeleitet
        (partner_id.commercial_partner_id des angemeldeten Nutzers) und niemals
        aus dem Request. Damit ist auf dieser Seite kein fremder Verband
        erreichbar, egal was im POST steht. Ohne is_kjr_member ist der Nutzer
        kein Mitgliedsverband und bekommt kein Formular.
        """
        commercial = request.env.user.partner_id.commercial_partner_id
        if commercial and commercial.is_kjr_member:
            return commercial
        return request.env['res.partner'].browse()

    @staticmethod
    def _partner_fields(names):
        """Aus einer Whitelist die Felder, die es auf res.partner wirklich gibt.

        Eine Whitelist ist eine Absichtserklärung, kein Schema. Ob ein Feld auf
        DIESER Instanz existiert, entscheidet die Modulzusammenstellung —
        Odoo 19 hat z. B. `mobile` an res.partner ersatzlos entfernt. Statt die
        Version fest zu verdrahten, wird zur Laufzeit geprüft: was es nicht
        gibt, entfällt stillschweigend, statt beim Speichern mit einer Exception
        abzubrechen.
        """
        partner_fields = request.env['res.partner']._fields
        return tuple(name for name in names if name in partner_fields)

    @staticmethod
    def _collect_partner_vals(post, field_names, key_prefix=''):
        """Aus dem POST ausschließlich die Felder der Whitelist lesen und säubern.

        Das rohe post-Dict verlässt diese Methode nicht — was hier nicht
        aufgeführt ist, kann nicht in ein write() oder create() gelangen.

        Aufgenommen wird nur, was im POST auch WIRKLICH steht. Das ist kein
        Schönheitsfehler, sondern verhindert eine Feldlöschung durch Teil-POST:
        stünde für jedes Whitelist-Feld ein Eintrag im Ergebnis, würde ein
        abgeschicktes Formular ohne das Feld `street2` dieses als '' und damit
        als Änderung auf False werten. Ein gemerkter Link oder ein veraltetes
        Formular im Browser-Cache würde so die Hälfte der Kontaktdaten leeren.
        Was nicht mitgeschickt wurde, bleibt unangetastet.
        """
        vals = {}
        for fname in field_names:
            key = key_prefix + fname
            if key not in post:
                continue
            raw = (post.get(key) or '').strip()
            if fname == 'website' and raw and '://' not in raw:
                # Ohne Schema wertet der Browser den Link als relative Adresse
                # und der Verweis auf die Verbandsseite führt ins Leere.
                raw = 'https://%s' % raw
            vals[fname] = raw
        return vals

    @staticmethod
    def _validate_partner_vals(vals, required, errors, key_prefix=''):
        """Serverseitige Prüfung der Kontakt- und Adressangaben.

        Schreibt feldgenaue Meldungen nach `errors`; der Schlüssel ist der
        Feldname mit `key_prefix` davor, damit Verbandsformular (street, zip, …)
        und Kontaktformular (contact_name, contact_email, …) dieselbe Routine
        verwenden. Serverseitig, weil eine Prüfung im Browser bei einem
        handgebauten Request nicht stattfindet.
        """
        for fname in required:
            if fname in vals and not vals[fname]:
                errors[key_prefix + fname] = (
                    '%s ist eine Pflichtangabe.' % PARTNER_FIELD_LABELS.get(fname, fname)
                )
        email = vals.get('email') or ''
        if email and not EMAIL_RE.match(email):
            errors[key_prefix + 'email'] = (
                'Bitte eine gültige E-Mail-Adresse angeben (z. B. info@verein.de). '
                'An diese Adresse gehen Rückfragen und Bescheide der Geschäftsstelle.'
            )
        zip_code = vals.get('zip') or ''
        if zip_code and not ZIP_RE.match(zip_code):
            errors[key_prefix + 'zip'] = (
                'Die Postleitzahl sieht nicht plausibel aus. Erwartet werden 5 Ziffern '
                '(z. B. 87527), bei einer Anschrift in Österreich 4 Ziffern.'
            )
        phone = vals.get('phone') or ''
        if phone and not PHONE_RE.match(phone):
            errors[key_prefix + 'phone'] = (
                'Telefon bitte nur mit Ziffern und den Zeichen + ( ) / - angeben '
                '(z. B. 08321 1234-0).'
            )
        website = vals.get('website') or ''
        if website and (' ' in website or '.' not in website):
            errors[key_prefix + 'website'] = (
                'Die Adresse der Website sieht nicht plausibel aus (z. B. www.verein.de).'
            )

    @staticmethod
    def _changed_fields(record, vals):
        """Nur die Felder, die sich tatsächlich ändern — mit altem und neuem Wert.

        Grundlage für zwei Dinge: geschrieben wird nur, was sich ändert, und es
        entsteht keine Chatter-Notiz, wenn jemand das Formular unverändert
        abschickt. Sonst wäre der Verlauf des Verbands nach kurzer Zeit
        unlesbar.
        """
        changes = []
        for fname, new_value in vals.items():
            old_value = record[fname] if record else False
            old_text = '' if old_value in (False, None) else str(old_value)
            if old_text == new_value:
                continue
            changes.append({
                'field': fname,
                'label': PARTNER_FIELD_LABELS.get(fname, fname),
                'old': old_text,
                'new': new_value,
            })
        return changes

    @staticmethod
    def _log_portal_changes(verband, header, changes):
        """Änderung im Chatter des Verbands protokollieren: wer, was, von/auf was.

        Das ist der Nachweis für die Geschäftsstelle — sie muss nachvollziehen
        können, wer wann welche Angabe geändert hat. Nur mit gefülltem `changes`
        aufrufen (siehe _changed_fields).

        sudo(): Portalnutzer haben auf res.partner nur Leserecht, ein
        message_post scheitert sonst am Schreibrecht auf dem Thread. Der Autor
        bleibt trotz sudo der angemeldete Nutzer (author_id), die Notiz ist also
        ihm zugeordnet und nicht dem Systembenutzer. HTML deshalb über
        markupsafe.Markup, damit eingetragene Werte escaped werden.

        TODO(KJR/DSB): Bei Änderungen an Ansprechpersonen stehen alter UND neuer
        Wert dauerhaft im Verlauf des VERBANDS — also Daten einer Person unter
        einem fremden Datensatz. Die Art.-15-Auskunft des Moduls
        (res_partner.action_kjr_datenauskunft) sucht am Satz der Person und
        findet diese Einträge deshalb nicht. Denkbare Abmilderungen: nur die
        geänderten FELDNAMEN statt der Werte protokollieren, oder den Eintrag
        zusätzlich am Kontakt selbst führen. Keine Änderung ohne Entscheidung
        des KJR — das Protokoll ist zugleich der Nachweis, den die
        Geschäftsstelle braucht.
        """
        items = Markup('').join(
            Markup('<li><b>%s</b>: „%s" → „%s"</li>') % (
                change['label'], change['old'] or '—', change['new'] or '—',
            )
            for change in changes
        )
        verband.sudo().message_post(
            body=Markup('<p>%s</p><ul>%s</ul>') % (header, items),
            subtype_xmlid='mail.mt_note',
            author_id=request.env.user.partner_id.id,
        )

    @staticmethod
    def _verband_contacts(verband):
        """Aktive Ansprechpersonen des Verbands (Personen, keine Unterorganisationen).

        Bewusst ohne sudo: die Datensatzregel für Portalnutzer beschränkt das
        Lesen ohnehin auf den eigenen Baum — eine zweite Sicherung neben der
        Domain.
        """
        return request.env['res.partner'].search([
            ('commercial_partner_id', '=', verband.id),
            ('id', '!=', verband.id),
            ('is_company', '=', False),
            ('type', '=', 'contact'),
            ('active', '=', True),
        ], order='name')

    @staticmethod
    def _verband_delegates(verband):
        """Gemeldete Delegierte des Verbands — als lesbares Recordset.

        Bewusst über search() und bewusst OHNE sudo, statt einfach
        `verband.kjr_vr_delegate_ids` weiterzureichen: Die Many2many-Liste kann
        aus dem Backend heraus auch eine Person enthalten, die NICHT unterhalb
        des Verbands hängt (Doppelmitgliedschaft, Umhängen eines Kontakts). Ein
        solcher Satz liegt ausserhalb der Portal-Datensatzregel
        (base.res_partner_portal_public_rule, `id child_of
        user.commercial_partner_id`) — die Seite bräche beim Rendern der
        Delegiertentabelle mit einem AccessError ab. search() lässt einen
        unlesbaren Satz still weg, statt die ganze Seite mitzunehmen.
        """
        if not verband.kjr_vr_delegate_ids:
            return request.env['res.partner'].browse()
        return request.env['res.partner'].search([
            ('id', 'in', verband.kjr_vr_delegate_ids.ids),
        ], order='name')

    @staticmethod
    def _verband_contact(verband, contact_id):
        """Kontakt aus dem POST — nur wenn er zum eigenen Verband gehört.

        Der Zugehörigkeitstest läuft über commercial_partner_id, also über
        dieselbe Regel wie im Backend. Zusätzlich greift die Datensatzregel für
        Portalnutzer, weil bewusst OHNE sudo gesucht wird: eine fremde ID liefert
        schlicht nichts und kann deshalb nie in ein write() laufen.

        Die Domain ist ABSICHTLICH Zeichen für Zeichen dieselbe wie in
        _verband_contacts, ergänzt um die ID. Sonst entstünde eine Lücke
        zwischen dem, was die Seite ZEIGT, und dem, was sie SCHREIBT: eine
        Rechnungs- oder Lieferadresse des eigenen Verbands (type='invoice' /
        'delivery') taucht in keiner Tabelle auf, ließe sich über ein
        untergeschobenes contact_id aber umbenennen, verknüpfen und
        stilllegen — eine Änderung, die auf der Seite niemandem auffiele.

        TODO(KJR): Vor dem Go-live gegen die Bestandsdaten prüfen. Sind dort
        Ansprechpersonen mit abweichendem `type` gepflegt, gehört der Filter
        gelockert (an BEIDEN Stellen) statt einzelne Personen unsichtbar zu
        lassen.
        """
        if not contact_id:
            return request.env['res.partner'].browse()
        return request.env['res.partner'].search([
            ('id', '=', contact_id),
            ('commercial_partner_id', '=', verband.id),
            ('id', '!=', verband.id),
            ('is_company', '=', False),
            ('type', '=', 'contact'),
            ('active', '=', True),
        ], limit=1)

    @staticmethod
    def _verband_locked_contact_ids(contacts):
        """IDs der Ansprechpersonen, an denen ein Portalzugang hängt.

        Das Template braucht sie, um Name und E-Mail dieser Personen als
        gesperrt zu kennzeichnen und den Grund danebenzuschreiben (siehe
        CONTACT_WRITABLE_FIELDS_WITH_PORTAL_ACCESS). Die Sperre selbst wirkt
        serverseitig in _verband_save_contact — das hier ist nur die Anzeige.

        sudo() ausschließlich zum LESEN: Portalnutzer dürfen res.users nicht
        lesen, die Frage „hat diese Person einen Zugang?" wäre sonst nicht zu
        beantworten. Gelesen wird nur die Verknüpfung, kein einziges Feld des
        Benutzerkontos, und nur an Kontakten des eigenen Verbands.
        """
        if not contacts:
            return []
        return contacts.sudo().filtered('user_ids').ids

    @staticmethod
    def _verband_member_info(verband):
        """Die vom KJR festgestellten Mitgliedsangaben — fertig aufbereitet.

        Das ist die EINZIGE Brücke, über die diese Angaben ins Template
        gelangen, und sie liefert bewusst nur Text, Zahl und Ja/Nein — kein
        Recordset. Der Grund steht im Modul-Docstring von
        models/res_partner.py: kjr_member_type, kjr_member_number,
        kjr_active_since und kjr_vr_votes tragen `groups='base.group_user'`.
        Odoo 19 prüft das schon beim LESEN (_check_field_access aus
        _fetch_field), ein Portalnutzer bekommt also einen AccessError — und
        zwar mitten im Rendern, was die ganze Seite mit HTTP 500 beendet. Ein
        sudo()-Recordset ins Template durchzureichen würde zwar auch
        funktionieren, aber jeden späteren `verband_ro.<irgendwas>`-Zugriff im
        QWeb zu einer unbemerkten Rechteumgehung machen. Deshalb dieser Weg:
        was das Template nicht in der Hand hat, kann es auch nicht falsch
        benutzen.

        sudo() steht hier ausschließlich für LESEN. Gelesen wird nur der eigene,
        aus der Session abgeleitete Verbandssatz; geschrieben werden diese
        Felder nie (VERBAND_WRITABLE_FIELDS).

        kjr_vr_right trägt kein groups= und wäre auch direkt lesbar; es läuft
        trotzdem über diesen Weg mit, damit die Karte „Mitgliedschaft im
        Kreisjugendring" genau eine Quelle hat.
        """
        verband_sudo = verband.sudo()
        member_types = dict(
            verband_sudo._fields['kjr_member_type']._description_selection(request.env)
        )
        return {
            'name': verband_sudo.name or '',
            'member_type': member_types.get(verband_sudo.kjr_member_type) or '',
            'member_number': verband_sudo.kjr_member_number or '',
            'active_since': (
                verband_sudo.kjr_active_since.strftime('%d.%m.%Y')
                if verband_sudo.kjr_active_since else ''
            ),
            'vr_right': bool(verband_sudo.kjr_vr_right),
            # Historischer Altwert ohne fachliche Wirkung; das Template zeigt
            # ihn nur, wenn wirklich etwas darin steht (siehe Kommentar dort).
            'vr_votes': verband_sudo.kjr_vr_votes or 0,
        }

    @staticmethod
    def _kjr_office_info():
        """Kontaktdaten der Geschäftsstelle für die Verweise auf der Seite.

        Wird ausdrücklich vom Controller geliefert und nicht im Template aus
        `res_company` gezogen: dieser Wert steht nur im Website-Kontext zur
        Verfügung, und die Seite verweist an mehreren Stellen auf „melden Sie
        es der Geschäftsstelle". Ein Verweis auf eine Stelle, deren Kontaktdaten
        nirgends stehen, ist keine Hilfe.

        sudo() zum Lesen: res.company ist für Portalnutzer nicht durchgängig
        lesbar. Gelesen werden ausschließlich Name, Telefon und E-Mail der
        eigenen Firma — die öffentlichen Kontaktdaten des Kreisjugendrings.
        Nicht gepflegte Angaben liefert die Methode als leeren Text; das
        Template setzt dann sichtbar „wird vom KJR ergänzt" statt eine Nummer zu
        erfinden.
        """
        company = request.env.company.sudo()
        return {
            'name': company.name or '',
            'phone': company.phone or '',
            'email': company.email or '',
        }

    def _verband_values(self, verband):
        """Formularwerte aus dem gespeicherten Stand (Erstaufruf und Sticky-Basis)."""
        values = {}
        for fname in self._partner_fields(VERBAND_WRITABLE_FIELDS):
            value = verband[fname]
            values[fname] = '' if value in (False, None) else str(value)
        return values

    def _verband_locked_fields(self, verband):
        """Felder des Verbandssatzes, die im Portal gesperrt sind.

        Nur relevant, wenn der Portalzugang direkt auf der Organisation liegt —
        dann ist die E-Mail der Weg zur Kontoübernahme über „Passwort vergessen".
        sudo(): user_ids ist für Portalnutzer nicht lesbar, gebraucht wird nur,
        OB ein Zugang existiert.
        """
        if verband and verband.sudo().user_ids:
            return VERBAND_LOCKED_FIELDS_WITH_PORTAL_ACCESS
        return ()

    def _render_verband(self, verband, values, errors, success=None, warning=None):
        """Einzige Renderstelle der Seite — Erstaufruf wie Fehlerpfad.

        Analog zu _render_apply_form in website.py: ein einziger Ausgang, damit
        kein Rückweg einen Kontextwert vergisst. Welche Schlüssel das Template
        erwartet, steht als Kontrakt im Docstring von portal_my_verband und
        wortgleich im Kopfkommentar des Templates. Wer hier einen Schlüssel
        ergänzt oder umbenennt, zieht BEIDE Stellen nach.
        """
        contacts = self._verband_contacts(verband)
        locked = self._verband_locked_fields(verband)
        return request.render('kjr_grant.portal_my_verband', {
            'page_name': 'kjr_verband',
            'verband': verband,
            'member_info': self._verband_member_info(verband),
            'office': self._kjr_office_info(),
            'contacts': contacts,
            'locked_contact_ids': self._verband_locked_contact_ids(contacts),
            'delegates': self._verband_delegates(verband),
            # Gesperrte Felder fallen auch aus den Pflichtangaben — sonst trüge
            # ein Feld ein Sternchen, das der Nutzer gar nicht füllen kann.
            'locked_fields': locked,
            'required_fields': tuple(
                f for f in VERBAND_REQUIRED_FIELDS if f not in locked),
            'values': values,
            'errors': errors,
            'success': success,
            'warning': warning,
        })

    def _render_verband_no_member(self):
        """Seite für Nutzer ohne Mitgliedsverband.

        Kein 404 und kein Zugriffsfehler: Kooperationspartner, Mieter und
        Entleiher haben ebenfalls einen Portalzugang. In „Mein Konto" sehen sie
        die Kachel nicht (der Zähler steht auf 0), über die direkte Adresse
        landen sie aber hier — und sollen dann einen verständlichen Hinweis auf
        die Geschäftsstelle sehen statt einer Fehlerseite. Der Kontext trägt
        dieselben Schlüssel wie der Normalfall, damit das Template nicht auf
        einen fehlenden Wert läuft.
        """
        return request.render('kjr_grant.portal_my_verband', {
            'page_name': 'kjr_verband',
            'verband': False,
            'member_info': {},
            'office': self._kjr_office_info(),
            'contacts': [],
            'locked_contact_ids': [],
            'delegates': [],
            'locked_fields': (),
            'required_fields': (),
            'values': {},
            'errors': {},
            'success': None,
            'warning': None,
        })

    @http.route(
        '/my/verband', type='http', auth='user', website=True,
        methods=['GET', 'POST'],
    )
    def portal_my_verband(self, **post):
        """Verbandsdaten ansehen und pflegen.

        ══════════════════════════════════════════════════════════════════════
        KONTRAKT ZWISCHEN DIESEM CONTROLLER UND
        views/portal_templates.xml → kjr_grant.portal_my_verband
        ══════════════════════════════════════════════════════════════════════
        Diese Seite ist einmal auseinandergelaufen — Controller und Template
        waren gegen zwei verschiedene Namenssätze gebaut, die Seite endete für
        jeden Portalnutzer mit HTTP 500 und die Kontaktformulare taten
        wortlos nichts. Deshalb steht die Vereinbarung hier UND wortgleich im
        Kopfkommentar des Templates. Wer einen Namen ändert, ändert beide.

        KONTEXT, den jede Renderstelle liefert (siehe _render_verband):
          verband             res.partner oder False — False nur auf der
                              Hinweisseite für Nutzer ohne Mitgliedsverband.
                              Immer aus der Session
                              (_kjr_verband), NIE aus dem POST.
          member_info         dict — die vom KJR festgestellten Angaben, fertig
                              aufbereitet: name, member_type, member_number,
                              active_since (Text tt.mm.jjjj), vr_right (bool),
                              vr_votes (int). Das Template greift für diese
                              Angaben NIE direkt auf den Record zu; sie tragen
                              groups='base.group_user' und ein Portalnutzer darf
                              sie nicht lesen (siehe _verband_member_info).
          office              dict — name, phone, email der Geschäftsstelle.
          contacts            res.partner-Recordset der Ansprechpersonen.
          locked_contact_ids  Liste von IDs: Ansprechpersonen MIT Portalzugang.
                              An ihnen sind Name und E-Mail gesperrt.
          delegates           res.partner-Recordset der gemeldeten Delegierten.
          required_fields     Feldnamen, die das Formular als Pflicht kennzeichnet
                              (identisch mit der serverseitigen Prüfung).
          values              dict der zuletzt abgeschickten Werte (Sticky nach
                              einem Fehler). Enthält immer 'action', bei
                              Kontaktvorgängen zusätzlich 'contact_id',
                              'contact_is_delegate' und ggf. 'archive_warning'.
          errors              dict {feldname: meldung}, Schlüssel 'global' für
                              formularübergreifende Meldungen.
          success / warning   optionale Meldungstexte (Klartext, kein HTML).

        ACTIONS, die das Template sendet — genau diese vier, keine Synonyme:
          verband_save    Anschrift und Kontaktdaten des Verbands
                          (street, street2, zip, city, phone, email, website)
          contact_create  contact_name, contact_function, contact_email,
                          contact_phone, contact_is_delegate
          contact_save    dieselben Felder + contact_id
          contact_delete  contact_id [+ contact_delete_confirm bei Rückfrage]

        GET zeigt das Formular, POST speichert; welcher Teil, entscheidet
        ausschließlich das versteckte Feld `action` — nicht das Vorhandensein
        einzelner Werte, sonst wirkte ein leeres Kontaktformular beim Speichern
        der Adresse mit. Ein POST ohne bekannte Aktion speichert bewusst nichts
        und sagt das auch: still auf die Seite zurückzuleiten hat genau den
        Fehler verdeckt, der diese Seite unbrauchbar gemacht hat.
        """
        verband = self._kjr_verband()
        if not verband:
            return self._render_verband_no_member()

        if request.httprequest.method == 'POST':
            action = (post.get('action') or '').strip()
            if action in ('contact_create', 'contact_save'):
                return self._verband_save_contact(verband, post)
            if action == 'contact_delete':
                return self._verband_archive_contact(verband, post)
            if action == 'verband_save':
                return self._verband_save_data(verband, post)
            _logger.warning(
                '/my/verband: unbekannte Aktion %r von Benutzer %s',
                action, request.env.user.login,
            )
            return self._render_verband(
                verband, self._verband_values(verband),
                {'global': 'Das abgeschickte Formular konnte keiner Aktion zugeordnet '
                           'werden — es wurde nichts gespeichert. Bitte laden Sie die '
                           'Seite neu und versuchen Sie es noch einmal. Bleibt es dabei, '
                           'melden Sie es bitte der KJR-Geschäftsstelle.'},
            )

        # GET nach dem Speichern (Post/Redirect/Get): `message` trägt nur einen
        # Schlüssel, ausgegeben wird ausschließlich der hinterlegte Text — der
        # Parameterwert selbst landet nie in der Seite.
        return self._render_verband(
            verband, self._verband_values(verband), {},
            success=VERBAND_MESSAGES.get(post.get('message')),
        )

    def _verband_save_data(self, verband, post):
        """Kontakt- und Adressdaten des Verbands speichern.

        Wie bei den Ansprechpersonen gilt auch hier die Sperre gegen
        Kontoübernahme: Hängt an DIESEM Datensatz selbst ein Portalzugang — das
        ist der Fall, wenn der Login direkt auf der Organisation angelegt wurde
        statt auf einer Person —, darf die E-Mail-Adresse im Portal nicht
        geändert werden. res.users erbt von res.partner, user.email IST
        partner.email: wer sie umbiegt, bekommt über „Passwort vergessen" die
        Reset-Mail und damit das Konto. Die erste Fassung der Sperre deckte nur
        _verband_save_contact ab und ließ genau diesen Weg offen.
        """
        errors = {}
        writable = VERBAND_WRITABLE_FIELDS
        # sudo(): user_ids ist für Portalnutzer nicht lesbar, gebraucht wird nur
        # die Information, OB ein Zugang existiert.
        if verband.sudo().user_ids:
            writable = tuple(
                f for f in VERBAND_WRITABLE_FIELDS
                if f not in VERBAND_LOCKED_FIELDS_WITH_PORTAL_ACCESS)
        vals = self._collect_partner_vals(post, self._partner_fields(writable))
        # Ein gesperrtes Feld darf nicht als „Pflichtangabe fehlt" zurückkommen —
        # der Nutzer kann es gar nicht liefern.
        required = tuple(f for f in VERBAND_REQUIRED_FIELDS if f in writable)
        # Eingaben für den Fehlerfall festhalten: nach einer abgelehnten PLZ soll
        # niemand das ganze Formular neu tippen müssen.
        values = dict(vals)
        values['action'] = 'verband_save'
        self._validate_partner_vals(vals, required, errors)
        if errors:
            return self._render_verband(verband, values, errors)

        changes = self._changed_fields(verband, vals)
        if not changes:
            return request.redirect('/my/verband?message=unchanged')

        # sudo(): Portalnutzer haben auf res.partner nur Leserecht
        # (base.access_res_partner_portal; die Regel res_partner_portal_public_rule
        # erlaubt ausdrücklich kein Schreiben) — ohne sudo scheitert jedes
        # Speichern. Vertretbar ist es hier, weil vorher beides feststeht: der
        # Zielsatz stammt aus der Session (_kjr_verband, nie aus dem POST) und
        # geschrieben werden ausschließlich Felder der Whitelist.
        verband.sudo().write({change['field']: change['new'] or False for change in changes})
        self._log_portal_changes(
            verband,
            '%s hat die Verbandsdaten im Portal geändert:' % request.env.user.name,
            changes,
        )
        return request.redirect('/my/verband?message=saved')

    def _verband_save_contact(self, verband, post):
        """Ansprechperson anlegen oder ändern, inklusive Delegiertenstatus."""
        errors = {}
        vals = self._collect_partner_vals(
            post, self._partner_fields(CONTACT_WRITABLE_FIELDS), key_prefix='contact_',
        )
        # Sticky-Werte: das Hauptformular aus dem Bestand (es wurde nicht
        # abgeschickt), das Kontaktformular aus der Eingabe.
        values = self._verband_values(verband)
        values.update({'contact_%s' % key: value for key, value in vals.items()})
        contact_id = _parse_int(post.get('contact_id'))
        values['contact_id'] = str(contact_id or '')
        values['contact_is_delegate'] = bool(post.get('contact_is_delegate'))
        # Das Template entscheidet über `values['action']`, WELCHES der drei
        # Kontaktformulare nach einem Fehler wieder aufgeklappt und mit den
        # Eingaben befüllt wird (contact_create = "Neue Ansprechperson",
        # contact_save = die Zeile genau dieses Kontakts). Ohne diesen Wert
        # stünde die Meldung nur in der Sammelbox oben und der Nutzer müsste
        # das Formular neu suchen und neu tippen.
        values['action'] = 'contact_save' if contact_id else 'contact_create'

        contact = request.env['res.partner'].browse()
        locked = False
        if contact_id:
            contact = self._verband_contact(verband, contact_id)
            if not contact:
                errors['contact_id'] = (
                    'Diese Ansprechperson gehört nicht zu Ihrem Verband und kann hier '
                    'nicht geändert werden. Bitte wenden Sie sich an die '
                    'KJR-Geschäftsstelle.'
                )
            else:
                # Kontoübernahme im eigenen Verband verhindern: hängt an der
                # Person ein Portalzugang, sind Name und E-Mail gesperrt (siehe
                # CONTACT_WRITABLE_FIELDS_WITH_PORTAL_ACCESS). Die gesperrten
                # Werte fliegen hier aus dem Wertedict — damit lösen sie weder
                # ein write() noch eine Pflichtfeld-Meldung aus, und Funktion
                # und Telefon bleiben normal pflegbar. Das Template zeigt die
                # beiden Felder für diese Personen schreibgeschützt mit
                # Begründung; diese Prüfung hier ist die wirksame, weil ein
                # handgebautes POST das Formular nicht braucht.
                # sudo() nur zum Lesen: Portalnutzer dürfen res.users nicht lesen.
                locked = bool(contact.sudo().user_ids)
                if locked:
                    for fname in CONTACT_WRITABLE_FIELDS:
                        if fname not in CONTACT_WRITABLE_FIELDS_WITH_PORTAL_ACCESS:
                            vals.pop(fname, None)
                            # Auch aus den Sticky-Werten nehmen: nach einem
                            # Fehler soll im gesperrten Feld der gespeicherte
                            # Stand stehen, nicht der abgewiesene Eingabewert.
                            values.pop('contact_%s' % fname, None)
        if not contact_id:
            # ANLEGEN: jede Pflichtangabe muss geprüft werden, auch wenn das Feld
            # im POST überhaupt nicht vorkommt. _collect_partner_vals nimmt
            # bewusst nur mitgeschickte Felder auf (Schutz vor Feldlöschung durch
            # Teil-POST) — beim Anlegen gäbe es dann aber nichts zu prüfen, und
            # ein handgebautes POST ohne `contact_name` liefe ungebremst in die
            # Datenbankbedingung res_partner_check_name ("Contacts require a
            # name", base/models/res_partner.py) und damit in eine
            # Fehlerseite statt in eine verständliche Meldung am Feld.
            # Beim ÄNDERN bleibt es beim bisherigen Verhalten: was nicht
            # mitgeschickt wurde, bleibt unangetastet.
            for fname in CONTACT_REQUIRED_FIELDS:
                vals.setdefault(fname, '')
        self._validate_partner_vals(
            vals, CONTACT_REQUIRED_FIELDS, errors, key_prefix='contact_',
        )
        if errors:
            return self._render_verband(verband, values, errors)

        user_name = request.env.user.name
        # Bei gesperrten Kontakten steht der Name nicht mehr in vals — für die
        # Protokollzeile zählt ohnehin der gespeicherte Name.
        contact_name = contact.name if contact else (vals.get('name') or '')
        if contact:
            changes = self._changed_fields(contact, vals)
            if changes:
                # sudo() wie in _verband_save_data. Die Zugehörigkeit des Kontakts
                # ist über _verband_contact geprüft, die Felder stammen aus der
                # Whitelist.
                contact.sudo().write({c['field']: c['new'] or False for c in changes})
            header = '%s hat die Ansprechperson „%s" im Portal geändert:' % (
                user_name, contact_name,
            )
            message_key = 'contact_saved'
            # Nur melden, wenn der Nutzer an den gesperrten Feldern tatsächlich
            # etwas ändern WOLLTE — sonst stünde bei jedem Speichern eine
            # Erklärung für ein Problem, das niemand hatte.
            if locked and self._locked_fields_touched(contact, post):
                message_key = 'contact_saved_locked'
        else:
            create_vals = dict(vals)
            create_vals.update({
                # parent_id kommt NIE aus dem Request: ein neuer Kontakt hängt
                # immer am eigenen Verband. Damit ist auch commercial_partner_id
                # gesetzt, worüber jede spätere Änderung geprüft wird.
                'parent_id': verband.id,
                'is_company': False,
                'type': 'contact',
            })
            contact = request.env['res.partner'].sudo().create(create_vals)
            changes = [
                {'field': fname, 'label': PARTNER_FIELD_LABELS.get(fname, fname),
                 'old': '', 'new': value}
                for fname, value in vals.items() if value
            ]
            header = '%s hat die Ansprechperson „%s" im Portal angelegt:' % (
                user_name, contact_name,
            )
            message_key = 'contact_created'

        # Das Häkchen „Delegierte/r" steht im Formular NUR bei Verbänden MIT
        # Vertretungsrecht (Template: t-if member_info['vr_right']). Ohne dieses
        # Recht schickt kein Formular der Seite `contact_is_delegate` mit — ein
        # ungeprüfter Aufruf würde daraus „nicht mehr delegiert" ableiten und bei
        # JEDEM Speichern einer Ansprechperson eine im Backend gepflegte
        # Altmeldung stillschweigend lösen, obwohl die Seite die Rubrik gar nicht
        # zeigt. Deshalb hier dieselbe Bedingung wie im Template. Das Lösen einer
        # Meldung beim ENTFERNEN einer Person (_verband_archive_contact) läuft
        # bewusst weiterhin unabhängig davon.
        if verband.kjr_vr_right:
            changes += self._set_delegate(
                verband, contact, bool(post.get('contact_is_delegate')),
            )
        if not changes:
            # Auch wenn nichts zu speichern war: hat der Nutzer an einem
            # gesperrten Feld gedreht, muss er erfahren, warum sein Eintrag
            # nicht angekommen ist — „nichts zu speichern" wäre hier irreführend.
            if message_key == 'contact_saved_locked':
                return request.redirect('/my/verband?message=contact_saved_locked')
            return request.redirect('/my/verband?message=unchanged')
        self._log_portal_changes(verband, header, changes)
        return request.redirect('/my/verband?message=%s' % message_key)

    @staticmethod
    def _locked_fields_touched(contact, post):
        """Hat der Nutzer an einem gesperrten Feld überhaupt etwas geändert?

        Gesperrt sind Name und E-Mail von Personen mit Portalzugang. Weil das
        Formular sie schreibgeschützt, aber mit Wert anzeigt, kommen sie
        unverändert im POST wieder an — ein bloßes Vorhandensein sagt also
        nichts. Verglichen wird deshalb gegen den gespeicherten Stand.
        """
        for fname in CONTACT_WRITABLE_FIELDS:
            if fname in CONTACT_WRITABLE_FIELDS_WITH_PORTAL_ACCESS:
                continue
            key = 'contact_%s' % fname
            if key not in post:
                continue
            submitted = (post.get(key) or '').strip()
            stored = contact[fname] if fname in contact._fields else False
            stored_text = '' if stored in (False, None) else str(stored)
            if submitted != stored_text:
                return True
        return False

    @staticmethod
    def _set_delegate(verband, contact, is_delegate):
        """Delegiertenstatus setzen; liefert die Änderung als Chatter-Zeile.

        Delegierte hängen als Many2many am Verband (kjr_vr_delegate_ids).
        Geschrieben wird ausschließlich dieses eine Feld — kjr_vr_right und
        kjr_vr_votes sind Feststellungen des KJR und dürfen sich hierdurch nicht
        ändern. Deshalb ein gezieltes write() mit Command.link/unlink und kein
        Wertedict aus dem Formular. Command.unlink löst nur die Verknüpfung, der
        Kontakt selbst bleibt bestehen.

        ANMELDEN kann nur ein Verband MIT Vertretungsrecht (kjr_vr_right). Ohne
        dieses Recht gibt es für ihn in der Vollversammlung keine Vertretung,
        die er melden könnte; die Seite blendet die Rubrik deshalb aus. Diese
        Prüfung hier ist die wirksame — ein ausgeblendetes Formularfeld hält ein
        handgebautes POST nicht auf. ABMELDEN bleibt hier immer möglich: ein
        Altbestand aus dem Backend muss sich lösen lassen, auch wenn das
        Vertretungsrecht inzwischen weggefallen ist (sonst bliebe eine
        stillgelegte Person dauerhaft als Delegierte verknüpft) — deshalb greift
        die Prüfung nur beim Anmelden.

        ACHTUNG beim Aufrufen: `is_delegate=False` heißt hier „abmelden" und
        nicht „das Formular hat dazu nichts gesagt". Wer diese Methode aus einem
        Formular heraus aufruft, das die Rubrik gar nicht anzeigt, löst damit
        eine bestehende Meldung — siehe die Bedingung in
        _verband_save_contact.
        """
        if is_delegate and not verband.kjr_vr_right:
            return []
        was_delegate = contact.id in verband.kjr_vr_delegate_ids.ids
        if was_delegate == is_delegate:
            return []
        command = Command.link(contact.id) if is_delegate else Command.unlink(contact.id)
        # sudo(): Schreibrecht auf res.partner, siehe _verband_save_data.
        verband.sudo().write({'kjr_vr_delegate_ids': [command]})
        return [{
            'field': 'kjr_vr_delegate_ids',
            'label': 'Vertretung in der Vollversammlung (%s)' % (contact.name or ''),
            'old': 'ja' if was_delegate else 'nein',
            'new': 'ja' if is_delegate else 'nein',
        }]

    @staticmethod
    def _verband_archive_hints(verband, contact):
        """Was hängt an dieser Person noch? Liefert fertige Sätze für die Rückfrage.

        Gezählt wird nur, was im Modul TATSÄCHLICH auf den Kontakt zeigt:
        Juleica-Karten (kjr.juleica.partner_id), Ehrenamtsstunden
        (kjr.volunteer.log.partner_id), die Delegiertenrolle beim eigenen
        Verband, Aufgaben in einer noch nicht durchgeführten Vollversammlung
        (Versammlungsleitung, Protokollführung, Stimmzählung) und Kandidaturen.

        Zuschussanträge stehen bewusst NICHT in der Liste: kjr.grant.application
        führt Ansprechperson, E-Mail und Telefon als freie Textfelder ohne
        Verknüpfung zum Kontakt. Eine Zählung wäre geraten, und geraten wird auf
        dieser Seite nichts.

        sudo() ausschließlich zum ZÄHLEN: auf kjr.juleica, kjr.volunteer.log und
        kjr.assembly hat ein Portalnutzer kein Leserecht. Nach außen geht nur
        die Anzahl, und nur zu einer Person des eigenen Verbands, die der
        Nutzer ohnehin gerade vor sich hat — keine Inhalte, keine fremden Sätze.
        """
        env = request.env
        hints = []

        juleica_count = env['kjr.juleica'].sudo().search_count([
            ('partner_id', '=', contact.id),
        ])
        if juleica_count == 1:
            hints.append('Auf diese Person ist eine Juleica-Karte erfasst. Der Eintrag '
                         'bleibt bestehen, samt Ablaufdatum und Erinnerung der '
                         'Geschäftsstelle — die Person selbst taucht dort aber in keiner '
                         'Auswahlliste mehr auf.')
        elif juleica_count > 1:
            hints.append('Auf diese Person sind %d Juleica-Karten erfasst. Die Einträge '
                         'bleiben bestehen, samt Ablaufdatum und Erinnerung der '
                         'Geschäftsstelle — die Person selbst taucht dort aber in keiner '
                         'Auswahlliste mehr auf.' % juleica_count)

        volunteer_count = env['kjr.volunteer.log'].sudo().search_count([
            ('partner_id', '=', contact.id),
        ])
        if volunteer_count == 1:
            hints.append('Zu dieser Person ist ein Eintrag über Ehrenamtsstunden erfasst. '
                         'Der Eintrag bleibt bestehen.')
        elif volunteer_count > 1:
            hints.append('Zu dieser Person sind %d Einträge über Ehrenamtsstunden erfasst. '
                         'Die Einträge bleiben bestehen.' % volunteer_count)

        if contact.id in verband.kjr_vr_delegate_ids.ids:
            if len(verband.kjr_vr_delegate_ids) == 1:
                hints.append('Diese Person ist derzeit Ihre einzige gemeldete Delegierte '
                             'bzw. Ihr einziger gemeldeter Delegierter für die '
                             'Vollversammlung. Mit dem Entfernen ist für Ihren Verband '
                             'niemand mehr gemeldet.')
            else:
                hints.append('Diese Person ist als Delegierte/r für die Vollversammlung '
                             'gemeldet. Die Meldung wird mit entfernt.')

        assembly_count = env['kjr.assembly'].sudo().search_count([
            ('state', 'in', ('draft', 'invited')),
            '|', '|',
            ('chair_id', '=', contact.id),
            ('secretary_id', '=', contact.id),
            ('teller_ids', 'in', [contact.id]),
        ])
        if assembly_count:
            hints.append('Für %s Vollversammlung%s, die noch aussteht, ist diese Person '
                         'für eine Aufgabe eingeplant (Versammlungsleitung, '
                         'Protokollführung oder Stimmzählung). Bitte melden Sie das der '
                         'Geschäftsstelle.'
                         % (assembly_count, 'en' if assembly_count > 1 else ''))

        candidate_count = env['kjr.assembly.candidate'].sudo().search_count([
            ('partner_id', '=', contact.id),
        ])
        if candidate_count:
            hints.append('Diese Person ist mit %s Kandidatur%s in den Wahlunterlagen der '
                         'Vollversammlung verknüpft. Die Einträge bleiben unverändert.'
                         % (candidate_count, 'en' if candidate_count > 1 else ''))
        return hints

    def _verband_archive_contact(self, verband, post):
        """Ansprechperson entfernen — archivieren statt löschen.

        An einem Kontakt hängen Zuschussanträge, Einladungen und Anwesenheiten
        der Vollversammlung sowie Chatter-Einträge. Ein unlink() würde diese
        Bezüge zerreißen bzw. an den Fremdschlüsseln scheitern, und die Historie
        muss für die Geschäftsstelle nachvollziehbar bleiben. Archivieren nimmt
        die Person aus allen Auswahllisten und Übersichten, lässt die
        Vergangenheit aber unangetastet.

        Hängen an der Person noch aktive Bezüge (Juleica-Karte,
        Ehrenamtsstunden, Delegiertenrolle, Aufgaben in einer geplanten
        Vollversammlung), kommt zuerst eine Rückfrage mit genau diesen Punkten.
        Bewusst KEINE Sperre: wer im Verband ausscheidet, scheidet aus, und die
        Liste gehört dem Verband. Aber wer ihn stilllegt, soll wissen, dass
        z. B. eine gültige Juleica-Karte auf ihn ausgestellt ist und deren
        Ablauferinnerung weiterläuft, während er aus allen Auswahllisten
        verschwindet. Gesperrt bleibt nur der Fall Portalzugang — dort ginge es
        nicht um eine Liste, sondern um ein Benutzerkonto.
        """
        contact_id = _parse_int(post.get('contact_id'))
        values = self._verband_values(verband)
        # Damit das Template den richtigen Abschnitt wieder aufklappt.
        values['action'] = 'contact_delete'
        values['contact_id'] = str(contact_id or '')
        contact = self._verband_contact(verband, contact_id)
        if not contact:
            return self._render_verband(verband, values, {'contact_id': (
                'Diese Ansprechperson gehört nicht zu Ihrem Verband und kann hier nicht '
                'entfernt werden. Bitte wenden Sie sich an die KJR-Geschäftsstelle.'
            )})
        # sudo() nur zum Lesen: Portalnutzer dürfen res.users nicht lesen, die
        # Prüfung wäre sonst nicht möglich. Konservativ, weil an dieser Person
        # ein Portalzugang hängt — ob dieser gesperrt oder übertragen wird,
        # entscheidet die Geschäftsstelle, nicht der Verband.
        # TODO(KJR): Entscheidung einholen, ob ein Verband eine Person MIT
        # Portalzugang selbst entfernen darf. Bis dahin gesperrt — sonst könnte
        # sich ein Vorstandswechsel selbst aussperren bzw. ein aktiver Zugang
        # ins Leere zeigen.
        if contact.sudo().user_ids:
            return self._render_verband(verband, values, {'contact_id': (
                'Für diese Person besteht ein Portalzugang. Sie kann hier nicht '
                'entfernt werden — bitte wenden Sie sich an die KJR-Geschäftsstelle.'
            )})

        contact_name = contact.name or ''
        # Rückfrage, solange sie nicht schon beantwortet ist. `contact_delete_confirm`
        # setzt ausschließlich der Bestätigungsschritt des Formulars.
        hints = self._verband_archive_hints(verband, contact)
        if hints and not post.get('contact_delete_confirm'):
            values['archive_warning'] = hints
            return self._render_verband(
                verband, values, {},
                warning='Bitte kurz prüfen: an %s hängen noch Einträge im '
                        'Kreisjugendring-System.' % (contact_name or 'dieser Person'),
            )

        # Erst die Vertretung lösen (liest die Delegiertenliste des Verbands),
        # dann archivieren: eine archivierte Person darf nicht als Delegierte
        # stehen bleiben, sonst gingen Einladungen zur Vollversammlung ins Leere.
        changes = self._set_delegate(verband, contact, False)
        # sudo(): Schreibrecht auf res.partner, siehe _verband_save_data. Der
        # Kontakt ist über _verband_contact als eigener geprüft.
        contact.sudo().write({'active': False})
        changes.append({
            'field': 'active',
            'label': 'Ansprechperson „%s"' % contact_name,
            'old': 'aktiv',
            'new': 'entfernt (archiviert)',
        })
        self._log_portal_changes(
            verband,
            '%s hat eine Ansprechperson im Portal entfernt:' % request.env.user.name,
            changes,
        )
        return request.redirect('/my/verband?message=contact_archived')
