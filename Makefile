.PHONY: install lint format typecheck test web web-test e2e check serve demo refresh train legacy

install:            ## Python (uv) and UI (npm) dependencies
	uv sync --extra dev
	cd web && npm ci

lint:
	uv run ruff check . && uv run ruff format --check .
	cd web && npm run lint

format:
	uv run ruff format . && uv run ruff check --fix .

typecheck:
	uv run mypy
	cd web && npm run typecheck

test:               ## Python unit and integration tests with coverage
	uv run pytest --cov=d2bg --cov-report=term-missing

web:                ## build the UI into src/d2bg/static
	cd web && npm run build

web-test:
	cd web && npm test

e2e: web            ## Playwright against the real server (uses Edge locally)
	cd web && npm run e2e

check: lint typecheck test web-test e2e

serve:
	uv run d2bg serve

demo:
	uv run d2bg serve --demo juggernaut

refresh:            ## about 650 OpenDota requests; the free limit is about 3,000 a day
	uv run d2bg data refresh

train:              ## retrain the draft model from the stored public matches
	uv run --extra train d2bg train

legacy:             ## the v1 desktop app's tests (needs requirements.txt installed)
	python -m pytest tests --ignore=tests/d2bg -q
