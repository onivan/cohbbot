# -*- coding: utf-8 -*-
"""Перевірки інваріантів обліку коштів ЦН (без змін у БД).

Запуск на staging:
    venv/bin/python test_cash.py

Тест читає дані БД і перевіряє формули залишків, неперервність місячного
ланцюжка та звірку за поточний місяць.
"""
import asyncio
import math
import sys

import database
from handlers.cash import format_balance_message, format_money


_results = {'pass': 0, 'fail': 0, 'skip': 0}


def check(name, cond, detail=''):
    if cond:
        _results['pass'] += 1
        print('  PASS  %s' % name)
    else:
        _results['fail'] += 1
        print('  FAIL  %s  %s' % (name, detail))


def skip(name, why):
    _results['skip'] += 1
    print('  SKIP  %s  (%s)' % (name, why))


def close_to(actual, expected):
    try:
        return math.isfinite(float(actual)) and abs(float(actual) - float(expected)) < 0.01
    except (TypeError, ValueError):
        return False


async def main():
    print('\n[1] Повідомлення бота')
    check('формат суми з десятковою комою', format_money(1234.5) == '1 234,50 грн')
    check('від’ємна сума з мінусом', format_money(-12) == '−12,00 грн')
    unconfigured = format_balance_message({'configured': False, 'month': '2026-11'})
    check('не налаштований облік пояснено', 'не налаштовано' in unconfigured)
    configured = format_balance_message({
        'configured': True, 'month': '2026-11', 'opening_balance': 100,
        'received': 50, 'spent': 25, 'closing_balance': 125,
    })
    check('звіт містить залишок', 'Залишок: 125,00 грн' in configured)
    closed_mismatch = format_balance_message({
        'configured': True, 'month': '2026-11', 'opening_balance': 100,
        'received': 50, 'spent': 25, 'closing_balance': 125,
        'status': 'closed', 'matches': False,
    })
    check('розбіжність закритого місяця позначено', 'не збігається' in closed_mismatch)

    print('\n[2] Формули та ланцюжки в БД')
    month = database.current_month()
    overview = await database.get_cash_overview(int(month[:4]))
    configured_rows = 0
    centers = {}
    for month_data in overview.get('months', []):
        for row in month_data.get('rows', []):
            if not row.get('configured'):
                continue
            configured_rows += 1
            cid = int(row['center_id'])
            opening = row['opening_balance']
            received = row['received']
            spent = row['spent']
            closing = row['closing_balance']
            check('%s ЦН %s: received = funding - returned + adjustment'
                  % (month_data['month'], cid),
                  close_to(received, row['funding'] - row['returned'] + row['adjustment']),
                  'funding=%r returned=%r adjustment=%r received=%r'
                  % (row['funding'], row['returned'], row['adjustment'], received))
            check('%s ЦН %s: closing = opening + received - spent' % (month_data['month'], cid),
                  close_to(closing, opening + received - spent),
                  'opening=%r received=%r spent=%r closing=%r'
                  % (opening, received, spent, closing))
            previous = centers.get(cid)
            if previous:
                check('%s ЦН %s: opening дорівнює залишку попереднього місяця'
                      % (month_data['month'], cid),
                      close_to(opening, previous[1]),
                      'opening=%r previous closing=%r' % (opening, previous[1]))
            centers[cid] = (month_data['month'], closing)

        rows = [r for r in month_data.get('rows', []) if r.get('configured')]
        totals = month_data.get('totals') or {}
        for key in ('received', 'spent', 'closing_balance'):
            expected = sum(float(r.get(key) or 0) for r in rows)
            check('%s підсумок %s відповідає сумі рядків' % (month_data['month'], key),
                  close_to(totals.get(key), expected),
                  'total=%r rows=%r' % (totals.get(key), expected))

    if not configured_rows:
        skip('формули та ланцюжки', 'у БД ще немає налаштованого обліку')

    print('\n[3] Підсумок і звірка за %s' % month)
    settings = await database.get_all_cash_settings()
    if not settings:
        skip('поточний підсумок', 'у БД ще немає налаштованих ЦН')
        skip('reconcile_month', 'у БД ще немає налаштованих ЦН')
    else:
        summaries = 0
        for cid in settings:
            summary = await database.get_cash_summary(cid, month)
            if not summary.get('configured'):
                continue
            summaries += 1
            check('ЦН %s: received = funding - returned + adjustment' % cid,
                  close_to(summary['received'], summary['funding'] - summary['returned']
                           + summary['adjustment']), str(summary))
            check('ЦН %s: summary дотримується формули' % cid,
                  close_to(summary['closing_balance'],
                           summary['opening_balance'] + summary['received'] - summary['spent']),
                  str(summary))
            if summary.get('status') == 'closed':
                check('ЦН %s: закритий snapshot збігається з розрахунком' % cid,
                      summary.get('matches') is True, str(summary))
        if summaries == 0:
            skip('поточний підсумок', 'усі налаштування починаються пізніше поточного місяця')

        reconciled = await database.reconcile_month(month)
        check('звірка ланцюжка та знімків пройдена', reconciled.get('ok') is True,
              '; '.join('%s ЦН %s: %s' % (i.get('month'), i.get('center_id'), i.get('detail'))
                        for i in reconciled.get('issues', [])))

    print('\n===== PASS: %d   FAIL: %d   SKIP: %d ====='
          % (_results['pass'], _results['fail'], _results['skip']))

    pool = getattr(database, '_pool', None)
    if pool is not None:
        pool.close()
        await pool.wait_closed()
        database._pool = None

    return 1 if _results['fail'] else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
