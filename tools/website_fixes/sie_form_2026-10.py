# -*- coding: utf-8 -*-
"""Sie-Form und Odoo-Standardseiten auf der Website (Stand Oktober 2026).

Entscheidung 4 (Termin 13.10.2026): Website- und Systemtexte sprechen die
Besucher:innen mit Sie an. Das Skript korrigiert die Stellen, die KLGM selbst
in die Website-Daten gelegt hat, und nimmt Odoo-Mustertexte vom Netz. Es
gestaltet nichts um.

Teil 1  Fußbereich-Code (website.custom_code_footer der Website):
        Den Skriptblock entfernen, der den Cookie-Platzhalter für gesperrte
        Drittinhalte von „müssen Sie“ auf „müsst ihr“ umschreibt. Odoo liefert
        den Text schon in Sie-Form. Der zweite Block (doppelter Link auf die
        Cookie-Richtlinien) bleibt unverändert.
Teil 2  Cookie-Banner (website-eigene Ansicht website.cookies_bar):
        „damit sie für euch besser funktioniert“ -> „damit sie für Sie besser
        funktioniert“. Es wird nur dieser Satz geändert, Klassen und Aufbau
        bleiben gleich.
Teil 3  Odoo-Standardseiten:
        /terms (englische Muster-AGB) und /website/info (Liste der installierten
        Apps) bekommen je eine Weiterleitung vom Typ „404 Not Found“
        (Website > Konfiguration > Weiterleitungen). Odoo nimmt die Route dann
        aus dem Routing und damit auch aus der sitemap.xml. Zusätzlich wird die
        Einstellung „Standard-Geschäftsbedingungen“ (account.use_invoice_terms)
        ausgeschaltet. Sonst schreibt Odoo in jeden neuen Auftrag „Terms &
        Conditions: …/terms“ und verlinkt damit eine Seite, die es nicht mehr
        gibt. /shop bleibt unverändert (wird für den Checkout gebraucht, siehe
        README).
Teil 4  Fußbereich-Code als Block im <body>:
        Odoo parst den Fußbereich-Code für Besucher:innen ohne Cookie-Zustimmung
        mit lxml (website._control_third_party_trackers_in_html). Besteht er nur
        aus <script>, legt lxml ihn in ein <html><head> und genau so landet er
        im <body>. Das Skript umschließt den Code mit <div class="d-none">.
        Das Element ist unsichtbar, das Skript darin läuft wie bisher.
Am Ende wird der zwischengespeicherte Sitemap-Anhang der Website gelöscht.
Odoo erzeugt ihn beim nächsten Aufruf von /sitemap.xml neu.

Autor:   KLGM UG (haftungsbeschraenkt), https://www.klgm-consulting.de
Lizenz:  OPL-1
Stand:   2026-10-22
Anleitung: tools/website_fixes/README.md, Abschnitt „Befund C“. Vor JEDER
Ausführung lesen.

AUSFÜHREN DARF DAS SKRIPT NUR EINE BERECHTIGTE PERSON auf dem Server bzw.
einer Server-Kopie, nach einem Snapshot. Nicht lokal, nicht durch den
Assistenten.

Betriebsarten (Umgebungsvariablen):
    (keine)                   Probelauf: rechnet alles durch, prüft und rollt
                              zurück. Ändert nichts.
    KJR_FIX_WRITE=1           schreibt (Backup-Datei zuerst) und committet nur,
                              wenn die Nachprüfung in Ordnung ist.
    KJR_WEBSITE_ID=<id>       Website (Vorgabe: die eine Website mit dem Code
                              aus Teil 1, auf der Produktion 3).
    KJR_KEEP_INVOICE_TERMS=1  account.use_invoice_terms NICHT ausschalten.
    KJR_FIX_OUT=<ordner>      Ablage für das Backup (Vorgabe: aktuelles
                              Verzeichnis). Datei: sie_form_backup_<zeit>.json

Aufruf (auf dem Server, NICHT lokal):
    odoo shell -d <db> --no-http < sie_form_2026-10.py                    # Probelauf
    KJR_FIX_WRITE=1 odoo shell -d <db> --no-http < sie_form_2026-10.py    # schreibt

Jeder Teil prüft vorher, ob er schon erledigt ist, und überspringt sich dann.
Ein zweiter Lauf ändert also nichts. Weicht ein Inhalt vom erwarteten Stand ab,
bricht das Skript ohne Änderung ab.
"""
import json
import os
import re
import time

