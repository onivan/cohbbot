# Швидкі команди розробки/деплою (виконуються на VPS у каталозі гілки)
SHELL   := /bin/bash
VENV    := venv/bin
PROD    := /home/onivan/cohbbot
STAGING := /home/onivan/cohbbot-dev

.DEFAULT_GOAL := help
.PHONY: help test deploy deploy-prod restart logs status

help:  ## список команд
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

test:  ## тести на staging (БД і сервіс там же)
	$(VENV)/python test_centers_own.py

deploy:  ## задеплоїти поточну гілку через git (dev → staging)
	./deploy.sh

deploy-prod:  ## задеплоїти main → прод
	cd $(PROD) && ./deploy.sh

restart:  ## перезапустити staging-сервіс без деплою
	sudo systemctl restart expensebot-dev.service && systemctl is-active expensebot-dev.service

logs:  ## останні логи staging
	sudo journalctl -u expensebot-dev.service -n 60 --no-pager

status:  ## стан git і сервісів
	@git status -sb
	@echo "staging: $$(systemctl is-active expensebot-dev.service)"
	@echo "prod:    $$(systemctl is-active expensebot.service)"
