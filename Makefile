.PHONY: clean clean-test clean-pyc clean-build clean-env docs help setup
.DEFAULT_GOAL := help
.SILENT: clean clean-build clean-pyc clean-test setup

define BROWSER_PYSCRIPT
import os, webbrowser, sys

from urllib.request import pathname2url

webbrowser.open("file://" + pathname2url(os.path.abspath(sys.argv[1])))
endef
export BROWSER_PYSCRIPT

define PRINT_HELP_PYSCRIPT
import re, sys

for line in sys.stdin:
	match = re.match(r'^([a-zA-Z_-]+):.*?## (.*)$$', line)
	if match:
		target, help = match.groups()
		print("%-20s %s" % (target, help))
endef
export PRINT_HELP_PYSCRIPT

BROWSER := python -c "$$BROWSER_PYSCRIPT"

help:
	@python -c "$$PRINT_HELP_PYSCRIPT" < $(MAKEFILE_LIST)

clean: clean-build clean-pyc clean-test ## remove all build, test, coverage and Python artifacts

clean-build: ## remove build artifacts
	rm -fr build/
	rm -fr out/
	rm -fr gen/
	rm -fr dist/
	rm -fr .eggs/
	rm -fr .hypothesis/
	rm -fr .mypy_cache/
	find . -name '*.egg-info' -exec rm -fr {} +
	find . -name '*.egg' -exec rm -fr {} +

clean-pyc: ## remove Python file artifacts
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -fr {} +

clean-test: ## remove test and coverage artifacts
	rm -fr .nox/
	rm -f .coverage
	rm -fr htmlcov/
	rm -fr .pytest_cache

clean-env: ## remove environment
	rm -fr venv

lint: ## static code analysis
	black --line-length 120 --check fixbackend tests
	flake8 --max-line-length 999 fixbackend tests
	mypy --python-version 3.12 --config-file mypy.ini fixbackend tests

test: ## run tests quickly with the default Python
	pytest

test-all: ## run tests on every Python version with nox
	nox

coverage: ## check code coverage quickly with the default Python
	coverage run --source fixbackend -m pytest
	coverage combine || true
	coverage report -m || true
	coverage html || true
	$(BROWSER) htmlcov/index.html

venv:
	python3 -m venv venv --prompt "fixbackend"
	. ./venv/bin/activate && python3 -m pip install --upgrade poetry
	. ./venv/bin/activate && poetry install
	. ./venv/bin/activate && pip install --upgrade nox-poetry nox
	. ./venv/bin/activate && mypy --install-types --non-interactive fixbackend tests


setup: clean clean-env venv

