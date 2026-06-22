def migrate(cr, version):
    KPI_NAMES = {
        "Umsatz (netto)": "Revenue (net)",
        "Umsatz pro Monat": "Revenue per Month",
        "Umsatz nach Land": "Revenue by Country",
        "Umsatz nach Produktkategorie": "Revenue by Product Category",
        "Umsatz nach Team": "Revenue by Team",
        "Umsatz nach Vertriebskanal": "Revenue by Sales Channel",
        "Umsatz Pro Kopf": "Revenue per Capita",
        "Umsatz pro Mitarbeiter": "Revenue per Employee",
        "Auftragseingang pro Monat": "Order Intake per Month",
        "Aufträge": "Orders",
        "Aufträge pro Monat": "Orders per Month",
        "Fakturierung": "Invoicing",
        "Fakturierung pro Monat": "Invoicing per Month",
        "Fakturierung pro Quartal": "Invoicing per Quarter",
        "Marge": "Margin",
        "Marge %": "Margin %",
        "Marge pro Monat": "Margin per Month",
        "Offene Forderungen": "Open Receivables",
        "Forderungen nach Fälligkeit": "Receivables by Due Date",
        "Kontostand": "Bank Balance",
        "Einkaufsvolumen": "Purchase Volume",
        "Einkauf pro Monat": "Purchasing per Month",
        "Eingangsrechnungen": "Vendor Bills",
        "Eingangsrechnungen pro Monat": "Vendor Bills per Month",
        "Lieferquote": "Delivery Rate",
        "Lieferstatus": "Delivery Status",
        "Lieferungen": "Deliveries",
        "Lieferungen pro Monat": "Deliveries per Month",
        "Offene Lieferungen": "Open Deliveries",
        "Lagerbestand": "Inventory Value",
        "Retourenquote": "Return Rate",
        "Lieferanten-Delay": "Supplier Delay",
        "Neue Leads": "New Leads",
        "Pipeline-Wert": "Pipeline Value",
        "Pipeline nach Phase": "Pipeline by Stage",
        "Pipeline nach Mitarbeiter": "Pipeline by Employee",
        "Leads nach Vertriebsteam": "Leads by Sales Team",
        "Sales Cycle": "Sales Cycle",
        "Ø Rabatt": "Avg. Discount",
        "Top Kunden": "Top Customers",
        "DSO (Tage)": "DSO (Days)",
        "DPO (Tage)": "DPO (Days)",
        "Mitarbeiter": "Employees",
        "Abwesenheitsquote": "Absence Rate",
        "Abwesenheitstage": "Absence Days",
        "Aufgaben": "Tasks",
        "Aufgaben/MA": "Tasks/Employee",
        "Aufgaben nach Phase": "Tasks by Phase",
        "Aufgaben nach Projekt": "Tasks by Project",
        "Aufgaben nach Verantwortlichem": "Tasks by Responsible",
        "Aufgaben pro Monat (Deadline)": "Tasks per Month (Deadline)",
        "Neue Aufgaben pro Monat": "New Tasks per Month",
        "Team nach Abteilung": "Team by Department",
        "Aktivitäten gesamt": "Total Activities",
        "Aktivitäten nach Typ": "Activities by Type",
        "Aktivitäten pro Mitarbeiter": "Activities per Employee",
        "Aktivitäten pro Monat": "Activities per Month",
        "Anrufe": "Calls",
        "Anrufe pro Mitarbeiter": "Calls per Employee",
        "E-Mails": "Emails",
        "E-Mails pro Mitarbeiter": "Emails per Employee",
        "Meetings": "Meetings",
        "Meetings pro Mitarbeiter": "Meetings per Employee",
        "To-Dos pro Mitarbeiter": "To-Dos per Employee",
        "Wiederkaufrate": "Repeat Purchase Rate",
        "Vertriebsstärke/MA": "Sales Strength/Employee",
        "Zahlungsstatus": "Payment Status",
        "Umsatz nach Vertriebskanal": "Revenue by Sales Channel",
    }

    DASHBOARD_NAMES = {
        "CEO — Unternehmensübersicht": "CEO — Company Overview",
        "CFO — Finanzen": "CFO — Finance",
        "COO — Operations": "COO — Operations",
        "CSO — Sales Performance": "CSO — Sales Performance",
        "CTO — Projekte & Team": "CTO — Projects & Team",
    }

    for de, en in KPI_NAMES.items():
        cr.execute(
            "UPDATE executive_dashboard_kpi SET name = %s WHERE name = %s",
            (en, de),
        )

    for de, en in DASHBOARD_NAMES.items():
        cr.execute(
            "UPDATE executive_dashboard SET name = %s WHERE name = %s",
            (en, de),
        )

    # Allow future XML updates for these records
    cr.execute(
        "UPDATE ir_model_data SET noupdate = false "
        "WHERE module = 'executive_dashboard' "
        "AND model IN ('executive.dashboard.kpi', 'executive.dashboard')"
    )
