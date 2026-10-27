.PHONY: install test info api ui

install:
	pip install -r requirements.txt
	cd frontend && npm install

test:
	python -m pytest -q

info:
	python -m adtp.cli info

api:
	uvicorn api.main:app --reload --port 8000

ui:
	cd frontend && npm run dev
