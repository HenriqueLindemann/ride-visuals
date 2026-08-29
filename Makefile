PYTHON ?= python3
RUN := PYTHONPATH=src $(PYTHON) -m ride_visuals.cli
CONFIG ?= config/config.toml
CONFIG_ARG := --config "$(CONFIG)"
SCOPE ?=
ACTIVITY_ID ?=
MAP_BASEMAP ?= dark
VIDEO_BASEMAP ?= dark
TELEMETRY_BASEMAP ?= plain
MOTION ?= chronological
STYLE ?= density

.PHONY: help install check ingest audit preview-collection preview-activity \
	final final-assets final-reports final-maps final-videos final-activity validate

help:
	@echo 'make install'
	@echo 'make check'
	@echo 'make audit SCOPE="--start-date 2024-02-01 --end-date 2024-12-31"'
	@echo 'make preview-collection SCOPE="--year 2024 --month 2"'
	@echo 'make preview-activity ACTIVITY_ID=<id>'
	@echo 'make --jobs=6 final'
	@echo 'make final-activity ACTIVITY_ID=<id>'

install:
	$(PYTHON) -m pip install -e '.[dev]'
	npm --prefix renderer ci --no-bin-links

check:
	$(RUN) doctor
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m ruff check \
		src/ride_visuals/cli.py src/ride_visuals/commands \
		tests/conftest.py tests/test_cli.py tests/test_cli_reference_activity.py \
		tests/test_reference_activity.py \
		--extend-select I,B,C4,SIM,C90,PLR0912,PLR0913,PLR0915
	PYTHONPATH=src $(PYTHON) -m pytest -q
	$(PYTHON) -m compileall -q src
	npm --prefix renderer run typecheck
	git diff --check

audit:
	$(RUN) audit $(CONFIG_ARG) $(SCOPE)

ingest:
	$(RUN) ingest $(CONFIG_ARG) $(SCOPE)

preview-collection:
	$(RUN) video collection --preview --motion $(MOTION) --style $(STYLE) \
		--basemap $(VIDEO_BASEMAP) --aspect 16:9 $(CONFIG_ARG) $(SCOPE)

preview-activity:
	@test -n "$(ACTIVITY_ID)" || (echo 'ACTIVITY_ID is required' && exit 2)
	$(RUN) video telemetry $(ACTIVITY_ID) --preview --basemap $(TELEMETRY_BASEMAP) --aspect 16:9 $(CONFIG_ARG)

final: check
	$(MAKE) ingest
	$(MAKE) audit
	$(MAKE) final-assets
	$(MAKE) validate

final-assets: final-reports final-maps final-videos

final-reports:
	$(RUN) report progress $(CONFIG_ARG) $(SCOPE)
	$(RUN) report dashboard $(CONFIG_ARG) $(SCOPE)
	$(RUN) report timeline $(CONFIG_ARG) $(SCOPE)

final-maps:
	$(RUN) map overview --dpi 300 --basemap $(MAP_BASEMAP) $(CONFIG_ARG) $(SCOPE)
	$(RUN) map heatmap --dpi 300 --basemap $(MAP_BASEMAP) $(CONFIG_ARG) $(SCOPE)
	$(RUN) map effort --dpi 300 --basemap $(MAP_BASEMAP) $(CONFIG_ARG) $(SCOPE)

final-videos:
	$(RUN) video collection --motion $(MOTION) --style $(STYLE) --basemap $(VIDEO_BASEMAP) --aspect 16:9 $(CONFIG_ARG) $(SCOPE)
	$(RUN) video collection --motion $(MOTION) --style $(STYLE) --basemap $(VIDEO_BASEMAP) --aspect 9:16 $(CONFIG_ARG) $(SCOPE)
	$(RUN) video progress --aspect 16:9 $(CONFIG_ARG) $(SCOPE)
	$(RUN) video progress --aspect 9:16 $(CONFIG_ARG) $(SCOPE)
	$(RUN) video timeline --aspect 16:9 $(CONFIG_ARG) $(SCOPE)
	$(RUN) video timeline --aspect 9:16 $(CONFIG_ARG) $(SCOPE)

final-activity:
	@test -n "$(ACTIVITY_ID)" || (echo 'ACTIVITY_ID is required' && exit 2)
	$(RUN) video clean $(ACTIVITY_ID) --aspect 16:9 $(CONFIG_ARG)
	$(RUN) video clean $(ACTIVITY_ID) --aspect 9:16 $(CONFIG_ARG)
	$(RUN) video telemetry $(ACTIVITY_ID) --basemap $(TELEMETRY_BASEMAP) --aspect 16:9 $(CONFIG_ARG)
	$(RUN) video telemetry $(ACTIVITY_ID) --basemap $(TELEMETRY_BASEMAP) --aspect 9:16 $(CONFIG_ARG)
	$(RUN) video overlay $(ACTIVITY_ID) --overlay-format png --aspect 16:9 $(CONFIG_ARG)

validate:
	$(RUN) validate --final-set --motion $(MOTION) --style $(STYLE) --basemap $(VIDEO_BASEMAP) $(CONFIG_ARG) $(SCOPE)
