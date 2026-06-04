# Changelog — KJR App (`kjr_grant`)

## 19.0.3.0.0 (2026-06-02) — Review, Härtung & Förderfest-Ausbau

### Behoben (kritisch/hoch)
- **`action_approve` brach komplett ab (Rollback):** `pdf_content, _ = _render_qweb_pdf(...)` überschrieb die gettext-Funktion `_` → `TypeError`. Jetzt `_report_type`.
- **Korrupte Bescheid-/Antrags-PDFs:** `ir.attachment.datas` erhielt rohe Bytes statt Base64 → `base64.b64encode(...)` (2 Stellen).
- **Mail-Templates versandten nie:** Modell hatte kein `company_id` (von Templates referenziert) → Feld ergänzt.
- **Jahresbericht-PDF crashte:** `o.env.cr.now()` existiert nicht → `context_timestamp(datetime.datetime.now())`.
- **Rückforderung falsch:** skalierte `grant_calculated` statt `grant_approved`; `@api.depends` vervollständigt.
- **Budget-Kennzahlen stale:** `store=True` ohne gültige Dependencies → auf non-stored (live) umgestellt.

### Security & DSGVO
- `base.group_public`-Schreibrecht auf `kjr.grant.participant` entfernt.
- Record Rules für `kjr.grant.participant` (Mandantentrennung der Teilnehmerdaten).
- IDOR auf Bestätigungsseite geschlossen; Antrag nur für eigene Verbände (Sachbearbeiter alle).
- Einwilligung Erziehungsberechtigter (`participant_consent`) + Anonymisierungs-Cron (`participant_retention_years`, Default 5 J.).

### Korrektheit / Datenintegrität
- `@api.constrains`: Datum (Ende ≥ Beginn), TN-Zahlen, keine negativen Beträge, `leader_ratio ≥ 1`.
- `<chatter/>` statt `oe_chatter` (5 Forms); `portal.pager` statt `web.pager`; Portal-Searchbar verdrahtet; `measure_end` Pflichtfeld.

### Neue Funktionen
- **Förderregeln konfigurierbar** (`kjr.grant.type`): Juleica-Zuschlag, Betreuungsschlüssel, Herkunftsquote, Alter, Dauer — statt hartcodiert (verifiziert gegen KJR-OA-Zuschussrichtlinie).
- **Förderfähigkeits-Hinweise** beim Einreichen.
- **Verwendungsnachweis-PDF** (Soll/Ist) + **„Abrechnung erstellen"** aus dem Antrag.
- **Vollversammlung**: Quorum + automatisches Beschlussergebnis.

### Aufräumen
- Ungenutzte Enterprise-Deps entfernt (`event`, `website_event`, `mass_mailing`, `sale_renting`, `website_sale_renting`) — kommen als eigene Folge-Module. `kjr_grant_type`-Stammdaten `noupdate="1"`.

### Hinweis
Steuer/USt/E-Rechnung betreffen die geplanten Einrichtungs-/Verleih-Module, nicht die Zuschussverwaltung (Zuschüsse = kein steuerbarer Umsatz). GoBD-Festschreibung über Odoo-Core (`l10n_de`) aktivieren.
Getestet: statisch (`py_compile`, `xmllint`, Referenz-Checks) + 2 adversariale Review-Durchgänge. Vor Produktivnahme auf Staging installieren und Workflows manuell testen.
