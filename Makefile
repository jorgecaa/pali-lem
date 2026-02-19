.PHONY: cli-test cli-file battery battery-online

TEXT ?= dhammo buddha sangha
DICT ?= dpd
FORMAT ?= compact
DEBUG ?= 1
DB ?=
FILE ?=
BMIN ?= 90
ONLINE_WORDS ?= buddha,dhamma,saṅgha,anicca,dukkha,anattā
ONLINE_MIN ?= 0.75

cli-test:
	python3 scripts/app_cli.py \
		--text "$(TEXT)" \
		--dict "$(DICT)" \
		--format "$(FORMAT)" \
		$(if $(filter 1 true yes,$(DEBUG)),--debug,) \
		$(if $(DB),--db "$(DB)",)

cli-file:
	python3 scripts/app_cli.py \
		--file "$(FILE)" \
		--dict "$(DICT)" \
		--format "$(FORMAT)" \
		$(if $(filter 1 true yes,$(DEBUG)),--debug,) \
		$(if $(DB),--db "$(DB)",)

battery:
	python3 scripts/custom_test_battery.py \
		--dict "$(DICT)" \
		--min-coverage "$(BMIN)" \
		$(if $(DB),--db "$(DB)",)

battery-online:
	python3 scripts/custom_test_battery.py \
		--dict "$(DICT)" \
		--min-coverage "$(BMIN)" \
		--online \
		--online-words "$(ONLINE_WORDS)" \
		--min-online-field-match "$(ONLINE_MIN)" \
		$(if $(DB),--db "$(DB)",)
