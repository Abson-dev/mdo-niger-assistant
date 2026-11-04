# Contributing

## Never commit data

This repository holds no surveillance data. Do not commit `data/`, `demo_data/`, CSV, GeoJSON or Excel files, eval answers, API keys, or screenshots with real figures. Take screenshots on the invented system (`docs/make_screenshots.py`). `tests/test_build.py` fails if a data file is tracked.

## Set up

```bash
python -m venv .venv && source .venv/bin/activate    # or the conda environment in environment.yml
pip install -r requirements.txt -r requirements-dev.txt
```

## Before a pull request

```bash
ruff check .
python -m pytest
```

Both run in GitHub Actions on every pull request, with no data and no API key. If you have the real tables, also run `MDO_TEST_REAL_DATA=1 python -m pytest tests/test_real_data.py`.

## Changing the assistant

- A rule for reading the data belongs in `mdo_agent/catalog.py` when a tool can attach it to a table, and in `mdo_agent/data_notes.csv` when it explains the data. Keep `system_prompt.md` to how to use them.
- A new tool goes in `mdo_agent/tools.py` and `TOOLS`, with a test in `tests/test_tools.py` and, if it changes what the model should do, a question in `evals/questions.csv`.
- No figure from the real data belongs in the code, the notes, the prompt or the tests. Evals read their expected values from the tables at run time.
- Run the evals after changing the instructions or the tools. They make paid API calls.
