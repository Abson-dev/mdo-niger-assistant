---
name: mdo-niger-data
description: Answer questions about Niger's weekly notifiable disease surveillance (MDO), 2015 to 2024 week 43. Use for cases, deaths, incidence and case fatality of malaria, measles, meningitis, cholera, diphtheria, malnutrition and other series, by year, week, region or health district; WHO meningitis thresholds; reporting completeness and timeliness; maternal deaths; DHIS2 2024 against the workbooks; and the statistical model estimates.
metadata:
  version: "0.1.0"
---

# MDO Niger data

Read `../mdo_agent/system_prompt.md` first: it holds the rules for reading the data and for answering. Every figure must come from a tool result; do not read the project's CSV files directly, because the tools carry the cautions that go with each table.

Run the tools from the root of this repository, in the `mdo-agent` conda environment:

```bash
python mdo_cli.py list
python mdo_cli.py get_disease_trend disease=measles level=region years=2017-2023
python mdo_cli.py compare_years disease="Paludisme confirmé" year_a=2023 year_b=2024
python mdo_cli.py rank_places disease=meningitis year=2022 level=district top=10
python mdo_cli.py get_meningitis_alerts years=2024 by=district
python mdo_cli.py get_reporting years=2023-2024 level=region
python mdo_cli.py search_data_notes term=denominators
python mdo_cli.py get_model_result table=t03_year_irr_long term=Meningitis
```

The tables come from `python build_agent_data.py`. If a tool says a table is missing, ask the user to build it after running the project's pipeline.

There is no `publish_result` in a shell: show the relevant rows as a table in your answer, and repeat the `# caution:` lines that bear on it.

Sub-national figures come from national surveillance: keep them out of anything public unless the data owners agree.
