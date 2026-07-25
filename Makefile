PYTHON ?= python3.10
VENV := .venv
VENV_PY := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip
PORT ?= 8000

.PHONY: help venv install install-dev run dev clean

help:
	@echo "Targets:"
	@echo "  make venv         Create .venv"
	@echo "  make install      Create .venv and install runtime dependencies"
	@echo "  make install-dev  Create .venv and install dev dependencies too"
	@echo "  make run          Run the app (uvicorn, no auto-reload)"
	@echo "  make dev          Run the app with auto-reload"
	@echo "  make clean        Remove .venv"

venv:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PY) -m pip install --upgrade pip

install: venv
	$(VENV_PIP) install -e .

install-dev: venv
	$(VENV_PIP) install -e ".[dev]"

run:
	$(VENV_PY) -m uvicorn app.main:app --host 127.0.0.1 --port $(PORT)

dev:
	$(VENV_PY) -m uvicorn app.main:app --host 127.0.0.1 --port $(PORT) --reload

clean:
	rm -rf $(VENV)