from lxml import html as lxml_html

WRITE = os.environ.get('KJR_FIX_WRITE') == '1'
KEEP_INVOICE_TERMS = os.environ.get('KJR_KEEP_INVOICE_TERMS') == '1'
OUT = os.environ.get('KJR_FIX_OUT') or os.getcwd()

# Teil 1: Kennzeichen des zu entfernenden Skriptblocks (so im Feld gespeichert).
IHR_MARKER = 'm\\u00fcsst ihr optionale Cookies akzeptieren'
IHR_BLOCK_RE = re.compile(
    r'/\* Platzhalter fuer gesperrte Drittinhalte\..*?\*/\s*'   # Kommentar des Blocks
    r'\(function \(\) \{.*?' + re.escape(IHR_MARKER) + r'.*?\n\}\)\(\);[ \t]*\n\s*',
    re.S)
KEEP_MARKER = 'o_cookie_policy_link'   # zweiter Block, muss bleiben
WRAP_OPEN = '<div class="d-none">'
WRAP_CLOSE = '</div>'

# Teil 2
BANNER_KEY = 'website.cookies_bar'
BANNER_ALT = 'damit sie für euch besser funktioniert.'
BANNER_NEU = 'damit sie für Sie besser funktioniert.'

# Teil 3
REWRITE_404 = [
    ('/terms', 'KJR: Odoo-Muster-AGB (/terms) gesperrt'),
    ('/website/info', 'KJR: Odoo-Seite /website/info gesperrt'),
]
INVOICE_TERMS_PARAM = 'account.use_invoice_terms'


class Abbruch(Exception):
    pass


# ---------------------------------------------------------------- Teil 1 + 4
def neuer_fusscode(code):
    """Liefert (neuer_code, protokoll)."""
    log = []
    if IHR_MARKER in code:
        new, n = IHR_BLOCK_RE.subn('', code, count=1)
        if n != 1 or IHR_MARKER in new:
            raise Abbruch('Teil 1: Skriptblock mit „müsst ihr“ nicht eindeutig abgrenzbar.')
        if KEEP_MARKER not in new:
            raise Abbruch('Teil 1: zweiter Skriptblock (Cookie-Link) wäre mit entfernt worden.')
        log.append('Teil 1: Skriptblock „Platzhalter … müsst ihr“ entfernt (%d -> %d Zeichen)'
                   % (len(code), len(new)))
        code = new
    else:
        log.append('Teil 1: kein Skriptblock mit „müsst ihr“ (schon erledigt)')
    if code.strip() and not code.lstrip().startswith(WRAP_OPEN):
        if _als_html_dokument(code):
            code = '%s\n%s\n%s\n' % (WRAP_OPEN, code.strip('\n'), WRAP_CLOSE)
            log.append('Teil 4: Code mit %s…%s umschlossen' % (WRAP_OPEN, WRAP_CLOSE))
        else:
            log.append('Teil 4: Code wird nicht als <html><head> gerendert, keine Änderung')
    else:
        log.append('Teil 4: schon umschlossen bzw. leer')
    return code, log


def _als_html_dokument(code):
    """True, wenn Odoos lxml-Durchlauf den Code als <html><head>… ausgibt."""
    root = lxml_html.fromstring(str(code))
    return lxml_html.tostring(root, encoding='unicode').lstrip().startswith('<html')


def pruefe_fusscode(code):
    fehler = []
    if IHR_MARKER in code or 'ihr optionale Cookies' in code:
        fehler.append('Fußbereich-Code: ihr-Skript noch vorhanden')
    if KEEP_MARKER not in code:
        fehler.append('Fußbereich-Code: Cookie-Link-Skript fehlt')
    if code.strip() and _als_html_dokument(code):
        fehler.append('Fußbereich-Code: würde weiter als <html><head> gerendert')
    return fehler


# ---------------------------------------------------------------- Teil 2
def _raw_arch(view_id):
    env.cr.execute('SELECT arch_db FROM ir_ui_view WHERE id = %s', (view_id,))
    row = env.cr.fetchone()
    return (row and row[0]) or {}


