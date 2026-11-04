# Changelog

## 0.1.0 (2026-11-04)

First version, tested offline and not yet with the live model.

- `build_agent_data.py`: aggregate tables from the outputs of msf-mdo-niger; reports not received become unknown; expected live births dropped.
- 19 read-only tools: disease series, weekly curves, rankings, like-for-like comparisons, seasonality, malaria testing, WHO meningitis thresholds, reporting, maternal deaths, DHIS2 2024, validation checks, data notes, model estimates, and a server-checked `publish_result`.
- Cautions attached by the tools and shown to the reader whatever the model writes.
- Web app with the MDO dashboard's colours: chat, charts, region map, CSV, password rule, strict Content-Security-Policy.
- Command line (`ask.py`, `mdo_cli.py`), skill, invented demo system, offline tests including a real browser and the real SDK against a fake API, and 24 live eval questions.
