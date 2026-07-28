def migrate(cr, version):
    # App rename "Controlling" -> "Executive Dashboard" (App Store listing
    # decision, 27.07.2026). Most occurrences are plain XML text on
    # non-noupdate records and pick up the new value on a normal -u reload.
    # The cron job's display name is the one exception: ir.cron's `name` is
    # delegate-inherited from ir.actions.server.name, which is translate=True
    # -> stored as jsonb (same class of bug as Fund #8 in
    # reference_odoo_i18n_mechanics — a plain-text UPDATE would crash the
    # registry load again). Only an en_US key exists on this record, no
    # de_DE, so there is nothing else to preserve.
    cr.execute(
        "UPDATE ir_act_server s "
        "SET name = jsonb_set(s.name, '{en_US}', to_jsonb(%s::text)) "
        "FROM ir_cron c "
        "WHERE c.ir_actions_server_id = s.id "
        "AND s.name ->> 'en_US' = %s",
        (
            "Executive Dashboard: Reports versenden",
            "Controlling: Dashboard Reports versenden",
        ),
    )
