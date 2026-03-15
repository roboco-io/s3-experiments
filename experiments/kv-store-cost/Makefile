VENV := .venv
PYTHON := $(VENV)/bin/python3
PIP := $(VENV)/bin/pip
DOCS_DIR := ../../docs/research

.PHONY: all setup run clean copy-to-docs

all: setup run copy-to-docs

setup: $(VENV)/bin/activate

$(VENV)/bin/activate:
	python3 -m venv $(VENV)
	$(PIP) install --quiet matplotlib numpy

run: setup
	$(PYTHON) chart.py

copy-to-docs: run
	cp output/*.png $(DOCS_DIR)/
	@echo "Charts copied to $(DOCS_DIR)/"

clean:
	rm -rf $(VENV) output/
