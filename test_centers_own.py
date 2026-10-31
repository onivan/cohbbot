# -*- coding: utf-8 -*-
"""Тести «свого ЦН» (F6) та прав доступу (H1).

Запуск на VPS (сервіс має бути запущений):
    cd /home/onivan/cohbbot-dev && source venv/bin/activate
    python test_centers_own.py

Опційно:
    TEST_BASE_URL=http://127.0.0.1:8001 ADMIN_ID=474964150 python test_centers_own.py

Перевіряє:
  * database._mark_own_center / get_cached_center_id / get_user_center_id
  * get_centers() / get_centers_summary() з user_id (прапорець is_my_center, свій ЦН першим)
  * HTTP: /api/user/{id}/role, /api/admin/centers, /api/admin/centers/summary
  * cache-busting: ?v=<mtime> у /static/js/*.js
  * права: звичайний юзер не має доступу до /api/admin/*
  * H1 (відома діра): читання бюджетів чужого ЦН звичайним юзером
"""
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime

import database

BASE = os.environ.get('TEST_BASE_URL', 'http://127.0.0.1:8001')
ADMIN_ID = int(os.environ['ADMIN_ID']) if os.environ.get('ADMIN_ID') else None
MONTH = None  # None -> поточний місяць (як на головному екрані)

_results = {'pass': 0, 'fail': 0, 'skip': 0, 'known': 0}


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


def known_issue(name):
    """Відома проблема з TODO.md: не валить тест, але й не мовчить."""
    _results['known'] += 1
    print('  KNOWN %s' % name)


def http(path, user=None):
    user = user or ADMIN_ID
    req = urllib.request.Request(BASE + path, headers={'x-telegram-user-id': str(user)})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')


def get_json(path, user=None):
    status, body = http(path, user)
    try:
        return status, json.loads(body)
    except ValueError:
        return status, None


