# Changelog — Website-Downloadbereich (`kjr_website_downloads`)

## 19.0.1.0.0 (2026-10-22)

### Neu
- **Downloadbereich für die ganze Website** (Termin 13.10.2026, „Weitere Punkte“;
  Rückmeldung Bora 14.10.: für die ganze Website, nicht nur Freizeiten).
  Modell `website.download` mit Titel, Beschreibung, Datei, Kategorie, Datum,
  Reihenfolge, „Veröffentlicht“ und optional Website; Kategorien
  `website.download.category` mit eigener Reihenfolge.
- **Backend:** Website > Website > Inhalt > Downloads (gruppiert nach Kategorie,
  Reihenfolge per Ziehen), Website > Konfiguration > Download-Kategorien.
  Pflege durch die Gruppe Website-Designer.
- **Öffentliche Seite `/service/downloads`:** nach Kategorie gruppiert (Reihenfolge
  der Kategorien, ohne Kategorie zum Schluss unter „Weitere Downloads“), je Datei
  Dateityp, Größe und Datum. Überschriften-Hierarchie, Listen und aussagekräftige
  Linktexte (Titel). Schlicht im Standard-Layout, Einleitung und Schluss im
  Website-Editor befüllbar.
- **Auslieferung** über `/service/downloads/<id>`: nur veröffentlichte Downloads
  der aktuellen Website in aktiven Kategorien; PDFs und Rasterbilder öffnen im
  Browser, alles andere wird gespeichert.
- Bewusst **kein Website-Menüpunkt**: die Menüs pflegt der Betreiber selbst.
