.PHONY: test run dry-run links list export discord

test:
	python3 offres_alternance.py --self-test
	PYTHONPYCACHEPREFIX=/private/tmp/python-pycache python3 -m py_compile offres_alternance.py

run:
	python3 offres_alternance.py --no-email

dry-run:
	python3 offres_alternance.py --no-email --no-discord --dry-run --max 5

links:
	python3 offres_alternance.py --links-only

list:
	python3 offres_alternance.py --list-offers --max 20

export:
	python3 offres_alternance.py --export-csv

discord:
	python3 offres_alternance.py --test-discord
