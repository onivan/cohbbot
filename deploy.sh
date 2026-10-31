#!/usr/bin/env bash
# Деплой поточної гілки: push у bare-репо на VPS → хук post-receive оновлює
# робочий каталог сервісу і перезапускає його.
# Запускати ЛОКАЛЬНО в клоні гілки (dev або main): ./deploy.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$ROOT/.vps.env" ]; then
    set -a; . "$ROOT/.vps.env"; set +a
fi
if [ -z "${COHB_VPS:-}" ]; then
    echo "!! не задано COHB_VPS. Створи .vps.env (він у .gitignore):" >&2
    echo "   cp .vps.env.example .vps.env && chmod 600 .vps.env  # COHB_VPS=user@host" >&2
    exit 1
fi
VPS="$COHB_VPS"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
REMOTE="deploy-$BRANCH"

case "$BRANCH" in
    main) UNIT="expensebot.service";     TARGET="/home/onivan/cohbbot" ;;
    dev)  UNIT="expensebot-dev.service"; TARGET="/home/onivan/cohbbot-dev" ;;
    *)    echo "!! гілка '$BRANCH' не деплоїться (тільки main/dev)" >&2; exit 1 ;;
esac

if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
    echo "!! немає remote '$REMOTE'. Додай одноразово:" >&2
    echo "   git remote add $REMOTE ssh://$VPS/home/onivan/git/cohbbot-$BRANCH.git" >&2
    exit 1
fi

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "!! є незакомічені зміни — деплой їх не побачить:" >&2
    git status --short --untracked-files=no >&2
    exit 1
fi

git fetch "$REMOTE" "$BRANCH" --quiet
if [ -z "$(git rev-list "$REMOTE/$BRANCH..$BRANCH")" ]; then
    echo "→ $BRANCH: нічого нового ($(git log -1 --oneline))"
else
    echo "→ деплой $BRANCH: $(git log -1 --oneline)"
    git push "$REMOTE" "$BRANCH"

    local_sha="$(git rev-parse "$BRANCH")"
    remote_sha="$(ssh -o BatchMode=yes "$VPS" "git -C $TARGET rev-parse HEAD" 2>/dev/null || echo '?')"
    if [ "$local_sha" != "$remote_sha" ]; then
        echo "!! на VPS HEAD=${remote_sha:0:7}, очікували ${local_sha:0:7} — див. вивід хука" >&2
        echo "   ssh $VPS 'cd $TARGET && git status -sb'" >&2
        exit 1
    fi
    echo "   VPS: $TARGET @ ${local_sha:0:7} OK"
fi

state="$(ssh -o BatchMode=yes "$VPS" "systemctl is-active $UNIT" 2>/dev/null || true)"
if [ "$state" = "active" ]; then
    echo "→ $UNIT: active"
else
    echo "!! $UNIT: ${state:-невідомо}" >&2
    echo "   ssh $VPS 'sudo journalctl -u $UNIT -n 50 --no-pager'" >&2
    exit 1
fi

if git remote get-url origin >/dev/null 2>&1; then
    if git push origin "$BRANCH" --quiet 2>/dev/null; then
        echo "→ origin (GitHub): оновлено"
    else
        echo "   (origin не оновлено — перевір доступ до GitHub)"
    fi
fi
