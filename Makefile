PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip

.PHONY: venv install test serve probe

venv:
	python3 -m venv .venv

install: venv
	$(PIP) install -e ".[dev]"

test:
	$(PYTHON) -m pytest -q

serve:
	$(PYTHON) -m agent.main

probe:
	$(PYTHON) scripts/probe_ax.py
