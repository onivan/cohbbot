#!/usr/bin/env bash
# Переносить дані зі staging-БД (dev-бот) у прод-БД (prod-бот).
# Запускати НА VPS:
#     ./deploy/copy-db-dev-to-prod.sh               # лише довідкові дані
#     ./deploy/copy-db-dev-to-prod.sh --with-users  # + users/expenses (Telegram ID dev-бота!)
#
# Чому не все за замовчуванням: dev і prod — РІЗНІ Telegram-боти, тому в того самого
# користувача різні telegram_id. Перенесені `users` будуть «мертвими» для прод-бота,
# а `expenses` FK-залежні від `users`. Довідкові дані (центри, категорії, прив'язки,
# бюджети, налаштування AI) від ботів не залежать — їх переносити безпечно.
#
# Перевизначення шляхів: SRC_ENV=... DST_ENV=...
set -euo pipefail

SRC_ENV="${SRC_ENV:-/home/onivan/cohbbot-dev/.env}"
DST_ENV="${DST_ENV:-/home/onivan/cohbbot/.env}"

REF_TABLES=(centers categories center_categories budgets ai_settings)
USER_TABLES=(users expenses)

WITH_USERS=0
for arg in "$@"; do
    case "$arg" in
        --with-users) WITH_USERS=1 ;;
        -h|--help) sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "!! невідомий аргумент: $arg" >&2; exit 1 ;;
    esac
done

env_get() { # $1=файл $2=ключ
    grep -E "^[[:space:]]*$2=" "$1" | tail -1 | cut -d= -f2- | tr -d '\r' | sed 's/[[:space:]]*$//'
}

for f in "$SRC_ENV" "$DST_ENV"; do
    [ -f "$f" ] || { echo "!! немає $f" >&2; exit 1; }
done

S_HOST=$(env_get "$SRC_ENV" DB_HOST); S_PORT=$(env_get "$SRC_ENV" DB_PORT)
S_USER=$(env_get "$SRC_ENV" DB_USER); S_PASS=$(env_get "$SRC_ENV" DB_PASSWORD)
S_NAME=$(env_get "$SRC_ENV" DB_NAME)
D_HOST=$(env_get "$DST_ENV" DB_HOST); D_PORT=$(env_get "$DST_ENV" DB_PORT)
D_USER=$(env_get "$DST_ENV" DB_USER); D_PASS=$(env_get "$DST_ENV" DB_PASSWORD)
D_NAME=$(env_get "$DST_ENV" DB_NAME)

: "${S_HOST:=127.0.0.1}" "${S_PORT:=3306}" "${D_HOST:=127.0.0.1}" "${D_PORT:=3306}"

if [ -z "${S_NAME:-}" ] || [ -z "${D_NAME:-}" ]; then
    echo "!! у $SRC_ENV або $DST_ENV не задано DB_NAME" >&2
    exit 1
fi
if [ "$S_NAME" = "$D_NAME" ] && [ "$S_HOST" = "$D_HOST" ]; then
    echo "!! джерело і ціль — одна база ($D_NAME). Нічого не роблю." >&2
    exit 1
fi
for v in S_USER S_PASS D_USER D_PASS; do
    [ -n "${!v}" ] || { echo "!! не задано $v у відповідному .env" >&2; exit 1; }
done

TMPDIR_="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_"' EXIT
umask 077
printf '[client]\nhost=%s\nport=%s\nuser=%s\npassword=%s\n' "$S_HOST" "$S_PORT" "$S_USER" "$S_PASS" > "$TMPDIR_/src.cnf"
printf '[client]\nhost=%s\nport=%s\nuser=%s\npassword=%s\n' "$D_HOST" "$D_PORT" "$D_USER" "$D_PASS" > "$TMPDIR_/dst.cnf"

echo "→ джерело: $S_NAME @ $S_HOST:$S_PORT"
echo "→ ціль:    $D_NAME @ $D_HOST:$D_PORT"

TABLES=("${REF_TABLES[@]}")
[ "$WITH_USERS" = "1" ] && TABLES+=("${USER_TABLES[@]}")

# 1. Ціль має бути зі схемою (schema.sql застосовано)
have=$(mysql --defaults-extra-file="$TMPDIR_/dst.cnf" -N -e \
    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$D_NAME';" 2>/dev/null || echo 0)
echo "→ таблиць у цілі: $have"
if [ "${have:-0}" -lt "${#REF_TABLES[@]}" ]; then
    echo "!! у базі '$D_NAME' немає схеми. Спочатку:" >&2
    echo "   mysql <root> $D_NAME < schema.sql   # або mysql ... < ./schema.sql" >&2
    exit 1
fi

# 2. Копіюємо: TRUNCATE + дані в одному з'єднанні, FK-перевірки вимкнено
{
    echo "SET FOREIGN_KEY_CHECKS=0;"
    for t in "${TABLES[@]}"; do echo "TRUNCATE TABLE \`$t\`;"; done
    mysqldump --defaults-extra-file="$TMPDIR_/src.cnf" \
        --no-create-info --complete-insert --skip-triggers --skip-add-locks \
        --single-transaction --no-tablespaces "$S_NAME" "${TABLES[@]}"
    echo "SET FOREIGN_KEY_CHECKS=1;"
} | mysql --defaults-extra-file="$TMPDIR_/dst.cnf" "$D_NAME"

# 3. Звірка кількості рядків
echo "→ звірка:"
fail=0
for t in "${TABLES[@]}"; do
    s=$(mysql --defaults-extra-file="$TMPDIR_/src.cnf" -N -e "SELECT COUNT(*) FROM \`$t\`;" "$S_NAME")
    d=$(mysql --defaults-extra-file="$TMPDIR_/dst.cnf" -N -e "SELECT COUNT(*) FROM \`$t\`;" "$D_NAME")
    if [ "$s" = "$d" ]; then printf '   %-18s %s\n' "$t" "$d"
    else printf '   %-18s !! джерело %s, ціль %s\n' "$t" "$s" "$d"; fail=1; fi
done

[ -f "$DST_ENV" ] && echo "→ у $D_NAME пароль прод-БД лежить у $DST_ENV (не комітиться)"
if [ "$fail" = "1" ]; then echo "!! кількість рядків не збігається" >&2; exit 1; fi
echo "✓ дані перенесено"
