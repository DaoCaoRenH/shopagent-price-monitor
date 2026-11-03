# Development instructions

- This repository contains only the price-monitoring application.
- Use a project virtual environment and Python 3.11 or later.
- Keep credentials, user databases and imported product catalogs out of Git.
- Keep money comparisons in integer cents and timestamps timezone-aware.
- A historical low means strictly lower than earlier collected prices.
- Never execute partial or unvalidated model tool calls. Preserve search context during bounded repairs.
- Keep the demo catalog fictional. Real platform integrations implement PriceProvider.
- Keep application state outside the installed package directory.
- Use the project virtual environment for Python checks. After changes run
  `python -m unittest discover -s tests -v`, plus `npm test` and `npm run build`
  from `frontend/`. Frontend development requires Node 22.12+ or 24+.
- Frontend pages compose components; composables own state and asynchronous business flows;
  api modules own HTTP/NDJSON. Keep fetch calls out of components and views.
- Edit frontend/src, then rebuild the committed static distribution. Keep generated assets
  in the Python wheel so end users do not need Node. Never edit generated JS by hand.
- Update README or docs with changes to behavior, configuration or architecture.
- Do not publish local state, credentials or private research history.
