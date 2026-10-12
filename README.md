# klgm-programing
A new repository created by Skysize

## Branch `KJR` – Odoo 19 Module (Kreisjugendring Oberallgäu)

| Modul | Zweck |
|-------|-------|
| `kjr_grant` | Zuschussverwaltung, Juleica, Vollversammlung, Fördermittel, Verwendungsnachweis |
| `kjr_facility` | Einrichtungsbuchung (Jugendhaus Diepolz, Zeltplatz NiSo) |
| `kjr_facility_grant` | Brücke Einrichtung ↔ Zuschuss (auto_install) |
| `kjr_kommja` | KommJA – Einrichtungsverzeichnis |
| `kjr_rental` | Materialverleih (inkl. Spielmobil-Anfrage mit Spam-Schutz-Hook) |
| `kjr_event` | Ferienprogramm & Schulungen (inkl. Einwilligungs-Sperre: Online-Anmeldung Minderjähriger erst nach Einwilligung der Erziehungsberechtigten bestätigt) |
| `kjr_event_shop` | Brücke Veranstaltungen ↔ Shop (`website_event_sale`): Bestellbestätigung, Reservierungs-PDF, Einwilligungs-Sperre bei Anmeldungen mit Verkaufsauftrag (auto_install) |
| `kjr_event_sign` | Einwilligung der Erziehungsberechtigten digital per Odoo Sign (Enterprise, `sign`); inaktiv, bis in den Einstellungen „Einwilligung digital einholen" eingeschaltet ist |
| `kjr_website_antispam` | Unsichtbarer Spam-Schutz (Honeypot + signiertes Zeittoken) für Website-Formulare, Veranstaltungsanmeldung und KJR-Formulare; optional Cloudflare Turnstile (siehe Modul-README) |

Statisch geprüft (py_compile, xmllint) und mehrfach reviewt. Vor Produktivnahme auf Staging installieren/testen.

### Installation neuer Module

`auto_install` greift nur bei einer Neuinstallation der Abhängigkeiten, **nicht
beim Update** (`-u`). Neue Module deshalb auf der bestehenden Instanz
ausdrücklich installieren:

```
-i kjr_website_antispam
-i kjr_event_sign        # nur, wenn das Enterprise-Modul sign installiert ist
```

Rollout nur auf Staging bzw. einer Server-Kopie, nie direkt in Produktion:

1. `-u kjr_event,kjr_event_shop,kjr_rental` (kjr_event_shop nur, wenn installiert)
2. `-i kjr_website_antispam`, danach sofort den Systemparameter
   `kjr_website_antispam.mode` auf `log` stellen (zuerst nur protokollieren,
   nach der Beobachtung `enforce`; Notbremse `off`, siehe
   `kjr_website_antispam/README.md`). Im Log besonders auf `too_fast` bei
   angemeldeten Benutzern und erneut abgesendeten Formularen achten.
3. `-i kjr_event_sign`, falls `sign` installiert ist; danach in den
   Einstellungen Absender und Vorlage setzen und die digitale Einwilligung
   einschalten
4. Testanmeldungen und Tests:
   `--test-tags /kjr_event,/kjr_event_shop,/kjr_event_sign,/kjr_website_antispam`

### Werkzeuge

| Pfad | Zweck |
|------|-------|
| `tools/icons/build_icons.py` | erzeugt die App-Icons aller KJR-Module |
| `tools/einwilligung/build_einwilligung_pdf.py` | erzeugt das neutrale Einwilligungs-PDF für `kjr_event_sign` (`--check` prüft nur) |
| `tools/website_fixes/` | Befund A: `<br/>` in Formular-Textfeldern bereinigen (Anleitung in `tools/website_fixes/README.md`; Ausführung nur durch eine berechtigte Person nach Snapshot) |
