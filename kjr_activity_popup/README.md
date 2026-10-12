# KJR Aktivitäten-Popup (`kjr_activity_popup`)

Fällige und überfällige Erinnerungen erscheinen im Odoo-Backend als großes,
gut lesbares Popup-Fenster – statt nur als kleine Zahl oben in der Leiste.

## Was angezeigt wird
- Aktivitäten (`mail.activity`) des angemeldeten Benutzers mit Fälligkeit
  heute oder früher, aus allen Apps (Kontakte, Zuschüsse, Projekt-Aufgaben …).
- Falls die App Projekt installiert ist: offene, zugewiesene Aufgaben, deren
  Frist heute erreicht oder überschritten ist.

Jeder Eintrag erscheint höchstens einmal pro Tag. „Später erinnern“ stellt ihn
zurück (Standard 1 Stunde), danach kommt er am selben Tag noch einmal.

## Einstellungen
| Wo | Was |
|----|-----|
| Eigene Einstellungen bzw. Benutzer → Präferenzen | „Erinnerungen als Popup“ an/aus (Standard an) |
| Systemparameter `kjr_activity_popup.poll_minutes` | Abfrage-Intervall in Minuten (Standard 10, 1–240) |
| Systemparameter `kjr_activity_popup.snooze_minutes` | „Später erinnern“ in Minuten (Standard 60, 5–1440) |

## Installation / Tests
Das Modul hat **kein** `auto_install`, und kein anderes KJR-Modul hängt von
ihm ab. Ein reines `-u` der bestehenden Module bringt das Popup deshalb
**nicht** live – beim Ausrollen ausdrücklich installieren (zuerst auf Staging
bzw. einer Server-Kopie):

```
-i kjr_activity_popup
--test-tags /kjr_activity_popup
```

Optional danach die Systemparameter `kjr_activity_popup.poll_minutes` und
`kjr_activity_popup.snooze_minutes` anpassen (siehe „Einstellungen“); ohne
Eintrag gelten die Standardwerte 10 bzw. 60 Minuten.
