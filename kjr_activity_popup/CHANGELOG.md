# Changelog — KJR Aktivitäten-Popup (`kjr_activity_popup`)

## 19.0.1.0.0 (2026-10-12)

### Neu
- **Großes Erinnerungs-Popup im Backend** (Wunsch aus der Besprechung, B50:
  „schön groß sichtbar, dass auch Leute mit Brille das sehen … ein
  Pop-up-Fenster wäre besser“). Fällige und überfällige Aktivitäten des
  angemeldeten Benutzers (`mail.activity`, aus allen Apps – also auch
  Aktivitäten an Projekt-Aufgaben) erscheinen als modaler Dialog mit großer
  Schrift (Grundschrift 1,25 rem, Titel 1,5–1,75 rem), großen Knöpfen und
  farbiger Markierung (rot = überfällig mit Anzahl Tage, gelb = heute fällig).
- **Projekt-Aufgaben mit Frist**: Ist die App Projekt installiert, kommen
  offene Aufgaben (`project.task`, nicht erledigt/abgebrochen, keine Vorlage)
  dazu, die dem Benutzer zugewiesen sind und deren Frist heute erreicht oder
  überschritten ist. Weiche Kopplung über die Registry – das Modul hängt nur
  von `base`, `mail` und `web` ab.
- **Wann es aufpoppt**: kurz nach dem Laden des Backends, danach regelmäßig
  (Systemparameter `kjr_activity_popup.poll_minutes`, Standard 10, 1–240) und
  sofort, wenn der Bus eine neu zugewiesene fällige Aktivität meldet
  (`mail.activity/updated`). Geprüft wird nur im sichtbaren Browser-Tab; ein
  verdeckter Tab holt die Prüfung beim Zurückkehren nach. Während einer
  laufenden Odoo-Tour erscheint kein Popup.
- **Pro Eintrag und Tag nur einmal**: serverseitiger Merker
  `kjr.activity.popup.mark` (Benutzer, Modell, ID, zuletzt angezeigt am,
  zurückgestellt bis). „Heute“ richtet sich nach der Zeitzone des Benutzers.
  Der Merker wird in einer einzigen Anweisung (`INSERT … ON CONFLICT … DO
  UPDATE … WHERE … RETURNING`) gesetzt, damit mehrere Tabs denselben Eintrag
  nicht doppelt zeigen. Alte Merker räumt der Autovacuum nach 7 Tagen ab.
- **Knöpfe je Eintrag**: *Öffnen* (Datensatz bzw. Aufgabe; bei fehlendem
  Leserecht die Aktivität selbst, wie im Odoo-Standard), *Erledigt*
  (Aktivität wie über die Aktivitäten-Leiste abschließen bzw. Aufgabe auf
  „Erledigt“ setzen – mit den normalen Rechten des Benutzers; bei
  Dokument-Aktivitäten ausgeblendet, die verlangen einen Upload) und
  *In 1 Std. erinnern* (Systemparameter `kjr_activity_popup.snooze_minutes`,
  Standard 60, 5–1440). Unten: *Schließen*, *Alle in 1 Std. erinnern*,
  *Alle meine Aktivitäten*. Höchstens 20 Einträge je Popup; weitere folgen
  beim nächsten Abruf.
- **Pro Benutzer abschaltbar**: Feld `kjr_activity_popup_enabled`
  („Erinnerungen als Popup“, Standard an) in den eigenen Einstellungen und in
  der Benutzerverwaltung (Reiter Präferenzen); in `SELF_READABLE_FIELDS` und
  `SELF_WRITEABLE_FIELDS`, damit jeder es selbst umstellen kann.
- Selbst angelegte Einträge erscheinen erst nach 15 Minuten im Popup, damit
  die eigene, gerade angelegte Aktivität nicht Sekunden später über den Bus
  wieder aufpoppt.
- Popup-Aktionen wirken nur auf Einträge, die dem angemeldeten Benutzer
  zugewiesen sind; Portal-Benutzer bekommen kein Popup.
  Auch „Später erinnern“ (`kjr_popup_snooze`) nimmt nur interne Benutzer an
  (sonst AccessError), übergeht nicht zugewiesene oder nicht vorhandene
  Einträge stillschweigend und lehnt mehr als 20 Einträge je Aufruf ab – der
  Merker (nur Administratoren per ACL) lässt sich so nicht über RPC aufblähen.
- Aufgaben in Projekten mit Sichtbarkeit „Eingeladene interne Benutzer“, denen
  der Zugewiesene nicht folgt: Der Projektname wird gezielt mit `sudo`
  gelesen (nur der Name des Projekts der eigenen Aufgabe). Ein einzelner
  Eintrag ohne Leserecht wird übersprungen (ohne Merker, Log nur mit
  Modell/ID) und blockiert nicht mehr das ganze Popup.
- *Erledigt* bei Aufgaben nur, wenn der Benutzer die Aufgabe ändern darf
  (`has_access('write')`); interne Benutzer ohne Projekt-Gruppe sehen nur
  *Öffnen* und *Später erinnern*. Ein direkter Aufruf ohne Schreibrecht wird
  mit einer verständlichen Meldung abgewiesen.
- Barrierefreiheit: Jeder Listeneintrag ist über seinen Titel beschriftet
  (`aria-labelledby`), die Knöpfe tragen den Titel im zugänglichen Namen
  („Öffnen: Rückruf“, „Erledigt: Rückruf“, …).
- Dialogtitel neutral („Erinnerung: 1 fälliger Eintrag“ / „… fällige
  Einträge“), weil das Popup Aktivitäten und Aufgaben-Fristen zeigt.
- Ausrollen: kein `auto_install` – das Modul muss mit `-i kjr_activity_popup`
  ausdrücklich installiert werden, ein `-u` der übrigen Module genügt nicht
  (siehe Modul-README).
- Tests: `tests/test_activity_popup.py` (Auswahl, Reihenfolge, einmal pro Tag,
  pro Benutzer, Zurückstellen, Höchstzahl, Zeitzone, Präferenz, Portal,
  Erledigt/Öffnen inkl. Rechteprüfung, Systemparameter, Autovacuum,
  Asset-Bundle; Aufgaben-Fristen, falls Projekt installiert – inkl. Projekt
  nur für Follower und Benutzer ohne Schreibrecht auf die Aufgabe).