def neue_banner_arch(arch):
    n = arch.count(BANNER_ALT)
    if n == 0 and BANNER_NEU in arch:
        return arch
    if n != 1:
        raise Abbruch('Teil 2: Satz „%s“ %d-mal gefunden (erwartet 1).' % (BANNER_ALT, n))
    return arch.replace(BANNER_ALT, BANNER_NEU)


def pruefe_banner(arch):
    fehler = []
    if BANNER_NEU not in arch:
        fehler.append('Cookie-Banner: Sie-Satz fehlt')
    if re.search(r'\b(euch|euer|eure|ihr)\b', re.sub(r'<[^>]+>', ' ', arch)):
        fehler.append('Cookie-Banner: noch ihr-Form')
    return fehler


# ---------------------------------------------------------------- Ablauf
def _website():
    Website = env['website']
    if os.environ.get('KJR_WEBSITE_ID'):
        website = Website.browse(int(os.environ['KJR_WEBSITE_ID'])).exists()
        if not website:
            raise Abbruch('KJR_WEBSITE_ID unbekannt.')
        return website
    sites = Website.search([]).filtered(
        lambda w: w.custom_code_footer and KEEP_MARKER in str(w.custom_code_footer))
    if len(sites) != 1:
        raise Abbruch('%d Websites mit dem KJR-Fußbereich-Code gefunden; bitte KJR_WEBSITE_ID setzen.'
                      % len(sites))
    return sites


def _banner_view(website):
    views = env['ir.ui.view'].with_context(active_test=False).search(
        [('key', '=', BANNER_KEY), ('website_id', '=', website.id)])
    if len(views) != 1:
        raise Abbruch('Teil 2: %d website-eigene Ansichten %s gefunden (erwartet 1).'
                      % (len(views), BANNER_KEY))
    return views


