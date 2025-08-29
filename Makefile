.PHONY: venv deps scrape pdf clean

venv:
	python -m venv .venv

deps: venv
	. .venv/bin/activate && pip install -r requirements.txt

scrape:
	. .venv/bin/activate && python scripts/scrape_ibmi_docs.py

pdf:
	# Les PDF sont générés pendant scrape; cible laissée pour extension

clean:
	rm -rf data/raw_html data/md data/media outputs/pdf outputs/INDEX.md