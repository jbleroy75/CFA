up:
	docker compose up -d --build
logs:
	docker compose logs -f app
down:
	docker compose down
reset:
	docker compose down -v && docker compose up -d --build
test:
	PYTHONPATH=. python -m unittest discover -s tests -v
