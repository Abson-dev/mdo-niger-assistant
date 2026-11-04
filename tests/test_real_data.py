"""Only with MDO_TEST_REAL_DATA=1, on your computer: the tables in data/ against the project's own outputs and known facts."""
import os
from pathlib import Path

import pandas as pd
import pytest

from mdo_agent import tools

pytestmark = pytest.mark.skipif(os.environ.get("MDO_TEST_REAL_DATA") != "1", reason="needs the real tables")
PROJECT = Path(os.environ.get("MDO_NIGER_PROJECT", Path(tools.AGENT_DIR).parent / "MDO - Niger"))


def test_national_series_equal_the_project(rows):
    a = pd.read_csv(PROJECT / "data" / "processed" / "mdo_annual.csv")
    for disease in a.disease.unique():
        mine, _ = rows(tools.get_disease_trend, disease=disease)
        theirs = a[a.disease == disease].sort_values("year")
        assert mine.cases.tolist() == theirs.cases.tolist() and mine.deaths.tolist() == theirs.deaths.tolist()


def test_the_cut_to_a_week_matches_the_long_table(rows):
    long = pd.read_csv(PROJECT / "data" / "processed" / "mdo_long.csv", usecols=["year", "week", "disease", "cases", "region"], low_memory=False)
    t = long[(long.disease == "Méningite") & (long.region == "Zinder") & (long.year == 2023) & (long.week <= 43)]
    mine, _ = rows(tools.get_disease_trend, disease="Méningite", level="region", places="Zinder", years="2023", through_week=43)
    assert mine.cases.iloc[0] == t.cases.sum()


def test_known_shape_of_the_series():
    info = tools.build_info()
    assert not info["synthetic"] and info["diseases"] == 25 and info["districts"] == 72 and info["last_week_of_last_year"] == 43 and len(info["model_tables"]) == 16


def test_every_eval_question_has_its_expected_value():
    from run_evals import expected

    q = pd.read_csv(Path(tools.AGENT_DIR) / "evals" / "questions.csv", dtype=str, keep_default_na=False)
    for row in q.itertuples():
        expected(row)