def main():
    website = _website()
    print('Website %s „%s“' % (website.id, website.name))
    Rewrite = env['website.rewrite'].with_context(active_test=False)
    Param = env['ir.config_parameter'].sudo()

    # ---- Bestand lesen
    env.cr.execute('SELECT custom_code_footer FROM website WHERE id = %s', (website.id,))
    code_alt = env.cr.fetchone()[0] or ''
    banner = _banner_view(website)
    banner_alt = _raw_arch(banner.id)
    rewrites_alt = Rewrite.search([('url_from', 'in', [u for u, _n in REWRITE_404]),
                                   '|', ('website_id', '=', False), ('website_id', '=', website.id)])
    param_alt = Param.get_param(INVOICE_TERMS_PARAM)
    sitemaps = env['ir.attachment'].sudo().search([
        ('type', '=', 'binary'), ('url', '=like', '/sitemap-%d-%%.xml' % website.id)])

    # ---- Plan
    code_neu, log = neuer_fusscode(code_alt)
    banner_neu = {lang: neue_banner_arch(arch) for lang, arch in banner_alt.items()}
    for line in log:
        print('  ' + line)
    for lang in sorted(banner_alt):
        print('  Teil 2: Ansicht %s (%s) %s' % (
            banner.id, lang, 'ändern' if banner_neu[lang] != banner_alt[lang] else 'schon Sie-Form'))
    plan_rewrites = []
    for url, name in REWRITE_404:
        vorhanden = rewrites_alt.filtered(lambda r: r.url_from == url)
        if vorhanden.filtered(lambda r: r.redirect_type == '404' and r.active):
            print('  Teil 3: %s schon gesperrt (website.rewrite %s)' % (url, vorhanden.ids))
        elif vorhanden:
            raise Abbruch('Teil 3: Für %s gibt es schon eine andere Weiterleitung %s, bitte prüfen.'
                          % (url, [(r.id, r.redirect_type, r.url_to, r.active) for r in vorhanden]))
        else:
            plan_rewrites.append((url, name))
            print('  Teil 3: %s bekommt eine 404-Weiterleitung' % url)
    if KEEP_INVOICE_TERMS:
        print('  Teil 3: %s bleibt %r (KJR_KEEP_INVOICE_TERMS=1)' % (INVOICE_TERMS_PARAM, param_alt))
    elif param_alt:
        print('  Teil 3: %s: %r -> aus' % (INVOICE_TERMS_PARAM, param_alt))
    else:
        print('  Teil 3: %s schon aus' % INVOICE_TERMS_PARAM)
    print('  Sitemap-Zwischenspeicher: %d Anhang/Anhänge %s' % (len(sitemaps), sitemaps.mapped('url')))

    # ---- Backup
    if WRITE:
        backup = os.path.join(OUT, 'sie_form_backup_%s.json' % time.strftime('%Y%m%d-%H%M%S'))
        with open(backup, 'w', encoding='utf-8') as fh:
            json.dump({
                'website_id': website.id,
                'website.custom_code_footer': code_alt,
                'ir.ui.view': {'id': banner.id, 'key': banner.key, 'arch_db': banner_alt},
                'website.rewrite': [{'id': r.id, 'url_from': r.url_from, 'url_to': r.url_to,
                                     'redirect_type': r.redirect_type, 'active': r.active}
                                    for r in rewrites_alt],
                'ir.config_parameter': {INVOICE_TERMS_PARAM: param_alt},
            }, fh, ensure_ascii=False, indent=1)
        print('Backup: %s' % backup)

    # ---- Schreiben (im Probelauf ebenso, danach Rollback)
    if code_neu != code_alt:
        website.write({'custom_code_footer': code_neu})
    if any(banner_neu[l] != banner_alt[l] for l in banner_alt):
        target = banner.with_context(no_cow=True)
        for lang in sorted(banner_alt, key=lambda l: (l != 'en_US', l)):
            current = _raw_arch(banner.id).get(lang)
            if current and not pruefe_banner(current):
                continue
            target.with_context(lang=lang).write({'arch_db': neue_banner_arch(current)})
            target.invalidate_recordset(['arch_db'])
    for url, name in plan_rewrites:
        Rewrite.create({'name': name, 'url_from': url, 'redirect_type': '404',
                        'website_id': website.id})
    if not KEEP_INVOICE_TERMS and param_alt:
        Param.set_param(INVOICE_TERMS_PARAM, False)
    sitemaps.unlink()

    # ---- Nachprüfung
    env.invalidate_all()
    env.cr.execute('SELECT custom_code_footer FROM website WHERE id = %s', (website.id,))
    fehler = pruefe_fusscode(env.cr.fetchone()[0] or '')
    for lang, arch in _raw_arch(banner.id).items():
        fehler += ['%s (%s)' % (f, lang) for f in pruefe_banner(arch)]
    for url, _n in REWRITE_404:
        if not Rewrite.search([('url_from', '=', url), ('redirect_type', '=', '404'),
                               ('website_id', '=', website.id)]):
            fehler.append('404-Weiterleitung fehlt: %s' % url)
    if not KEEP_INVOICE_TERMS and Param.get_param(INVOICE_TERMS_PARAM):
        fehler.append('%s noch an' % INVOICE_TERMS_PARAM)
    layout = env['ir.ui.view'].with_context(website_id=website.id, lang='de_DE')._get_template_view(
        'website.layout')
    banner_layout = layout._get_combined_arch().xpath('//div[@id="website_cookies_bar"]')
    if not banner_layout or BANNER_NEU not in ' '.join(''.join(banner_layout[0].itertext()).split()):
        fehler.append('Kombinierte Vorlage website.layout: Banner ohne Sie-Satz')
    print('Nachprüfung: %s' % ('in Ordnung' if not fehler else fehler))

    if WRITE and not fehler:
        env.cr.commit()
        # Die laufenden Odoo-Prozesse leeren ihre Caches (Vorlagen, Routing mit
        # den 404-Weiterleitungen) erst, wenn die Änderung über die Datenbank
        # signalisiert wird. Die Odoo-Shell tut das nicht von selbst.
        env.registry.signal_changes()
        print('Commit ausgeführt, Caches der laufenden Server signalisiert. '
              'Danach die Prüfschritte aus README, Befund C, durchführen.')
    else:
        env.cr.rollback()
        env.registry.reset_changes()
        print('Probelauf bzw. Fehler: zurückgerollt, nichts geändert.')


try:
    main()
except Abbruch as exc:
    env.cr.rollback()
    env.registry.reset_changes()
    print('ABBRUCH, nichts geändert: %s' % exc)
