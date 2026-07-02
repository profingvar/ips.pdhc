# ips.pdhc/gateway Makefile — local dev + rollup #349 FHIR conformance.
#
# Day-to-day:
#   make test            # run the pytest suite
#
# Rollup #349 conformance surface (Rule 15 A: CapabilityStatement
# only for now; clinical resource shape polish deferred).
#   make corpus          # emit CapabilityStatement JSON into
#                        # tests/fhir_corpus/
#   make conformance     # validate corpus against HL7 R5
#                        # validator_cli.jar (VALIDATOR_JAR must point
#                        # to a downloaded copy)

VENV ?= venv
PY := $(VENV)/bin/python
PYTEST := $(VENV)/bin/pytest

VALIDATOR_JAR ?= $(HOME)/.local/share/fhir/validator_cli.jar
CORPUS_DIR := tests/fhir_corpus
FHIR_VERSION := 5.0.0

# Terminology server. Same one plan.pdhc / termbank / request.pdhc use.
TX_SERVER ?= https://tx.fhir.org/r5


.PHONY: help test corpus conformance check-jar

help:
	@echo "Targets: test, corpus, conformance, check-jar"

test:
	PYTHONPATH=. $(PYTEST) tests -q

corpus:
	@mkdir -p $(CORPUS_DIR)
	$(PY) tests/conformance_corpus_emit.py $(CORPUS_DIR)
	@echo "Corpus refreshed at $(CORPUS_DIR)/"
	@ls -1 $(CORPUS_DIR)/*.json | wc -l | xargs -I{} echo "{} JSON files"

check-jar:
	@if [ ! -f "$(VALIDATOR_JAR)" ]; then \
		echo "MISSING $(VALIDATOR_JAR)"; \
		echo "Download from https://github.com/hapifhir/org.hl7.fhir.core/releases/latest"; \
		echo "and place at $(VALIDATOR_JAR), or pass VALIDATOR_JAR=<path>."; \
		exit 1; \
	fi

conformance: check-jar corpus
	@echo "Validating $(CORPUS_DIR)/*.json against FHIR R5 (tx: $(TX_SERVER))..."
	java -jar "$(VALIDATOR_JAR)" -version $(FHIR_VERSION) -tx=$(TX_SERVER) $(CORPUS_DIR)/*.json
