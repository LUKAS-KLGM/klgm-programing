# -*- coding: utf-8 -*-
"""Deutsche Fassung übersetzbarer Felder sicherstellen (Prüfbericht 22.10.2026).

Odoo speichert übersetzbare Felder als jsonb ``{sprache: wert}``. Datensätze aus
den XML-Daten der Module landen dabei nur unter ``en_US``, auch wenn der Text
deutsch ist (die Module bringen keine .po-Dateien mit). Die deutsche Oberfläche
zeigt dann die en_US-Fassung als Ersatz. Bearbeitet die Geschäftsstelle den
Text auf Deutsch, entsteht daneben eine eigene de_DE-Fassung; wer auf
Englisch liest (oder eine Mail in en_US rendert), bekommt weiter den alten Text.

``fill_missing_lang`` kopiert deshalb die Quellfassung (en_US) in die
Zielsprache (de_DE), aber nur, wo die Zielsprache noch FEHLT. Eine bereits
gepflegte deutsche Fassung bleibt unangetastet. Ohne aktive Zielsprache
geschieht nichts.
"""
import logging

_logger = logging.getLogger(__name__)

TEMPLATE_FIELDS = ('name', 'subject', 'body_html')


def fill_missing_lang(env, records, fnames, lang='de_DE', source='en_US'):
    """Kopiert ``source`` nach ``lang`` in den Feldern ``fnames``, wo ``lang`` fehlt.

    Rückgabe: Anzahl der geänderten (Datensatz, Feld)-Paare.
    """
    records = records.exists()
    if not records or not env['res.lang'].with_context(active_test=True).search_count(
            [('code', '=', lang)]):
        return 0
    changed = 0
    table = records._table
    for fname in fnames:
        field = records._fields.get(fname)
        if not field or not field.translate or not field.store:
            continue
        # Spaltenname aus dem Feld (kein Benutzereingabe-Wert).
        env.cr.execute(
            'UPDATE "{table}" SET "{col}" = "{col}" || jsonb_build_object(%s, "{col}"->%s) '
            ' WHERE id = ANY(%s) AND "{col}" ? %s AND NOT "{col}" ? %s'.format(
                table=table, col=field.name),
            [lang, source, list(records.ids), source, lang])
        changed += env.cr.rowcount
    if changed:
        records.invalidate_recordset(list(fnames))
    return changed


def fill_module_templates(env, module, lang='de_DE'):
    """Mailvorlagen eines Moduls (per xmlid) mit deutscher Fassung versehen."""
    data = env['ir.model.data'].sudo().search(
        [('module', '=', module), ('model', '=', 'mail.template')])
    templates = env['mail.template'].sudo().with_context(active_test=False).browse(
        data.mapped('res_id'))
    count = fill_missing_lang(env, templates, TEMPLATE_FIELDS, lang=lang)
    if count:
        _logger.info('%s: deutsche Fassung für %d Vorlagenfeld(er) ergänzt (Vorlagen %s).',
                     module, count, templates.exists().ids)
    return count
