"""Build the assistant's tables in data/ from the outputs of the msf-mdo-niger project.

    python build_agent_data.py                         # project in ../MDO - Niger, or MDO_NIGER_PROJECT
    python build_agent_data.py --project PATH --out data

This is the only step that reads the project's files. The tools read only the folder written here. Nothing in this
step or in the tools changes a value from the project: it reshapes the tables, keeps the total population as the one
denominator, and marks district reports that were not received.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from mdo_agent.catalog import MODEL_TABLES

REPO = Path(__file__).resolve().parent
PROCESSED = ["mdo_long", "mdo_annual", "mdo_regional", "mdo_district", "mdo_weekly", "mdo_weekly_region", "mdo_summary", "mdo_years",
             "completeness_weekly", "completeness_2024_cumulative", "maternal_deaths", "dhis2_vs_workbook_2024", "district_regions",
             "validation_checks"]
APP = ["meningitis_district_week", "dhis2_cases_region_week", "dhis2_completeness_region_week"]


def read(folder: Path, name: str) -> pd.DataFrame:
    path = folder / f"{name}.csv"
    if not path.exists():
        raise SystemExit(f"Missing {path}. Run the project's pipeline first (rebuild_data.bat in msf-mdo-niger).")
    return pd.read_csv(path, low_memory=False)


def annual_table(source: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One long table of yearly figures, national, by region and by district."""
    years = source["mdo_years"].set_index("year")
    nat = source["mdo_annual"].drop(columns="partial_year").assign(level="national", region="", place="Niger")
    reg = source["mdo_regional"].assign(level="region", place=lambda d: d.region)
    dis = source["mdo_district"].assign(level="district", place=lambda d: d.district).drop(columns="district")
    out = pd.concat([nat, reg, dis], ignore_index=True)
    out["through_week"] = out.year.map(years.last_week)
    out["partial_year"] = out.year.map(~years.complete)
    cols = ["disease", "year", "level", "region", "place", "cases", "deaths", "population", "cfr_pct", "incidence_per_100k", "through_week", "partial_year"]
    return out[cols]


def weekly_tables(source: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """National and regional weeks with the number of reports not received; district weeks with their report status."""
    grid = source["completeness_weekly"]
    missing = grid[grid.status == "N"]
    nat_miss = missing.groupby(["year", "week"]).size().rename("reports_not_received").reset_index()
    reg_miss = missing.groupby(["year", "week", "region"]).size().rename("reports_not_received").reset_index()
    have_grid = set(grid.year)

    nat = source["mdo_weekly"].assign(level="national", place="Niger").merge(nat_miss, how="left", on=["year", "week"])
    reg = (source["mdo_weekly_region"].assign(level="region", place=lambda d: d.region).drop(columns="region")
           .merge(reg_miss.rename(columns={"region": "place"}), how="left", on=["year", "week", "place"]))
    weekly = pd.concat([nat, reg], ignore_index=True)
    weekly["reports_not_received"] = weekly.reports_not_received.where(~weekly.year.isin(have_grid), weekly.reports_not_received.fillna(0))

    last = source["mdo_years"].set_index("year").last_week
    long = source["mdo_long"]
    long = long[long.week <= long.year.map(last)][["year", "week", "region", "district", "disease", "cases", "deaths"]]
    status = grid[["year", "week", "district", "status"]].rename(columns={"status": "report"})
    long = long.merge(status, how="left", on=["year", "week", "district"])
    long["report"] = long.report.map({"T": "on time", "L": "late", "N": "not received"})
    # A report not received is unknown, not zero.
    gone = long.report == "not received"
    long.loc[gone, ["cases", "deaths"]] = float("nan")
    return weekly[["disease", "year", "week", "level", "place", "cases", "deaths", "reports_not_received"]], long


def malaria_testing(source: dict[str, pd.DataFrame]) -> pd.DataFrame:
    long = source["mdo_long"]
    t = long[(long.disease == "Paludisme confirmé") & long.tested.notna()]
    parts = [t.groupby("year")[["tested", "cases"]].sum().reset_index().assign(level="national", place="Niger"),
             t.groupby(["year", "region"])[["tested", "cases"]].sum().reset_index().rename(columns={"region": "place"}).assign(level="region"),
             t[t.year >= 2017].groupby(["year", "district"])[["tested", "cases"]].sum().reset_index().rename(columns={"district": "place"}).assign(level="district")]
    out = pd.concat(parts, ignore_index=True).rename(columns={"cases": "positive"})
    out["positivity_pct"] = (100 * out.positive / out.tested).where(out.tested > 0).round(1)
    return out[["year", "level", "place", "tested", "positive", "positivity_pct"]]


def build(project: Path, out: Path, synthetic: bool = False) -> dict:
    processed, app, models = project / "data" / "processed", project / "app" / "data", project / "analysis" / "output" / "tables"
    source = {n: read(processed, n) for n in PROCESSED} | {n: read(app, n) for n in APP}
    out.mkdir(parents=True, exist_ok=True)

    weekly, district_week = weekly_tables(source)
    tables = {
        "annual": annual_table(source),
        "weekly": weekly,
        "disease_summary": source["mdo_summary"],
        "years": source["mdo_years"],
        "places": source["district_regions"],
        "reporting_grid": source["completeness_weekly"],
        "reporting_2024": source["completeness_2024_cumulative"],
        "maternal_deaths": source["maternal_deaths"].drop(columns="live_births"),
        "malaria_testing": malaria_testing(source),
        "dhis2_vs_workbook": source["dhis2_vs_workbook_2024"],
        "dhis2_region_week": source["dhis2_cases_region_week"],
        "dhis2_completeness": source["dhis2_completeness_region_week"],
        "meningitis_week": source["meningitis_district_week"],
        "validation_checks": source["validation_checks"],
    }
    for name, table in tables.items():
        table.to_csv(out / f"{name}.csv", index=False, encoding="utf-8")
    district_week.to_csv(out / "district_week.csv.gz", index=False, encoding="utf-8", compression={"method": "gzip", "mtime": 0})

    geo = processed / "regions.geojson"
    if geo.exists():
        shutil.copyfile(geo, out / "regions.geojson")
    logo = project / "app" / "www" / "logo_msf.png"
    if logo.exists():
        shutil.copyfile(logo, out / "logo.png")

    model_dir = out / "models"
    model_dir.mkdir(exist_ok=True)
    found = []
    for name in MODEL_TABLES:
        if (models / f"{name}.csv").exists():
            shutil.copyfile(models / f"{name}.csv", model_dir / f"{name}.csv")
            found.append(name)

    years = source["mdo_years"]
    info = {
        "synthetic": synthetic,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "first_year": int(years.year.min()), "last_year": int(years.year.max()),
        "last_week_of_last_year": int(years.last_week.iloc[-1]),
        "diseases": int(source["mdo_summary"].disease.nunique()),
        "regions": int(source["district_regions"].region.nunique()),
        "districts": int(years.districts.max()),
        "district_weeks": int(len(district_week)),
        "model_tables": found,
    }
    (out / "build_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", default=os.environ.get("MDO_NIGER_PROJECT", str(REPO.parent / "MDO - Niger")))
    p.add_argument("--out", default=str(REPO / "data"))
    a = p.parse_args()
    info = build(Path(a.project), Path(a.out))
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
