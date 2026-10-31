# Thin wrapper around the stemma CLI. Usage: make all TRACK=example-sketch
TRACK ?= example-sketch
STEMMA := uv run stemma
ARGS ?=

.PHONY: help setup new validate midi render mix master analyse score all doctor test lint clean

help:
	@echo "make setup                    install Python dependencies with uv"
	@echo "make all TRACK=<slug>         midi, render, mix, master and analyse"
	@echo "make render TRACK=<slug> ARGS='--part lead --section groove'"
	@echo "make score TRACK=<slug>       sheet music: MusicXML, LilyPond and PDF"
	@echo "make new TRACK=<slug>         scaffold a new track"
	@echo "make test | lint | doctor | clean"

setup:
	@uv sync --quiet

new validate midi render mix master analyse score all: setup
	@$(STEMMA) $@ $(TRACK) $(ARGS)

doctor: setup
	$(STEMMA) doctor

test: setup
	uv run pytest -q

lint: setup
	uv run ruff check src tests tracks

clean:
	rm -rf tracks/$(TRACK)/renders
