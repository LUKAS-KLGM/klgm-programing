def migrate(cr, version):
    # Same class of bug as 19.0.6.4.0's KPI_NAMES migration: `description`
    # was never translate=True before this version, so every existing
    # record's stored value is the literal German text from the XML data
    # files. Flipping translate=True and changing the XML to English source
    # text does not retroactively rewrite the already-stored column — a
    # normal `-u` data reload leaves it untouched. Force it via SQL, mirroring
    # the proven fix for `name`.
    KPI_DESCRIPTIONS = {
        "Average Order Value — Durchschnittlicher Bestellwert (Umsatz / Aufträge)":
            "Average Order Value — average revenue per order (Revenue / Orders)",
        "Durchschnittliche Tage vom Lead bis zum Abschluss (gewonnene Opportunities)":
            "Average number of days from lead to close (won opportunities)",
        "Durchschnittlicher Rabatt in Prozent über alle Verkaufspositionen":
            "Average discount percentage across all sales order lines",
        "Nettoumsatz aus bestätigten Verkaufsaufträgen im gewählten Zeitraum":
            "Net revenue from confirmed sales orders in the selected period",
        "Anzahl bestätigter Verkaufsaufträge":
            "Number of confirmed sales orders",
        "Gewichteter Wert aller offenen Verkaufschancen (Umsatz × Wahrscheinlichkeit)":
            "Weighted value of all open opportunities (revenue × probability)",
        "Summe aller unbezahlten oder teilbezahlten Ausgangsrechnungen":
            "Sum of all unpaid or partially paid customer invoices",
        "Summe aller gebuchten Ausgangsrechnungen und Gutschriften":
            "Sum of all posted customer invoices and credit notes",
        "Bruttomarge = Umsatz minus Einkaufspreis der verkauften Waren":
            "Gross margin = revenue minus cost of goods sold",
        "Bruttomarge in Prozent vom Umsatz (Marge / Fakturierung × 100)":
            "Gross margin as a percentage of revenue (margin / invoicing × 100)",
        "Anteil der Kunden mit mehr als einem Auftrag im Zeitraum":
            "Share of customers with more than one order in the period",
        "Umsatz je Mitarbeiter — Steigerung >5% sehr gut, 3-5% normal, <3% kritisch (Geschäftsmodell kippt in 3 Jahren)":
            "Revenue per employee — growth >5% very good, 3-5% normal, <3% critical (business model tips over within 3 years)",
        "Lieferpositionen je Mitarbeiter — misst die operative Vertriebsproduktivität":
            "Delivery lines per employee — measures operational sales productivity",
        "Anzahl gewonnener Verkaufschancen im Zeitraum":
            "Number of won opportunities in the period",
        "Days Sales Outstanding — Wie viele Tage brauchen Kunden im Schnitt zum Bezahlen":
            "Days Sales Outstanding — average number of days customers take to pay",
        "Days Payable Outstanding — Wie viele Tage braucht ihr im Schnitt zum Bezahlen eurer Lieferanten":
            "Days Payable Outstanding — average number of days you take to pay your suppliers",
        "Gebuchter Saldo des Standard-Bankjournals (Summe Soll minus Haben)":
            "Posted balance of the default bank journal (total debit minus credit)",
        "Durchschnittliche Lieferzeit der Lieferanten in Tagen":
            "Average supplier delivery time in days",
        "Anteil gelieferter Menge an bestellter Menge in Prozent":
            "Share of delivered quantity relative to ordered quantity, in percent",
        "Ausgangslieferungen in Bearbeitung (zugewiesen, bestätigt, wartend)":
            "Outgoing deliveries in progress (assigned, confirmed, waiting)",
        "Gesamtwert aller internen Lagerbestände":
            "Total value of all internal stock",
        "Anteil der Retouren an den Gesamtlieferungen in Prozent":
            "Share of returns relative to total deliveries, in percent",
        "Abwesenheitstage / (Mitarbeiter × 20 Arbeitstage) in Prozent":
            "Absence days / (employees × 20 working days), in percent",
        "Genehmigte Abwesenheitstage (Urlaub, Krankheit, etc.) im Zeitraum":
            "Approved absence days (vacation, sick leave, etc.) in the period",
    }

    # `description` just became translate=True in this version, which
    # converts the column to jsonb ({"en_US": ..., "de_DE": ...}) as part of
    # the schema migration that runs before this script — every key already
    # holds the old German text at this point. Only the en_US key needs to
    # move to the new English source string; de_DE already holds the
    # correct German text and must be left untouched.
    for de, en in KPI_DESCRIPTIONS.items():
        cr.execute(
            "UPDATE executive_dashboard_kpi "
            "SET description = jsonb_set(description, '{en_US}', to_jsonb(%s::text)) "
            "WHERE description ->> 'en_US' = %s",
            (en, de),
        )
