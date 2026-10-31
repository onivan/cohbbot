#!/usr/bin/env bash
# Ідемпотентно готує git-деплой на VPS: bare-репозиторії + хуки + remote'и у робочих каталогах.
# Запускати НА VPS:  cd /home/onivan/cohbbot-dev && ./deploy/install-hooks.sh
set -euo pipefail

GIT_ROOT="/home/onivan/git"
HOOK_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/post-receive"

setup() {
    local work="$1" branch="$2" unit="$3"
    local bare="$GIT_ROOT/cohbbot-$branch.git"

    mkdir -p "$GIT_ROOT"
    if [ ! -d "$bare" ]; then
        echo "→ створюю bare-репо $bare (з $work)"
        git clone --bare --quiet "$work" "$bare"
    fi
    git -C "$bare" symbolic-ref HEAD "refs/heads/$branch"

    if git -C "$work" remote get-url "deploy-$branch" >/dev/null 2>&1; then
        git -C "$work" remote set-url "deploy-$branch" "$bare"
    else
        git -C "$work" remote add "deploy-$branch" "$bare"
    fi

    install -m 755 "$HOOK_SRC" "$bare/hooks/post-receive"
    printf 'TARGET=%s\nBRANCH=%s\nUNIT=%s\n' "$work" "$branch" "$unit" > "$bare/deploy.conf"

    echo "   OK: $bare → $work ($branch, $unit)"
}

echo "=== staging ==="
setup /home/onivan/cohbbot-dev dev expensebot-dev.service
echo "=== prod ==="
setup /home/onivan/cohbbot     main expensebot.service

echo
echo "Готово. Далі:"
echo "  ./deploy.sh            # у каталозі гілки (dev або main)"
echo
echo "Для автоматичного перезапуску сервісу з хука (одноразово, з паролем):"
echo "  echo 'onivan ALL=(root) NOPASSWD: /bin/systemctl restart expensebot.service, /bin/systemctl restart expensebot-dev.service' \\"
echo "    | sudo tee /etc/sudoers.d/cohb-deploy && sudo chmod 440 /etc/sudoers.d/cohb-deploy"
