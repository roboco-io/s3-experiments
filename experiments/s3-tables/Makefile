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
	@echo "This experiment creates real AWS resources:"
	@echo "  - S3 Table Bucket (Iceberg), regular S3 bucket, Glue database"
	@echo "  - Runs Athena queries (charged per TB scanned)"
	@echo "  - All resources auto-deleted after completion"
	@echo "  - Estimated time: 10-15 minutes. Cost: < \$$0.50"
	@echo "  - Region: us-east-1 (S3 Tables GA region)"
	@echo ""
	@echo "Press Ctrl+C to cancel, or wait 5 seconds to continue..."
	@sleep 5
	$(PYTHON) benchmark.py

clean:
	rm -rf $(VENV) output/
