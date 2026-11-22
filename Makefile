PYTHON ?= python3
MODEL ?= gpt-6.1-sol

.PHONY: setup test demo live review validate publication-check
setup:
	git config core.hooksPath .githooks

test:
	$(PYTHON) -m unittest discover -s tests -v

demo:
	$(PYTHON) -m src.demo --output-dir results/demo-$$(date +%Y%m%d-%H%M%S)

live:
	$(PYTHON) -m src.runner --provider codex --model $(MODEL) --output results/mvp/live-$$(date +%Y%m%d-%H%M%S).jsonl

review:
	$(PYTHON) -m src.review

validate:
	$(PYTHON) -m src.validate

publication-check:
	$(PYTHON) scripts/check_publication.py --staged
	$(PYTHON) scripts/check_publication.py --ref HEAD
