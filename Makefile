# Швидкі команди розробки/деплою. Працює ЛОКАЛЬНО (клон на своїй машині);
# тести й логи — через ssh на VPS.
SHELL   := /bin/bash
VPS     ?= onivan@167.99.246.23
PROD    := /home/onivan/cohbbot
STAGING := /home/onivan/cohbbot-dev
SSH     := ssh -o BatchMode=yes $(VPS)

.DEFAULT_GOAL := help
.PHONY: help test test-local deploy deploy-prod restart logs status shell

help:  ## список команд
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

test:  ## тести на VPS (там БД, venv і запущений сервіс)
	$(SSH) 'cd $(STAGING) && venv/bin/python test_centers_own.py'

test-local:  ## тести локально (потрібен .env і доступ до БД)
	venv/bin/python test_centers_own.py

deploy:  ## задеплоїти поточну гілку (push → хук на VPS)
	./deploy.sh

deploy-prod:  ## задеплоїти main → прод
	./deploy.sh

restart:  ## перезапустити staging-сервіс без деплою
	$(SSH) 'sudo systemctl restart expensebot-dev.service; systemctl is-active expensebot-dev.service'

logs:  ## останні логи staging
	$(SSH) 'sudo journalctl -u expensebot-dev.service -n 60 --no-pager'

status:  ## стан git, сервісів і зв'язку з VPS
	@git status -sb
	@echo "VPS:     $$($(SSH) 'echo ok' 2>/dev/null || echo 'немає доступу')"
	@echo "staging: $$($(SSH) 'systemctl is-active expensebot-dev.service' 2>/dev/null)"
	@echo "prod:    $$($(SSH) 'systemctl is-active expensebot.service' 2>/dev/null)"

shell:  ## ssh на VPS
	ssh $(VPS)
