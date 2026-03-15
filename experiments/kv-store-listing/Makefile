VENV := .venv
PYTHON := $(VENV)/bin/python3
PIP := $(VENV)/bin/pip

.PHONY: all setup run clean

all: setup run

setup: $(VENV)/bin/activate

$(VENV)/bin/activate:
	python3 -m venv $(VENV)
	$(PIP) install --quiet boto3

run: setup
	@echo "WARNING: This creates real AWS resources (S3 bucket with up to 50K files)."
	@echo "Estimated time: 5-10 minutes. Cost: < \$$0.10"
	@echo "Press Ctrl+C to cancel, or wait 5 seconds to continue..."
	@sleep 5
	$(PYTHON) benchmark.py

clean:
	rm -rf $(VENV) output/
