PY := .venv/bin/python

.PHONY: setup test check bootstrap prove demo web-setup web web-test web-demo

setup:            ## create .venv and install velum with dev tools
	python3 -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -e ".[dev]"
	@test -f .env || cp .env.example .env

test:             ## offline unit tests
	$(PY) -m pytest -q

check:            ## typecheck + tests (Python, and the web app if web/node_modules exists), run before every commit
	$(PY) -m mypy
	$(PY) -m pytest -q
	@if [ -d web/node_modules ]; then $(MAKE) --no-print-directory web-test; else echo "web/ skipped: run make web-setup"; fi

bootstrap:        ## fund the demo wallets ONCE (the only faucet caller) and write trust.local.json
	$(PY) scripts/bootstrap.py

prove:            ## live proof of step 2 on Testnet: anchors + verification against the real ledger
	$(PY) scripts/prove_anchor.py

demo:             ## THE CASE OF THE MISSING PIZZA: full demo on Testnet (samples/missing_pizza_case.png)
	$(PY) scripts/demo_pizza.py

web-setup:        ## install the web app (Nuxt) with the pinned lockfile; no install scripts run
	cd web && npm ci --ignore-scripts --no-audit --no-fund && npx nuxt prepare

web-test:         ## web: typecheck + tests against the same vectors as the Python code (tests/vectors)
	cd web && npx vue-tsc --noEmit && npx vitest run

web-demo:         ## copy the files of the last "make demo" into the Viewer's samples, and the trust list
	cd web && node scripts/sync-demo.mjs

web:              ## web app on http://localhost:3000 (Viewer, Editor, embed widget)
	cd web && npm run dev
