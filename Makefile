.PHONY: setup test verify demo score freeze-manifest baseline case trace ui clean

PYTHON ?= python3

setup:
	$(PYTHON) -m pip install --break-system-packages -r requirements.txt
	@which cobc >/dev/null 2>&1 || (echo "Installing GnuCOBOL..."; apt-get update -qq && apt-get install -y gnucobol)
	@echo "Setup complete. Try: make demo"

# THE ONE COMMAND. Runs the demo bar: happy flow, then the negative
# scenarios, then opens the HTML trace.
demo:
	$(PYTHON) run.py demo

# The pre-built test suite. This is a scoring gate.
test:
	$(PYTHON) -m pytest tests/ -v

# The held-back evaluation set (available in full - see eval/score.py).
# `make score REPEAT=2` reports run-to-run divergence.
score:
	$(PYTHON) -m eval.score $(if $(REPEAT),REPEAT=$(REPEAT),)

# Confirms nothing outside ai/ has been modified. Scoring gate.
verify:
	$(PYTHON) -c "from pathlib import Path; from ai_platform.guardrails import verify_manifest; \
	v = verify_manifest(Path('.manifest.json')); \
	(print('VERIFY FAILED:') or [print(' -', x) for x in v] or exit(1)) if v else print('make verify: clean.')"

# Run once, before you start editing ai/, to freeze the checksum
# manifest that `make verify` checks against.
freeze-manifest:
	$(PYTHON) -c "from pathlib import Path; from ai_platform.guardrails import write_manifest; \
	write_manifest(Path('.manifest.json')); print('.manifest.json written.')"

baseline:
	$(PYTHON) run.py baseline

case:
	$(PYTHON) run.py case $(CASE_ID)

trace:
	$(PYTHON) run.py trace --last

ui:
	$(PYTHON) -m streamlit run streamlit_app.py

clean:
	rm -rf traces/run_*.html out/*.html out/*.json generated/*.py __pycache__ .pytest_cache
	find . -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
