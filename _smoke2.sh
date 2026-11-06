#!/usr/bin/env bash
# Повторний smoke J4: CSV journal (кирилиця в імені), HTML адмінки, журнал помилок.
BASE="http://127.0.0.1:8001"
ADMIN=474964150
M=2026-11

hdr() { echo; echo "=== $1 ==="; }

hdr "12'. CSV журнал ЦН 8 (було 500)"
c=$(curl -s -D /tmp/h3.txt -o /tmp/l.csv -w "%{http_code}" -H "x-telegram-user-id: $ADMIN" "$BASE/api/admin/cash/export.csv?month=$M&center_id=8")
echo "HTTP $c"; grep -i -E "content-(type|disposition)" /tmp/h3.txt
echo "рядків: $(wc -l < /tmp/l.csv)"; cat /tmp/l.csv

hdr "12b. CSV журнал ЦН 4 (ЦН Звягель, не налаштовано)"
c=$(curl -s -D /tmp/h4.txt -o /tmp/l4.csv -w "%{http_code}" -H "x-telegram-user-id: $ADMIN" "$BASE/api/admin/cash/export.csv?month=$M&center_id=4")
echo "HTTP $c"; grep -i "content-disposition" /tmp/h4.txt; head -10 /tmp/l4.csv

hdr "12c. CSV журнал без month → рік (fallback)"
c=$(curl -s -o /dev/null -w "%{http_code}" -H "x-telegram-user-id: $ADMIN" "$BASE/api/admin/cash/export.csv?center_id=8&year=2026")
echo "HTTP $c"

hdr "15'. Шаблон адмінки на VPS містить нові елементи"
grep -c -E "cash-year-table|cash-reconcile-result|cash-year-summary" /home/onivan/cohbbot-dev/templates/admin.html
grep -c -E "cash-year|cash-reconcile|cash-close-month|cash-reopen-month|downloadCashCsv" /home/onivan/cohbbot-dev/static/js/admin.js

hdr "16'. Помилки в журналі сервісу за 3 хв"
journalctl -u expensebot-dev.service --since "-3min" --no-pager 2>/dev/null | grep -i -E "error|traceback|exception|500 " | tail -5 || echo "(немає / sudo недоступний)"
echo; echo "=== DONE ==="
