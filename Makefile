# Швидкі команди розробки/деплою. Працює ЛОКАЛЬНО (клон на своїй машині);
# тести й логи — через ssh на VPS. Адреса VPS — у .vps.env (у .gitignore).
SHELL   := /bin/bash
-include .vps.env
VPS     ?= $(COHB_VPS)
PROD    := /home/onivan/cohbbot
STAGING := /home/onivan/cohbbot-dev
SSH     := ssh -o BatchMode=yes $(VPS)

.DEFAULT_GOAL := help
.PHONY: help check-vps test test-local test-browser deploy deploy-prod restart restart-prod restart-all logs status shell

help:  ## список команд
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

check-vps:  ## (службова) перевірка, що адреса VPS задана
	@test -n "$(strip $(VPS))" || { \
		echo "!! не задано COHB_VPS: cp .vps.env.example .vps.env && chmod 600 .vps.env" >&2; exit 1; }

test: check-vps  ## backend-тести на VPS і headless browser acceptance проти staging
	$(SSH) 'cd $(STAGING) && venv/bin/python -m unittest test_telegram_auth.py test_budget_spent.py test_budget_duplicate.py test_budget_notify.py test_budget_alerts.py test_report_pdf.py && venv/bin/python test_cash.py && venv/bin/python test_centers_own.py'
	$(MAKE) --no-print-directory test-browser

test-local:  ## тести локально (потрібен .env і доступ до БД)
	python3 -m unittest test_telegram_auth.py
	venv/bin/python -m unittest test_budget_spent.py test_budget_duplicate.py test_budget_notify.py test_budget_alerts.py test_report_pdf.py
	venv/bin/python test_cash.py
	venv/bin/python test_centers_own.py

test-browser:  ## headless E1 browser acceptance проти staging; конфіг у browser_tests/e1-staging-config
	@test -f browser_tests/e1-staging-config || { echo "Скопіюйте browser_tests/e1-staging-config.example за інструкцією README.md" >&2; exit 1; }
	@set -a; . ./browser_tests/e1-staging-config; set +a; cd browser_tests && npm test

deploy:  ## задеплоїти поточну гілку (push → хук на VPS)
	./deploy.sh

deploy-prod:  ## задеплоїти main → прод
	./deploy.sh

restart: check-vps  ## перезапустити staging-сервіс без деплою
	$(SSH) 'sudo -n systemctl restart expensebot-dev.service && systemctl is-active expensebot-dev.service'

restart-prod: check-vps  ## перезапустити прод-сервіс
	$(SSH) 'sudo -n systemctl restart expensebot.service && systemctl is-active expensebot.service'

restart-all: check-vps  ## перезапустити обидва (sudo -n: по юніту за виклик, інакше sudoers не матчить)
	@$(MAKE) --no-print-directory restart
	@$(MAKE) --no-print-directory restart-prod

logs: check-vps  ## останні логи staging
	$(SSH) 'sudo journalctl -u expensebot-dev.service -n 60 --no-pager'

status: check-vps  ## стан git, сервісів і зв'язку з VPS
	@git status -sb
	@echo "VPS:     $$($(SSH) 'echo ok' 2>/dev/null || echo 'немає доступу')"
	@echo "staging: $$($(SSH) 'systemctl is-active expensebot-dev.service' 2>/dev/null)"
	@echo "prod:    $$($(SSH) 'systemctl is-active expensebot.service' 2>/dev/null)"

shell: check-vps  ## ssh на VPS
	ssh $(VPS)
