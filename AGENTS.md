# Development instructions

- This repository contains only the price-monitoring application.
- Use a project virtual environment and Python 3.11 or later.
- Keep credentials, user databases and imported product catalogs out of Git.
- Keep money comparisons in integer cents and timestamps timezone-aware.
- A historical low means strictly lower than earlier collected prices.
- Never execute partial or unvalidated model tool calls. Preserve search context during bounded repairs.
- Keep the demo catalog fictional. Real platform integrations implement PriceProvider.
- Keep application state outside the installed package directory.
- After changes run `python -m unittest discover -s tests -v` and, when available,
  `node --check src/shopagent_monitor/app/static/app.js`.
- Update README or docs with changes to behavior, configuration or architecture.
- Do not publish local state, credentials or private research history.
