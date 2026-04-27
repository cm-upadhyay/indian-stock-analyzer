PYTHON := uv run python
UV     := uv

.PHONY: help install lint format type test run run-morning deploy

help:
	@echo "Available targets:"
	@echo "  install      Install all dependencies"
	@echo "  lint         Run ruff linter"
	@echo "  format       Format code with ruff"
	@echo "  type         Run mypy type checker"
	@echo "  test         Run unit tests with coverage"
	@echo "  run          Run 4 PM pipeline (full screener)"
	@echo "  run SYMBOLS=RELIANCE,TCS  Watchlist mode"
	@echo "  run-morning  Run 8 AM morning note pipeline"
	@echo "  deploy       Build Docker image and deploy to Lambda"

install:
	$(UV) sync

lint:
	$(UV) run ruff check src/ tests/

format:
	$(UV) run ruff format src/ tests/

type:
	$(UV) run mypy src/analyzer/indicators/ src/analyzer/data/models.py src/analyzer/llm/formatter.py

test:
	$(UV) run pytest tests/ -v

run:
ifdef SYMBOLS
	$(PYTHON) -m analyzer --symbols $(SYMBOLS)
else
	$(PYTHON) -m analyzer
endif

run-dry:
ifdef SYMBOLS
	$(PYTHON) -m analyzer --symbols $(SYMBOLS) --dry-run
else
	$(PYTHON) -m analyzer --dry-run
endif

run-morning:
	$(PYTHON) -m analyzer --morning

api:
	$(UV) run uvicorn analyzer.api.app:app --reload --port 8000

deploy:
	bash scripts/deploy.sh
