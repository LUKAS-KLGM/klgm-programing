"""Carry the German -> English unit rename onto existing installations.

The shipped KPI data files all carry noupdate="1", so changing a <field
name="unit"> in XML only affects fresh installs. Without this script an
existing database keeps "Tage"/"Pos." in an otherwise English UI — which is
exactly what the App Store screenshots would have shown.

`unit` is a plain Char (no translate=True), so this is a varchar column and a
straight UPDATE is safe — unlike `name`/`description`, which are jsonb and need
jsonb_set (see the 19.0.6.5.9 migration).

Only rows still holding the old shipped value are touched, so a unit a customer
edited themselves is left alone.
"""

UNITS = {
    'Tage': 'Days',
    'Pos.': 'lines',
    'Stk.': 'pcs.',
}


def migrate(cr, version):
    if not version:
        return

    # Guard: bail out rather than corrupt data if `unit` ever becomes
    # translatable (jsonb) — a plain UPDATE would write a bare string into a
    # jsonb column.
    cr.execute("""
        SELECT data_type FROM information_schema.columns
         WHERE table_name = 'executive_dashboard_kpi' AND column_name = 'unit'
    """)
    row = cr.fetchone()
    if not row or row[0] == 'jsonb':
        return

    for old, new in UNITS.items():
        cr.execute("""
            UPDATE executive_dashboard_kpi kpi
               SET unit = %s
              FROM ir_model_data imd
             WHERE imd.module = 'executive_dashboard'
               AND imd.model = 'executive.dashboard.kpi'
               AND imd.res_id = kpi.id
               AND kpi.unit = %s
        """, (new, old))
