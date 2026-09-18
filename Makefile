test:
	cd backend && python -m pytest -q
eval:
	cd backend && python -m eval.harness
run:
	cd backend && uvicorn app.api.main:app --reload
front:
	cd frontend && npm run dev