async def main():
    await database.load_users()
    users = database.users_cache

    admins = [int(uid) for uid, info in users.items() if info.get('role') == 'admin']
    regulars = [int(uid) for uid, info in users.items() if info.get('role') != 'admin']
    admins_with_center = [u for u in admins if database.get_cached_center_id(u)]
    regulars_with_center = [u for u in regulars if database.get_cached_center_id(u)]

    admin = ADMIN_ID or (admins_with_center[0] if admins_with_center else (admins[0] if admins else None))
    admin_center = database.get_cached_center_id(admin) if admin else None
    other = regulars_with_center[0] if regulars_with_center else None

    print('\n[0] Оточення')
    print('    BASE               = %s' % BASE)
    print('    адмін для тестів   = %s (center_id=%r)' % (admin, admin_center))
    print('    звичайний юзер     = %s (center_id=%r)'
          % (other, database.get_cached_center_id(other) if other else None))
    print('    всього адмінів/юзерів = %d/%d, з ЦН = %d/%d'
          % (len(admins), len(regulars), len(admins_with_center), len(regulars_with_center)))
    if not admin:
        print('    !! у БД немає жодного адміна — HTTP-тести неможливі')
        return 1

    # ---------------- [1] чисті хелпери ----------------
    print('\n[1] Хелпери без БД')
    got = [c['id'] for c in database._mark_own_center(
        [{'id': 3, 'name': 'A'}, {'id': 1, 'name': 'B'}, {'id': 2, 'name': 'C'}], 2)]
    check('_mark_own_center: свій ЦН першим', got == [2, 3, 1], str(got))

    res = database._mark_own_center([{'id': 3, 'name': 'A'}, {'id': 1, 'name': 'B'}], None)
    check('_mark_own_center: без свого ЦН порядок не змінюється',
          [c['id'] for c in res] == [3, 1] and not any(c['is_my_center'] for c in res))

    res = database._mark_own_center([{'id': 7, 'name': 'X'}, {'name': 'без id'}], '7')
    check('_mark_own_center: рядковий id + битий запис',
          res[0]['is_my_center'] is True and res[1]['is_my_center'] is False)

    check('get_cached_center_id: невідомий юзер -> None', database.get_cached_center_id(999999999) is None)
    check('get_cached_center_id: None -> None', database.get_cached_center_id(None) is None)

    # ---------------- [2] БД ----------------
    print('\n[2] БД: get_user_center_id / get_centers / get_centers_summary')
    uid_center = await database.get_user_center_id(admin)
    check('get_user_center_id(адмін) == center_id з кешу',
          uid_center == admin_center, 'got %r, cache %r' % (uid_center, admin_center))

    centers_all = await database.get_centers()
    centers_own = await database.get_centers(user_id=admin)
    check('get_centers(): не порожній', len(centers_all) > 0, 'len=%d' % len(centers_all))
    check('get_centers(): без user_id жодного is_my_center',
          not any(c.get('is_my_center') for c in centers_all))
    check('get_centers(): однаковий склад з/без user_id',
          sorted(c['id'] for c in centers_all) == sorted(c['id'] for c in centers_own))

    summary_all = await database.get_centers_summary(MONTH)
    summary_own = await database.get_centers_summary(MONTH, admin)
    check('get_centers_summary(): не порожній', len(summary_all) > 0, 'len=%d' % len(summary_all))
    check('get_centers_summary(): без user_id жодного is_my_center',
          not any(c.get('is_my_center') for c in summary_all))

    if uid_center:
        mine = [c for c in centers_own if c.get('is_my_center')]
        check('get_centers(user_id): рівно один свій ЦН', len(mine) == 1, 'len=%d' % len(mine))
        check('get_centers(user_id): свій ЦН першим',
              bool(mine) and centers_own[0]['id'] == mine[0]['id'])
        check('get_centers(user_id): id збігається', bool(mine) and int(mine[0]['id']) == uid_center)
        rest = [c['name'].lower() for c in centers_own[1:]]
        check('get_centers(user_id): решта за назвою', rest == sorted(rest), str(rest))
        mine = [c for c in summary_own if c.get('is_my_center')]
        check('get_centers_summary(user_id): один свій ЦН і він перший',
              len(mine) == 1 and summary_own[0]['id'] == mine[0]['id'])
    else:
        skip('перевірки «свого ЦН» у БД', 'адмін не призначений на ЦН')

    # ---------------- [3] HTTP ----------------
    print('\n[3] HTTP: /api/user/{id}/role')
    status, data = get_json('/api/user/%d/role' % admin, admin)
    data = data or {}
    check('/role -> 200', status == 200, 'status=%s' % status)
    check('/role -> role=admin', data.get('role') == 'admin', str(data))
    if uid_center:
        check('/role -> center_id не порожній (фолбек з БД)', data.get('center_id') not in (None, ''), str(data))
    else:
        skip('/role -> center_id', 'адмін без ЦН у БД')

    print('\n[4] HTTP: /api/admin/centers')
    status, data = get_json('/api/admin/centers', admin)
    check('/api/admin/centers -> 200', status == 200, 'status=%s' % status)
    items = (data or {}).get('data') or []
    if uid_center:
        mine = [c for c in items if c.get('is_my_center')]
        check('один is_my_center', len(mine) == 1, 'len=%d' % len(mine))
        check('свій ЦН першим у відповіді', bool(mine) and items[0]['id'] == mine[0]['id'])

    print('\n[5] HTTP: /api/admin/centers/summary')
    status, data = get_json('/api/admin/centers/summary', admin)
    check('/api/admin/centers/summary -> 200', status == 200, 'status=%s' % status)
    items = (data or {}).get('data') or []
    if uid_center:
        mine = [c for c in items if c.get('is_my_center')]
        check('зведення: один is_my_center', len(mine) == 1, 'len=%d' % len(mine))
        check('зведення: свій ЦН першим', bool(mine) and items[0]['id'] == mine[0]['id'])
    if items:
        print('    перші 3 ЦН: %s' % [(c['name'], c.get('is_my_center')) for c in items[:3]])

    print('\n[6] HTTP: cache-busting')
    status, body = http('/?user_id=%d' % admin, admin)
    check('/ -> 200', status == 200, 'status=%s' % status)
    check('app.js?v=<mtime>', '/static/js/app.js?v=' in body)
    status, body = http('/admin?user_id=%d' % admin, admin)
    check('/admin -> 200 і admin.js?v=', status == 200 and '/static/js/admin.js?v=' in body,
          'status=%s' % status)

    print('\n[7] HTTP: права доступу')
    if other:
        status, _ = get_json('/api/admin/centers', other)
        check('звичайний юзер -> /api/admin/centers 403', status == 403, 'status=%s' % status)
        status, _ = get_json('/api/admin/centers/summary', other)
        check('звичайний юзер -> /api/admin/centers/summary 403', status == 403, 'status=%s' % status)
    else:
        skip('негативні тести /api/admin/*', 'немає звичайного юзера у БД')

    print('\n[8] H1 (відома діра, TODO H1): бюджети чужого ЦН')
    foreign = None
    if other and centers_all:
        own_other = database.get_cached_center_id(other)
        foreign = [c['id'] for c in centers_all if int(c['id']) != int(own_other or -1)]
        foreign = foreign[0] if foreign else None
    if foreign:
        status, _ = get_json('/api/budgets/center/%s?month=%s'
                             % (foreign, MONTH or datetime.now().strftime('%Y-%m')),
                             other)
        if status == 200:
            known_issue('H1: звичайний юзер %s читає бюджети ЦН %s (HTTP 200, очікується 403)'
                        % (other, foreign))
        else:
            check('H1: бюджети чужого ЦН недоступні (HTTP %s)' % status, status == 403, 'status=%s' % status)
    else:
        skip('H1: бюджети чужого ЦН', 'немає пари юзер/чужий ЦН')

    print('\n[9] HTTP: дані головного екрана')
    status, _ = get_json('/api/categories', admin)
    check('/api/categories -> 200', status == 200, 'status=%s' % status)
    if uid_center:
        status, _ = get_json('/api/expenses/%d?center_id=%d' % (admin, uid_center), admin)
        check('/api/expenses?center_id -> 200', status == 200, 'status=%s' % status)
        status, _ = get_json('/api/budgets/center/%d?month=%s'
                             % (uid_center, MONTH or __import__('datetime').datetime.now().strftime('%Y-%m')), admin)
        check('/api/budgets/center -> 200', status == 200, 'status=%s' % status)

    print('\n===== PASS: %d   FAIL: %d   SKIP: %d   KNOWN: %d ====='
          % (_results['pass'], _results['fail'], _results['skip'], _results['known']))

    # акуратно закриваємо пул, щоб aiomysql не логував «Event loop is closed»
    pool = getattr(database, '_pool', None)
    if pool is not None:
        pool.close()
        await pool.wait_closed()
        database._pool = None

    return 1 if _results['fail'] else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
