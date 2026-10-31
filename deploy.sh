#!/usr/bin/env bash
# Git-деплой поточної гілки: push у bare-репо на VPS → post-receive оновлює робочий каталог і перезапускає сервіс.
# Запускати НА VPS у каталозі гілки:  ./deploy.sh
# З локальної машини:                ssh 167.99.246.23 'cd /home/onivan/cohbbot-dev && ./deploy.sh'
set -euo pipefail

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
REMOTE="deploy-$BRANCH"

case "$BRANCH" in
    main) UNIT="expensebot.service" ;;
    dev)  UNIT="expensebot-dev.service" ;;
    *)    UNIT="" ;;
esac

if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
    echo "!! немає remote '$REMOTE' — спочатку: ./deploy/install-hooks.sh" >&2
    exit 1
fi

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "!! є незакомічені зміни (деплой перезапише їх):" >&2
    git status --short --untracked-files=no >&2
    echo "   закоміть або зроби 'git stash'" >&2
    exit 1
fi

if [ -z "$(git rev-list "$REMOTE/$BRANCH..$BRANCH" 2>/dev/null)" ]; then
    echo "→ $BRANCH: нічого нового, деплой не потрібен ($(git log -1 --oneline))"
    exit 0
fi

echo "→ деплой $BRANCH: $(git log -1 --oneline)"
git push "$REMOTE" "$BRANCH"

if [ -n "$UNIT" ]; then
    if systemctl is-active --quiet "$UNIT"; then
        echo "→ $UNIT: active"
    else
        echo "!! $UNIT НЕ активний — sudo journalctl -u $UNIT -n 50 --no-pager" >&2
        exit 1
    fi
fi
