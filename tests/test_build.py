"""The build, on the invented system: what it keeps, what it must never keep, and that nothing in git holds data."""
import json
import subprocess
import tempfile
from pathlib import Path

import make_demo_data
import pandas as pd
import pytest

from build_agent_data import build
from mdo_agent import tools
from mdo_agent.catalog import DISEASES, MODEL_TABLES


@pytest.fixture(scope="module")
def built():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        make_demo_data.make_project(root / "project")
        info = build(root / "project", root / "out", synthetic=True)
        yield root, info


def test_build_info_describes_the_tables(built):
    root, info = built
    saved = json.loads((root / "out" / "build_info.json").read_text(encoding="utf-8"))
    assert saved == info and info["synthetic"] and info["last_week_of_last_year"] == 43 and info["districts"] == 24


def test_a_report_not_received_becomes_unknown(built):
    root, _ = built
    d = pd.read_csv(root / "out" / "district_week.csv.gz")
    gone = d[d.report == "not received"]
    assert len(gone) and gone.cases.isna().all() and gone.deaths.isna().all()
    assert d[(d.report != "not received") & (d.year < 2024)].cases.notna().all()


def test_reports_not_received_add_up(built):
    root, _ = built
    w = pd.read_csv(root / "out" / "weekly.csv")
    grid = pd.read_csv(root / "project" / "data" / "processed" / "completeness_weekly.csv")
    nat = w[(w.level == "national") & (w.disease == "Rougeole") & (w.year == 2020)]
    assert nat.reports_not_received.sum() == (grid[grid.year == 2020].status == "N").sum()
    assert w[w.year == 2024].reports_not_received.isna().all()  # no grid for 2024: unknown, not zero


def test_expected_live_births_are_dropped(built):
    root, _ = built
    assert "live_births" not in pd.read_csv(root / "out" / "maternal_deaths.csv").columns


def test_missing_project_files_are_reported():
    with tempfile.TemporaryDirectory() as tmp, pytest.raises(SystemExit, match="Run the project's pipeline"):
        build(Path(tmp), Path(tmp) / "out")


def test_catalog_covers_every_disease_and_the_notes_load():
    for name in pd.read_csv(tools.DATA / "disease_summary.csv").disease:
        assert name in DISEASES
    assert len(DISEASES) == 25 and len(MODEL_TABLES) == 16
    notes = pd.read_csv(Path(tools.__file__).with_name("data_notes.csv"))
    assert notes.note.notna().all() and notes.topic.is_unique


def test_no_data_can_be_committed():
    repo = Path(tools.AGENT_DIR)
    rules = (repo / ".gitignore").read_text(encoding="utf-8")
    for rule in ("/data/", "/demo_data/", "evals/results/", "*.csv", "*.gz", "*.geojson", "*.xls", ".env"):
        assert rule in rules
    tracked = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True, text=True, check=False).stdout.splitlines()
    allowed_csv = {"mdo_agent/data_notes.csv", "evals/questions.csv"}
    assert not [f for f in tracked if f.endswith((".csv", ".gz", ".geojson", ".xls", ".xlsx", ".docx", ".sqlite")) and f not in allowed_csv]
    assert not [f for f in tracked if f.startswith(("data/", "demo_data/"))]
