#!/usr/bin/env bash
# Smoke-тест J4 (етап 4): річний огляд, звірка, закриття місяця, CSV.
BASE="http://127.0.0.1:8001"
ADMIN=474964150
USER=323137939
M=2026-11

hdr() { echo; echo "=== $1 ==="; }
code() { curl -s -o /tmp/out.json -w "%{http_code}" "$@"; }

hdr "1. year/2026 (admin)"
c=$(code -H "x-telegram-user-id: $ADMIN" "$BASE/api/admin/cash/year?year=2026")
echo "HTTP $c"
python3 - <<'PY'
import json
d = json.load(open('/tmp/out.json'))['data']
print('year:', d['year'], 'months:', len(d['months']), 'centers:', len(d['centers']))
print('totals:', d['totals'])
m = d['months'][-1]
print('last month:', m['month'], 'rows:', len(m['rows']), 'totals:', m['totals'])
if m['rows']:
    print('row0:', {k: m['rows'][0][k] for k in ('name','center_id','status','opening_balance','received','spent','closing_balance','matches')})
print('center0 keys:', sorted(d['centers'][0].keys()))
PY

hdr "2. year=1999 → 400"
echo "HTTP $(code -H "x-telegram-user-id: $ADMIN" "$BASE/api/admin/cash/year?year=1999")"; cat /tmp/out.json; echo

hdr "3. reconcile $M"
c=$(code -H "x-telegram-user-id: $ADMIN" "$BASE/api/admin/cash/reconcile?month=$M")
echo "HTTP $c"
python3 - <<'PY'
import json
d = json.load(open('/tmp/out.json'))['data']
print('month:', d['month'], 'ok:', d['ok'], 'issues:', len(d.get('issues') or []))
for i in (d.get('issues') or [])[:5]:
    print('  ', i)
print('keys:', sorted(d.keys()))
PY

hdr "4. reconcile month=2026-13 → 400"
echo "HTTP $(code -H "x-telegram-user-id: $ADMIN" "$BASE/api/admin/cash/reconcile?month=2026-13")"

echo; echo "--- стан ЦН 8 ДО дій ---"
curl -s -H "x-telegram-user-id: $ADMIN" "$BASE/api/admin/cash/overview?month=$M" | python3 -c "
import json,sys
d=json.load(sys.stdin)['data']
r=[x for x in d['rows'] if x['center_id']==8][0]
print({k:r[k] for k in ('status','month_opening','received','spent','closing_balance','matches')})
print('totals:', d['totals'])" | tee /tmp/before.txt

hdr "5. close-month у майбутньому → 400"
c=$(curl -s -o /tmp/out.json -w "%{http_code}" -X POST -H "x-telegram-user-id: $ADMIN" -H "Content-Type: application/json" \
      -d '{"month":"2099-01"}' "$BASE/api/admin/cash/close-month")
echo "HTTP $c"; head -c 300 /tmp/out.json; echo

hdr "6. close-month $M"
c=$(curl -s -o /tmp/out.json -w "%{http_code}" -X POST -H "x-telegram-user-id: $ADMIN" -H "Content-Type: application/json" \
      -d "{\"month\":\"$M\"}" "$BASE/api/admin/cash/close-month")
echo "HTTP $c"
python3 - <<'PY'
import json
b = json.load(open('/tmp/out.json'))
d = b.get('data', b)
print({k: (v if not isinstance(v, list) else len(v)) for k, v in d.items()})
PY

hdr "7. стан ЦН 8 ПІСЛЯ закриття"
curl -s -H "x-telegram-user-id: $ADMIN" "$BASE/api/admin/cash/overview?month=$M" | python3 -c "
import json,sys
d=json.load(sys.stdin)['data']
r=[x for x in d['rows'] if x['center_id']==8][0]
print({k:r[k] for k in ('status','month_opening','received','spent','closing_balance','matches')})
print('totals:', d['totals'])" | tee /tmp/after.txt

hdr "8. reopen-month $M"
c=$(curl -s -o /tmp/out.json -w "%{http_code}" -X POST -H "x-telegram-user-id: $ADMIN" -H "Content-Type: application/json" \
      -d "{\"month\":\"$M\",\"reason\":\"smoke J4\"}" "$BASE/api/admin/cash/reopen-month")
echo "HTTP $c"; cat /tmp/out.json | head -c 300; echo

hdr "9. стан ЦН 8 ПІСЛЯ відкриття"
curl -s -H "x-telegram-user-id: $ADMIN" "$BASE/api/admin/cash/overview?month=$M" | python3 -c "
import json,sys
d=json.load(sys.stdin)['data']
r=[x for x in d['rows'] if x['center_id']==8][0]
print({k:r[k] for k in ('status','month_opening','received','spent','closing_balance','matches')})
print('totals:', d['totals'])" | tee /tmp/after2.txt

echo; echo "--- порівняння ДО/ПІСЛЯ (цифри не мають змінитись) ---"
diff <(sed 's/закритий//;s/відкритий//' /tmp/before.txt) <(sed 's/закритий//;s/відкритий//' /tmp/after2.txt) \
  && echo "OK: цифри однакові" || echo "!! різниця"

hdr "10. CSV рік"
c=$(curl -s -D /tmp/h.txt -o /tmp/year.csv -w "%{http_code}" -H "x-telegram-user-id: $ADMIN" "$BASE/api/admin/cash/export.csv?year=2026")
echo "HTTP $c"; grep -i -E "content-(type|disposition)" /tmp/h.txt
echo "перші байти (hex): $(head -c 3 /tmp/year.csv | xxd -p)"
echo "рядків: $(wc -l < /tmp/year.csv)"; head -8 /tmp/year.csv

hdr "11. CSV місяць"
c=$(curl -s -D /tmp/h2.txt -o /tmp/m.csv -w "%{http_code}" -H "x-telegram-user-id: $ADMIN" "$BASE/api/admin/cash/export.csv?month=$M")
echo "HTTP $c"; grep -i "content-disposition" /tmp/h2.txt; head -12 /tmp/m.csv

hdr "12. CSV журнал ЦН 8"
c=$(curl -s -D /tmp/h3.txt -o /tmp/l.csv -w "%{http_code}" -H "x-telegram-user-id: $ADMIN" "$BASE/api/admin/cash/export.csv?month=$M&center_id=8")
echo "HTTP $c"; grep -i "content-disposition" /tmp/h3.txt; head -14 /tmp/l.csv

hdr "13. звичайний юзер → 403 на всі нові ендпоінти"
for u in "year?year=2026" "reconcile?month=$M" "export.csv?year=2026"; do
  echo "  /$u → HTTP $(code -H "x-telegram-user-id: $USER" "$BASE/api/admin/cash/$u")"
done
echo -n "  close-month → HTTP "; curl -s -o /dev/null -w "%{http_code}\n" -X POST -H "x-telegram-user-id: $USER" -H "Content-Type: application/json" -d "{\"month\":\"$M\"}" "$BASE/api/admin/cash/close-month"

hdr "14. без авторизації → 401"
echo "HTTP $(code "$BASE/api/admin/cash/year?year=2026")"

hdr "15. HTML адмінки містить нові елементи"
curl -s "$BASE/admin" | grep -c -E "cash-year-table|cash-reconcile-result"

hdr "16. журнал сервісу — помилки за останні 5 хв"
journalctl -u expensebot-dev.service --since "-5min" --no-pager 2>/dev/null | grep -i -E "error|traceback|exception" | tail -10 || echo "(sudo недоступний — пропущено)"
echo; echo "=== DONE ==="
