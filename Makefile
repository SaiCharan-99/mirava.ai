# mirava.ai — developer commands (CLAUDE.md §7). Recipes run in bash (Git Bash on Windows).
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PY := uv run
WEB := web
VISUAL := tools/visual
# call JS tools through node directly (no npm/npx → cmd.exe shims; robust to a broken Windows PATH)
VITEST := node node_modules/vitest/vitest.mjs
ESLINT := node node_modules/eslint/bin/eslint.js
TSC := node node_modules/typescript/bin/tsc
VITE := node node_modules/vite/bin/vite.js

.PHONY: help setup dev api web emulator test lint types map fetch-osm genesis engine llm-smoke seed-demo restore-demo eval visual fixtures deploy

help: ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/'

setup: ## uv sync + npm ci (web, tools/visual) + playwright chromium
	uv sync
	cd $(WEB) && npm ci
	cd $(VISUAL) && npm ci && npx playwright install chromium

dev: ## Firestore emulator + api + web (engine arrives in phase 2), fakes + fast clock
	@echo "api :8000 · web :5173 · firestore emulator :8080 (Ctrl+C stops all)"
	WORLD_SECONDS_PER_SIM_DAY=120 LLM_BACKEND=fake DECISION_BACKEND=fake BQ_BACKEND=duckdb \
	  npx --yes concurrently -k -n emu,api,web -c yellow,cyan,magenta \
	  "gcloud emulators firestore start --host-port=localhost:8080 --quiet" \
	  "$(PY) uvicorn api.main:app --port 8000 --reload" \
	  "cd $(WEB) && npm run dev"

api: ## api alone on :8000
	$(PY) uvicorn api.main:app --port 8000 --reload

web: ## web alone on :5173
	cd $(WEB) && node scripts/sync-assets.mjs && $(VITE) --port 5173 --strictPort

emulator: ## Firestore emulator alone on :8080
	gcloud emulators firestore start --host-port=localhost:8080 --quiet

test: ## pytest + web unit tests
	$(PY) pytest
	cd $(WEB) && $(VITEST) run

lint: ## ruff + mypy + eslint + tsc + gitleaks
	$(PY) ruff check .
	$(PY) mypy shared world api tools/mapgen tools/llm_smoke.py tools/gen_types.py
	cd $(WEB) && $(ESLINT) src --max-warnings=0
	cd $(WEB) && $(TSC) --noEmit -p .
	gitleaks git . --no-banner --redact --exit-code 1
	gitleaks git . --pre-commit --no-banner --redact --exit-code 1

types: ## pydantic → web/src/types/generated.ts
	$(PY) python -m tools.gen_types

map: ## OSM extract → Tiled map, road graph, places, sites, stores, tileset
	$(PY) python -m tools.mapgen.build

fetch-osm: ## (re)download the Overpass extract (normally committed)
	$(PY) python -m tools.mapgen.fetch_osm

genesis: ## phase 2
	@echo "make genesis arrives in phase 2"; exit 1

engine: ## phase 2
	@echo "make engine arrives in phase 2"; exit 1

llm-smoke: ## one structured call + one embedding via the configured backend
	$(PY) python -m tools.llm_smoke

seed-demo: ## phase 4+
	@echo "make seed-demo arrives in phase 4"; exit 1

restore-demo: ## phase 6
	@echo "make restore-demo arrives in phase 6"; exit 1

eval: ## phase 6
	@echo "make eval arrives in phase 6"; exit 1

fixtures: ## regenerate web/src/visual-fixtures/mockup-fixtures.json from the mockup
	cd $(VISUAL) && node extract-fixtures.mjs

visual: ## capture app (must run on :5173) + compare; PHASE=1 limits screens
	cd $(VISUAL) && node capture.mjs --target app $(if $(PHASE),--phase $(PHASE),) && node compare.mjs $(if $(PHASE),--phase $(PHASE),)

deploy: ## Cloud Build: api → Cloud Run, web → Firebase Hosting (needs gcloud auth)
	gcloud builds submit --config infra/cloudbuild.yaml --region $${GCP_REGION:-asia-south1} \
	  --substitutions _REGION=$${GCP_REGION:-asia-south1} .
