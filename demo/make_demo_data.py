"""An invented surveillance system: fake project outputs in the same layout as msf-mdo-niger, passed through the real
build_agent_data.py. Every value is invented and marked as synthetic. It lets anyone try the assistant, and lets the
tests run on a clean checkout, with no real data.

    python demo/make_demo_data.py            # writes demo_data/
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from build_agent_data import build as build_tables  # noqa: E402
from mdo_agent.catalog import MODEL_TABLES  # noqa: E402

REGIONS = ["Agadez", "Diffa", "Dosso", "Maradi", "Niamey", "Tahoua", "Tillabéri", "Zinder"]
YEARS = {2015: 53, 2016: 52, 2017: 52, 2018: 52, 2019: 52, 2020: 53, 2021: 52, 2022: 52, 2023: 52, 2024: 43}
# name: (mean weekly cases per 100,000, peak week, case fatality, first year, last year)
SERIES = {
    "Paludisme confirmé": (60.0, 38, 0.001, 2015, 2024), "Paludisme suspect": (80.0, 38, 0.001, 2015, 2024),
    "Paludisme (femmes enceintes)": (2.0, 38, 0.001, 2015, 2024), "Rougeole": (0.3, 14, 0.01, 2015, 2024),
    "Méningite": (0.2, 12, 0.06, 2015, 2024), "Choléra": (0.05, 33, 0.03, 2015, 2024), "Diphtérie": (0.03, 40, 0.05, 2015, 2024),
    "Malnutrition sévère": (9.0, 30, 0.001, 2015, 2021), "COVID-19": (0.02, 8, 0.04, 2021, 2024), "Dengue": (0.01, 42, 0.03, 2023, 2024),
    "Coqueluche": (0.02, 20, 0.001, 2015, 2024), "SRAS": (0.0, 1, 0.0, 2015, 2017),
}


def geometry() -> dict:
    """Eight rectangles in a row of two: invented shapes, clockwise rings."""
    features = []
    for i, region in enumerate(REGIONS):
        x, y = i % 4, i // 4
        ring = [[x, y], [x, y + 1], [x + 1, y + 1], [x + 1, y], [x, y]]
        features.append({"type": "Feature", "properties": {"region": region}, "geometry": {"type": "Polygon", "coordinates": [ring]}})
    return {"type": "FeatureCollection", "features": features}


def make_project(root: Path) -> None:
    rng = np.random.default_rng(2015)
    proc, app, models = root / "data" / "processed", root / "app" / "data", root / "analysis" / "output" / "tables"
    for p in (proc, app, models):
        p.mkdir(parents=True, exist_ok=True)

    districts = [(r, f"{r} {side}") for r in REGIONS for side in ("Nord", "Sud", "Centre")]
    pop0 = {d: 150_000 + 40_000 * (i % 7) for i, (_, d) in enumerate(districts)}
    rows, grid = [], []
    for year, last in YEARS.items():
        # Fewer districts before 2017, as in the real series: 'Centre' does not exist yet.
        here = [(r, d) for r, d in districts if year >= 2017 or not d.endswith("Centre")]
        pops = {d: round(pop0[d] * 1.03 ** (year - 2015)) for _, d in here}
        for week in range(1, last + 1):
            for region, district in here:
                status = "N" if rng.random() < 0.005 else ("L" if rng.random() < 0.1 else "T")
                if year <= 2023:
                    grid.append((year, week, region, district, status, int(status != "N"), int(status == "T")))
                for name, (rate, peak, cfr, first, final) in SERIES.items():
                    if not first <= year <= final or (name == "Paludisme (femmes enceintes)" and year in (2020, 2021)):
                        continue
                    season = 1.5 + np.cos(2 * np.pi * (week - peak) / 52)
                    mean = rate * season * pops[district] / 1e5
                    if name == "Méningite" and region == "Zinder" and year in (2018, 2022) and 10 <= week <= 14:
                        mean *= 30  # an invented outbreak, so that the thresholds have something to find
                    cases = int(rng.poisson(mean))
                    deaths = int(rng.binomial(cases, cfr))
                    if name == "Paludisme confirmé" and year <= 2020:
                        deaths = 0
                    tested = cases + int(rng.poisson(mean * 0.5) + 1) if name == "Paludisme confirmé" and year <= 2020 else np.nan
                    rows.append((year, week, region, district, pops[district], name, cases, deaths, tested))
    long = pd.DataFrame(rows, columns=["year", "week", "region", "district", "population", "disease", "cases", "deaths", "tested"])
    long.to_csv(proc / "mdo_long.csv", index=False)
    pd.DataFrame(districts, columns=["region", "district"])[["district", "region"]].to_csv(proc / "district_regions.csv", index=False)
    grid = pd.DataFrame(grid, columns=["year", "week", "region", "district", "status", "received", "on_time"])
    grid.to_csv(proc / "completeness_weekly.csv", index=False)

    def rates(t):
        t["cfr_pct"] = (100 * t.deaths / t.cases).where(t.cases > 0).round(2)
        t["incidence_per_100k"] = (1e5 * t.cases / t.population).round(2)
        return t

    base = long[(long.disease == "Rougeole") & (long.week == 1)]
    npop = base.groupby("year").population.sum()
    rpop = base.groupby(["year", "region"]).population.sum().reset_index()
    dpop = base.groupby(["year", "district"]).population.sum().reset_index()
    years = pd.DataFrame({"year": list(YEARS), "last_week": list(YEARS.values()), "districts": [long[long.year == y].district.nunique() for y in YEARS],
                          "population": [int(npop[y]) for y in YEARS]})
    years["complete"] = years.last_week >= 52
    years.to_csv(proc / "mdo_years.csv", index=False)
    annual = rates(long.groupby(["disease", "year"])[["cases", "deaths"]].sum().reset_index().assign(population=lambda d: d.year.map(npop)))
    annual["partial_year"] = annual.year.map(dict(zip(years.year, ~years.complete, strict=True)))
    annual.to_csv(proc / "mdo_annual.csv", index=False)
    long.groupby(["disease", "year", "week"])[["cases", "deaths"]].sum().reset_index().to_csv(proc / "mdo_weekly.csv", index=False)
    long.groupby(["disease", "year", "week", "region"])[["cases", "deaths"]].sum().reset_index().to_csv(proc / "mdo_weekly_region.csv", index=False)
    rates(long.groupby(["disease", "year", "region"])[["cases", "deaths"]].sum().reset_index().merge(rpop)).to_csv(proc / "mdo_regional.csv", index=False)
    rates(long.groupby(["disease", "year", "region", "district"])[["cases", "deaths"]].sum().reset_index().merge(dpop)).to_csv(proc / "mdo_district.csv", index=False)
    g = annual.groupby("disease")
    summary = pd.DataFrame({"years_reported": g.year.count(), "first_year": g.year.min(), "last_year": g.year.max(), "total_cases": g.cases.sum(), "total_deaths": g.deaths.sum()}).reset_index()
    summary["cfr_pct"] = (100 * summary.total_deaths / summary.total_cases).where(summary.total_cases > 0).round(2)
    peak = annual.loc[g.cases.idxmax(), ["disease", "year", "cases"]].rename(columns={"year": "peak_year", "cases": "peak_cases"})
    summary.merge(peak).to_csv(proc / "mdo_summary.csv", index=False)

    last = grid[grid.year == 2023].groupby("district").agg(c=("received", "mean"), t=("on_time", "mean")).reset_index()
    cum = [{"year": 2024, "through_week": 43, "level": "district", "name": d, "completeness_pct": round(100 * c, 1), "timeliness_pct": round(100 * t, 1), "region": d.rsplit(" ", 1)[0]} for d, c, t in last.itertuples(index=False)]
    cum += [{"year": 2024, "through_week": 43, "level": "region", "name": r, "completeness_pct": 97.0, "timeliness_pct": 88.0, "region": r} for r in REGIONS]
    cum += [{"year": 2024, "through_week": 43, "level": "national", "name": "Niger", "completeness_pct": 97.0, "timeliness_pct": 88.0, "region": ""}]
    pd.DataFrame(cum).to_csv(proc / "completeness_2024_cumulative.csv", index=False)

    mat = long[(long.disease == "Rougeole") & (long.year <= 2021)][["year", "week", "region", "district"]].copy()
    mat["live_births"] = np.where(mat.year <= 2016, 100.0, np.nan)
    mat["deaths_notified"] = rng.poisson(0.2, len(mat))
    mat["deaths_investigated"] = np.where(mat.year == 2015, np.nan, rng.binomial(mat.deaths_notified, 0.3))
    mat.to_csv(proc / "maternal_deaths.csv", index=False)

    w24 = long[(long.year == 2024) & (long.week <= 37)]
    wb = w24.groupby(["disease", "week"]).cases.sum().rename("workbook_cases").reset_index()
    wb["dhis2_cases"] = (wb.workbook_cases * 0.98).round()
    wb.to_csv(proc / "dhis2_vs_workbook_2024.csv", index=False)
    w24.groupby(["disease", "week", "region"])[["cases", "deaths"]].sum().reset_index().to_csv(app / "dhis2_cases_region_week.csv", index=False)
    pd.DataFrame([(w, r, 95.0) for w in range(1, 38) for r in REGIONS], columns=["week", "region", "completeness_pct"]).to_csv(app / "dhis2_completeness_region_week.csv", index=False)

    men = long[long.disease == "Méningite"][["year", "week", "region", "district", "population", "cases"]].copy()
    men["rate_per_100k"] = (1e5 * men.cases / men.population).round(2)
    men["status"] = np.select([men.rate_per_100k >= 10, men.rate_per_100k >= 3], ["epidemic", "alert"], "below")
    men.to_csv(app / "meningitis_district_week.csv", index=False)

    pd.DataFrame([("sheet_total", 2015, "Rougeole", 100, 100, 0, "match"), ("sheet_total", 2016, "Méningite", 50, 52, 2, "differs"), ("synthese", 2017, "Choléra", 30, 30, 0, "match")],
                 columns=["check", "year", "item", "reference", "parsed", "diff", "status"]).to_csv(proc / "validation_checks.csv", index=False)
    (proc / "regions.geojson").write_text(json.dumps(geometry()), encoding="utf-8")

    # Model tables: invented figures in the shape of two of them; the others are absent, as after a build without the models.
    pd.DataFrame([("Meningitis", 2018, 1.1, 0.9, 1.3, 1.2, 1.0, 1.4), ("Meningitis", 2024, 1.4, 1.1, 1.8, 1.5, 1.2, 1.9), ("Measles", 2024, 0.8, 0.6, 1.0, 0.8, 0.6, 1.1)],
                 columns=["disease", "year", "irr", "lo", "hi", "irr_ppml", "lo_ppml", "hi_ppml"]).to_csv(models / "t03_year_irr_long.csv", index=False)
    pd.DataFrame([("Agadez", "12.0% (9.0%–15.0%)", "0.5% (0.1%–1.0%)", "–", "–")], columns=["Region", "Meningitis", "Measles", "Cholera", "Diphtheria"]).to_csv(models / "t15_cfr_by_region.csv", index=False)
    assert {"t03_year_irr_long", "t15_cfr_by_region"} <= set(MODEL_TABLES)


def build(out: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="mdo_demo_") as tmp:
        make_project(Path(tmp))
        return build_tables(Path(tmp), Path(out), synthetic=True)


if __name__ == "__main__":
    target = REPO / "demo_data"
    print(json.dumps(build(target), indent=2))
    print(f"Invented tables in {target}. Set MDO_AGENT_DATA=demo_data to use them.")
