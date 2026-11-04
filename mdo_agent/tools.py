"""Read-only tools for the MDO Niger assistant.

Every tool reads the tables in data/ (built by build_agent_data.py) and nothing else. Each call is logged in TRACE so
the answer can show where its numbers came from. Each table is kept under a result id that publish_result can show to
the reader, together with the cautions that apply to it. A wrong argument returns a message, so the model can correct
the call instead of failing.
"""
from __future__ import annotations

import difflib
import functools
import json
import os
from collections.abc import Callable
from functools import cache
from pathlib import Path

import pandas as pd
from anthropic import beta_tool

from . import results as res
from .catalog import AMBIGUOUS, DISEASES, FIRST_STABLE_DISTRICT_YEAR, MODEL_TABLES, BadInput, caveats_for, norm, resolve_disease

AGENT_DIR = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("MDO_AGENT_DATA", AGENT_DIR / "data"))
LIMITS = json.loads((AGENT_DIR / "limits.json").read_text(encoding="utf-8"))
TRACE: list[dict] = []
RESULTS: dict[str, dict] = {}
PUBLISHED: list[dict] = []
ON_EVENT: list[Callable[[dict], None]] = []
MAX_ROWS = LIMITS["max_rows_to_model"]
LEVELS = ("national", "region", "district")
MEASURES = ("incidence_per_100k", "cases", "deaths", "cfr_pct")


def begin_question(on_event: Callable[[dict], None] | None = None) -> None:
    """Forget the tool calls and results of the previous question. The agent runs one question at a time."""
    TRACE.clear()
    RESULTS.clear()
    PUBLISHED.clear()
    ON_EVENT[:] = [on_event] if on_event else []


@cache
def _table(name: str) -> pd.DataFrame:
    path = DATA / name
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Build it first: python build_agent_data.py")
    return pd.read_csv(path, low_memory=False, keep_default_na=True)


def _log(tool: str, **args) -> dict:
    call = {"tool": tool, "args": {k: v for k, v in args.items() if v not in ("", None, 0)}}
    TRACE.append(call)
    for f in ON_EVENT:
        f({"type": "tool", "n": len(TRACE), **call})
    return call


def _csv(df: pd.DataFrame) -> str:
    if len(df) > MAX_ROWS:
        return f"{len(df)} rows: too many, narrow the request (years, places or weeks)."
    shown = df.copy()
    for col in shown.select_dtypes("float").columns:  # counts stay whole numbers in the text
        if (shown[col].dropna() % 1 == 0).all():
            shown[col] = shown[col].astype("Int64")
    return shown.to_csv(index=False, float_format="%.2f", lineterminator="\n")


@cache
def _is_demo() -> bool:
    path = DATA / "build_info.json"
    return path.exists() and bool(json.loads(path.read_text(encoding="utf-8")).get("synthetic"))


def _result(df: pd.DataFrame, call: dict, title: str, caveats: list[str] | None = None, head: str = "") -> str:
    """Keep a table for publish_result and return it to the model with its result id and its cautions."""
    text = _csv(df)
    if len(df) > MAX_ROWS:
        return text
    if df.empty:
        return "No rows for this request. If the disease was not on the sheets that year this is no data, not zero. " + " ".join(caveats or [])
    caveats = list(caveats or [])
    if _is_demo():
        caveats.insert(0, "SYNTHETIC DEMO DATA: every value is invented.")
    rid = f"R{len(RESULTS) + 1}"
    RESULTS[rid] = {"id": rid, "rows": df.reset_index(drop=True), "title": title, "tool": call["tool"], "args": call["args"], "caveats": caveats}
    notes = "".join(f"# caution: {c}\n" for c in caveats)
    return f"result_id: {rid}\n{notes}{head}{text}"


def _answers_errors(fn):
    """Return a wrong argument or an unbuilt table as text for the model, not as a crash."""
    @functools.wraps(fn)
    def run(*args, **kw):
        try:
            return fn(*args, **kw)
        except BadInput as e:
            return str(e)
    return run


def tool(fn):
    return beta_tool(_answers_errors(fn))


def _last_weeks() -> dict[int, int]:
    y = _table("years.csv")
    return dict(zip(y.year.astype(int), y.last_week.astype(int), strict=True))


def _years(text: str) -> list[int]:
    """'2019', '2019,2021' or '2017-2023'. Empty means all years."""
    known = sorted(_last_weeks())
    if not str(text).strip():
        return known
    out: list[int] = []
    for part in str(text).replace(" ", "").split(","):
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                out += list(range(int(a), int(b) + 1))
            elif part:
                out.append(int(part))
        except ValueError as e:
            raise BadInput(f"Years look like 2019, 2019,2021 or 2017-2023; got '{text}'.") from e
    unknown = sorted(set(out) - set(known))
    if unknown:
        raise BadInput(f"No data for {unknown}: the series runs from {known[0]} to {known[-1]}.")
    return sorted(set(out))


def _level(level: str, allowed: tuple[str, ...] = LEVELS) -> str:
    value = norm(level) or allowed[0]
    if value not in allowed:
        raise BadInput(f"level must be {', '.join(allowed)}.")
    return value


@cache
def _place_index() -> dict[str, dict[str, str]]:
    p = _table("places.csv")
    return {"region": {norm(x): x for x in p.region.unique()}, "district": {norm(x): x for x in p.district.unique()}}


def _places(level: str, text: str) -> list[str]:
    """Names in the data for comma-separated places, accents and case ignored. Empty means all."""
    if level == "national" or not str(text).strip():
        return []
    index = _place_index()[level]
    out = []
    for raw in str(text).split(","):
        key = norm(raw)
        if not key:
            continue
        if key not in index:
            close = difflib.get_close_matches(key, list(index), n=3, cutoff=0.6)
            hint = f" Did you mean {', '.join(index[c] for c in close)}?" if close else " Call list_places to see them."
            other = "district" if level == "region" else "region"
            if key in _place_index()[other]:
                hint = f" '{raw.strip()}' is a {other}: use level={other}."
            raise BadInput(f"Unknown {level} '{raw.strip()}'.{hint}")
        out.append(index[key])
    return out


def _rates(t: pd.DataFrame) -> pd.DataFrame:
    t["cfr_pct"] = (100 * t.deaths / t.cases).where(t.cases > 0).round(2)
    t["incidence_per_100k"] = (1e5 * t.cases / t.population).round(2)
    return t


def _cut_to_week(disease: str, level: str, places: list[str], years: list[int], week: int) -> pd.DataFrame:
    """Yearly figures from the weekly tables, stopping every year at the same week."""
    if level == "district":
        w = _table("district_week.csv.gz")
        w = w[(w.disease == disease) & w.year.isin(years) & (w.week <= week)].rename(columns={"district": "place"})
        if places:
            w = w[w.place.isin(places)]
    else:
        w = _table("weekly.csv")
        w = w[(w.disease == disease) & (w.level == level) & w.year.isin(years) & (w.week <= week)]
        if places:
            w = w[w.place.isin(places)]
    got = w.groupby(["year", "place"], as_index=False)[["cases", "deaths"]].sum()
    a = _table("annual.csv")
    pop = a[(a.level == level)][["year", "place", "region", "population"]].drop_duplicates(["year", "place"])
    got = got.merge(pop, how="left", on=["year", "place"])
    got["disease"], got["level"] = disease, level
    last = _last_weeks()
    got["through_week"] = [min(week, last[y]) for y in got.year]
    # A year that ends earlier than the cut is still partial for this comparison.
    got["partial_year"] = [last[y] < week for y in got.year]
    return _rates(got)


ANNUAL_COLS = ["disease", "year", "place", "cases", "deaths", "population", "cfr_pct", "incidence_per_100k", "through_week", "partial_year"]


# ---- What is in the data -----------------------------------------------------------------------------------

@tool
def list_diseases() -> str:
    """List the 25 disease series with their French id, English label, first and last year, total cases and deaths, and peak year.

    Totals run across different periods and definitions: use them to see what exists, not to compare burdens over time."""
    call = _log("list_diseases")
    t = _table("disease_summary.csv").copy()
    t.insert(1, "english", t.disease.map(lambda d: DISEASES[d]["en"] if d in DISEASES else ""))
    return _result(t, call, "Disease series in the data")


@tool
def list_years() -> str:
    """List the years: last week reported, number of districts, national population, and whether the year is complete."""
    call = _log("list_years")
    return _result(_table("years.csv"), call, "Years covered")


@tool
def list_places(region: str = "") -> str:
    """List the health districts and their regions. Districts as they exist from 2017.

    Args:
        region: Optional region name to keep only its districts.
    """
    call = _log("list_places", region=region)
    t = _table("places.csv")
    if region.strip():
        t = t[t.region.isin(_places("region", region))]
    return _result(t.sort_values(["region", "district"]), call, "Regions and districts")


@tool
def get_year_overview(year: int, through_week: int = 0) -> str:
    """All diseases in one year, national: cases, deaths, case fatality and incidence, sorted by cases.

    Args:
        year: The year.
        through_week: Optional week to stop at, to compare with another year at the same point.
    """
    call = _log("get_year_overview", year=year, through_week=through_week)
    _years(str(year))
    a = _table("annual.csv")
    if through_week:
        rows = [_cut_to_week(d, "national", [], [year], through_week) for d in a[a.year == year].disease.unique()]
        t = pd.concat(rows, ignore_index=True)
    else:
        t = a[(a.year == year) & (a.level == "national")]
    t = t[ANNUAL_COLS].sort_values("cases", ascending=False)
    t.insert(1, "english", t.disease.map(lambda d: DISEASES[d]["en"] if d in DISEASES else ""))
    cautions = ["Case fatality rests on notified cases and is unstable on few cases. Confirmed and suspected malaria overlap: do not add them."]
    if not through_week and _last_weeks()[year] < 52:
        cautions.append(f"Partial year: {year} stops at week {_last_weeks()[year]}.")
    return _result(t, call, f"All diseases, {year}", cautions)


# ---- Counts and rates ---------------------------------------------------------------------------------------

@tool
def get_disease_trend(disease: str, level: str = "national", places: str = "", years: str = "", through_week: int = 0) -> str:
    """Yearly cases, deaths, population, case fatality and incidence for one disease.

    District results start in 2017, because districts are not comparable before. For a fair comparison with 2024, pass
    through_week to cut every year to the same week.

    Args:
        disease: A disease, e.g. Méningite or measles. Malaria and malnutrition need the exact series.
        level: national, region or district.
        places: Optional comma-separated regions or districts. Empty = all at that level.
        years: Optional, e.g. 2019, or 2019,2021, or 2017-2023. Empty = all.
        through_week: Optional last week of every year, e.g. 43.
    """
    call = _log("get_disease_trend", disease=disease, level=level, places=places, years=years, through_week=through_week)
    dz, lev, ys = resolve_disease(disease), _level(level), _years(years)
    pl = _places(lev, places)
    dropped = lev == "district" and min(ys) < FIRST_STABLE_DISTRICT_YEAR
    if lev == "district":
        ys = [y for y in ys if y >= FIRST_STABLE_DISTRICT_YEAR]
        if not ys:
            raise BadInput("Districts are comparable only from 2017: use rank_places for one earlier year, or level=region.")
    if through_week:
        t = _cut_to_week(dz, lev, pl, ys, through_week)
    else:
        a = _table("annual.csv")
        t = a[(a.disease == dz) & (a.level == lev) & a.year.isin(ys)]
        if pl:
            t = t[t.place.isin(pl)]
    t = t[ANNUAL_COLS].sort_values(["place", "year"])
    cautions = caveats_for(dz, ys, lev, bool(through_week), _last_weeks())
    if dropped:
        cautions.append("Years before 2017 are left out at district level.")
    return _result(t, call, f"{DISEASES[dz]['en']}: cases and incidence by year", cautions)


@tool
def get_weekly_curve(disease: str, years: str = "", level: str = "national", places: str = "", weeks: str = "") -> str:
    """Weekly cases and deaths for one disease. reports_not_received counts the district reports missing that week (2015-2023).
    At district level each row has the report status, and a report not received has empty cases: unknown, not zero.

    Args:
        disease: A disease.
        years: Optional years. Empty = all (often too many rows: narrow it).
        level: national, region or district.
        places: Optional comma-separated regions or districts.
        weeks: Optional range of weeks, e.g. 1-20.
    """
    call = _log("get_weekly_curve", disease=disease, years=years, level=level, places=places, weeks=weeks)
    dz, lev, ys = resolve_disease(disease), _level(level), _years(years)
    pl = _places(lev, places)
    if lev == "district":
        t = _table("district_week.csv.gz")
        t = t[(t.disease == dz) & t.year.isin(ys)].rename(columns={"district": "place"})[["year", "week", "place", "region", "cases", "deaths", "report"]]
    else:
        t = _table("weekly.csv")
        t = t[(t.disease == dz) & (t.level == lev) & t.year.isin(ys)][["year", "week", "place", "cases", "deaths", "reports_not_received"]]
    if pl:
        t = t[t.place.isin(pl)]
    if str(weeks).strip():
        try:
            lo, _, hi = str(weeks).partition("-")
            t = t[t.week.between(int(lo), int(hi or lo))]
        except ValueError as e:
            raise BadInput(f"weeks looks like 1-20; got '{weeks}'.") from e
    t = t.sort_values(["place", "year", "week"])
    return _result(t, call, f"{DISEASES[dz]['en']}: weekly cases", caveats_for(dz, ys, lev, False, _last_weeks()))


@tool
def rank_places(disease: str, year: int, level: str = "region", measure: str = "incidence_per_100k", through_week: int = 0, top: int = 0) -> str:
    """Rank regions or districts for one disease in one year, with the national figure at the head of the result.

    Args:
        disease: A disease.
        year: The year.
        level: region or district.
        measure: incidence_per_100k, cases, deaths or cfr_pct.
        through_week: Optional week to stop at.
        top: Optional number of places to keep, e.g. 10.
    """
    call = _log("rank_places", disease=disease, year=year, level=level, measure=measure, through_week=through_week, top=top)
    dz, lev = resolve_disease(disease), _level(level, ("region", "district"))
    _years(str(year))
    if measure not in MEASURES:
        raise BadInput(f"measure must be {', '.join(MEASURES)}.")
    a = _table("annual.csv")
    if through_week:
        t = _cut_to_week(dz, lev, [], [year], through_week)
        n = _cut_to_week(dz, "national", [], [year], through_week)
    else:
        t = a[(a.disease == dz) & (a.level == lev) & (a.year == year)]
        n = a[(a.disease == dz) & (a.level == "national") & (a.year == year)]
    t = t[["place", "region", "cases", "deaths", "population", "cfr_pct", "incidence_per_100k", "through_week"]].sort_values(measure, ascending=False)
    t.insert(0, "rank", range(1, len(t) + 1))
    t["rank"] = t["rank"].where(t[measure].notna())
    if top:
        t = t.head(top)
    head = ""
    if len(n):
        first = n.iloc[0]
        head = f"# national {year}: cases={first.cases:.0f}, deaths={first.deaths:.0f}, cfr_pct={first.cfr_pct}, incidence_per_100k={first.incidence_per_100k}\n"
    cautions = caveats_for(dz, [year], lev, bool(through_week), _last_weeks())
    if measure == "cfr_pct":
        cautions.append("Case fatality on few cases is unstable: read it with the number of cases.")
    return _result(t, call, f"{DISEASES[dz]['en']}, {year}: {measure.replace('_', ' ')} by {lev}", cautions, head)


@tool
def compare_years(disease: str, year_a: int, year_b: int, level: str = "national", places: str = "") -> str:
    """Compare two years like for like: both are cut to the last week reported in both. Gives cases, deaths and incidence in each year
    and the change. Descriptive: no confidence interval; model estimates are in get_model_result.

    Args:
        disease: A disease.
        year_a: The earlier year.
        year_b: The later year.
        level: national, region or district.
        places: Optional comma-separated regions or districts.
    """
    call = _log("compare_years", disease=disease, year_a=year_a, year_b=year_b, level=level, places=places)
    dz, lev = resolve_disease(disease), _level(level)
    _years(f"{year_a},{year_b}")
    pl = _places(lev, places)
    if lev == "district" and min(year_a, year_b) < FIRST_STABLE_DISTRICT_YEAR:
        raise BadInput("Districts are comparable only from 2017: use level=region for earlier years.")
    last = _last_weeks()
    week = min(last[year_a], last[year_b])
    t = _cut_to_week(dz, lev, pl, [year_a, year_b], week)
    wide = t.pivot(index="place", columns="year", values=["cases", "deaths", "incidence_per_100k"])
    wide.columns = [f"{name}_{y}" for name, y in wide.columns]
    wide = wide.reset_index()
    if year_a not in set(t.year) or year_b not in set(t.year):
        raise BadInput(f"{DISEASES[dz]['en']} has no data for one of {year_a} and {year_b}: this is no data, not zero. Call list_diseases.")
    a, b = wide[f"cases_{year_a}"], wide[f"cases_{year_b}"]
    wide["cases_change_pct"] = (100 * (b - a) / a).where(a > 0).round(1)
    ia, ib = wide[f"incidence_per_100k_{year_a}"], wide[f"incidence_per_100k_{year_b}"]
    wide["incidence_change_pct"] = (100 * (ib - ia) / ia).where(ia > 0).round(1)
    wide.insert(1, "weeks_compared", f"1-{week}")
    cautions = caveats_for(dz, [year_a, year_b], lev, True, last)
    return _result(wide, call, f"{DISEASES[dz]['en']}: {year_a} vs {year_b}, weeks 1-{week}", cautions)


@tool
def get_seasonality(disease: str, region: str = "") -> str:
    """The usual seasonal curve: mean, lowest and highest weekly cases by week of the year, over complete years, with the peak week.

    Args:
        disease: A disease.
        region: Optional region. Empty = national.
    """
    call = _log("get_seasonality", disease=disease, region=region)
    dz = resolve_disease(disease)
    lev = "region" if region.strip() else "national"
    pl = _places(lev, region)
    complete = [y for y, w in _last_weeks().items() if w >= 52]
    t = _table("weekly.csv")
    t = t[(t.disease == dz) & (t.level == lev) & t.year.isin(complete)]
    if pl:
        t = t[t.place.isin(pl)]
    g = t.groupby("week").cases
    s = pd.DataFrame({"mean_cases": g.mean().round(1), "lowest": g.min(), "highest": g.max(), "years": g.count()}).reset_index()
    head = ""
    if len(s) and s.mean_cases.max() > 0:
        peak = s.loc[s[s.years >= 3].mean_cases.idxmax()]
        head = f"# peak week: {int(peak.week)} (mean {peak.mean_cases} cases per week, over {int(peak.years)} years)\n"
    where = pl[0] if pl else "Niger"
    cautions = ["Week 53 exists in 2015 and 2020 only.", "Partial years are left out."]
    used = sorted(t.year.unique().tolist())
    return _result(s, call, f"{DISEASES[dz]['en']}: seasonal curve, {where}", caveats_for(dz, used, lev, True, None) + cautions, head)


@tool
def get_malaria_testing(years: str = "", level: str = "national", places: str = "") -> str:
    """Malaria tests done, positive tests and positivity, 2015-2020 (not available from 2021). District level from 2017.

    Args:
        years: Optional years.
        level: national, region or district.
        places: Optional comma-separated regions or districts.
    """
    call = _log("get_malaria_testing", years=years, level=level, places=places)
    lev, ys = _level(level), _years(years)
    pl = _places(lev, places)
    t = _table("malaria_testing.csv")
    t = t[(t.level == lev) & t.year.isin(ys)]
    if pl:
        t = t[t.place.isin(pl)]
    return _result(t.drop(columns="level").sort_values(["place", "year"]), call, "Malaria tests and positivity",
                   ["Tests are recorded only for 2015-2020. Positivity also depends on who is tested."])


# ---- Surveillance tools -------------------------------------------------------------------------------------

@tool
def get_meningitis_alerts(years: str = "", by: str = "week", region: str = "", status: str = "") -> str:
    """Districts crossing the WHO meningitis thresholds. by=week lists each district-week over a threshold; by=district and by=year count them.

    Args:
        years: Optional years. Empty = all.
        by: week, district or year.
        region: Optional region.
        status: Optional alert or epidemic. Empty = both. Rows under the threshold are never listed.
    """
    call = _log("get_meningitis_alerts", years=years, by=by, region=region, status=status)
    ys = _years(years)
    pl = _places("region", region)
    stat = norm(status)
    if stat and stat not in ("alert", "epidemic"):
        raise BadInput("status must be alert or epidemic.")
    if by not in ("week", "district", "year"):
        raise BadInput("by must be week, district or year.")
    t = _table("meningitis_week.csv")
    t = t[t.year.isin(ys)]
    if pl:
        t = t[t.region.isin(pl)]
    over = t[t.status.isin([stat] if stat else ["alert", "epidemic"])]
    cautions = ["WHO thresholds applied to whole districts: a sub-district outbreak can stay under them. This is not an official declaration."]
    if min(ys) < FIRST_STABLE_DISTRICT_YEAR:
        cautions.append("Districts are comparable only from 2017: counts of district-weeks before and after are not like for like.")
    if by == "week":
        out = over[["year", "week", "region", "district", "population", "cases", "rate_per_100k", "status"]].sort_values(["year", "week", "district"])
    else:
        keys = ["year"] if by == "year" else ["year", "region", "district"]
        out = over.groupby(keys + ["status"]).size().unstack("status", fill_value=0).reset_index()
        for col in ("alert", "epidemic"):
            if col not in out.columns:
                out[col] = 0
        out = out.rename(columns={"alert": "alert_weeks", "epidemic": "epidemic_weeks"})
        out.columns.name = None
        if by == "year":
            count = t.groupby("year").agg(district_weeks=("week", "size")).reset_index()
            out = count.merge(out, how="left", on="year").fillna({"alert_weeks": 0, "epidemic_weeks": 0})
            out[["alert_weeks", "epidemic_weeks"]] = out[["alert_weeks", "epidemic_weeks"]].astype(int)
    return _result(out, call, "Meningitis: districts over the WHO thresholds", cautions)


@tool
def get_reporting(years: str = "", level: str = "national", places: str = "", by: str = "year") -> str:
    """Reporting completeness (share of district reports received) and timeliness (share on time). 2015-2023 come from the weekly grids;
    2024 has only cumulative percentages to week 43, or, with by=week, DHIS2 facility completeness by region to week 37.

    Args:
        years: Optional years.
        level: national, region or district.
        places: Optional comma-separated regions or districts.
        by: year or week.
    """
    call = _log("get_reporting", years=years, level=level, places=places, by=by)
    lev, ys = _level(level), _years(years)
    pl = _places(lev, places)
    if by not in ("year", "week"):
        raise BadInput("by must be year or week.")
    grid = _table("reporting_grid.csv")
    grid = grid[grid.year.isin(ys)].assign(place="Niger" if lev == "national" else grid.get(lev, ""))
    if pl:
        grid = grid[grid.place.isin(pl)]
    keys = ["year", "place"] + (["week"] if by == "week" else [])
    t = grid.groupby(keys).agg(reports_expected=("received", "size"), reports_not_received=("received", lambda s: int((s == 0).sum())),
                               completeness_pct=("received", lambda s: round(100 * s.mean(), 1)), timeliness_pct=("on_time", lambda s: round(100 * s.mean(), 1))).reset_index()
    cautions = ["A report received says nothing about how many facilities fed it, nor about cases that never reached a facility."]
    if 2024 in ys:
        if by == "year":
            r24 = _table("reporting_2024.csv")
            r24 = r24[r24.level == lev].rename(columns={"name": "place"})
            if pl:
                r24 = r24[r24.place.isin(pl)]
            t = pd.concat([t, r24[["year", "place", "completeness_pct", "timeliness_pct"]]], ignore_index=True)
            cautions.append("2024 is cumulative to week 43, read from the workbook: the number of reports is not available.")
        elif lev == "region":
            d = _table("dhis2_completeness.csv").rename(columns={"region": "place"}).assign(year=2024, source="DHIS2 facility completeness")
            if pl:
                d = d[d.place.isin(pl)]
            t = pd.concat([t, d[["year", "place", "week", "completeness_pct", "source"]]], ignore_index=True)
            cautions.append("2024 weekly figures are DHIS2 facility completeness to week 37: a different measure from the district reports of other years.")
        else:
            cautions.append("2024 has no weekly district reporting grid: use level=region for DHIS2 facility completeness.")
    if lev == "district" and min(ys) < FIRST_STABLE_DISTRICT_YEAR:
        cautions.append("Districts are comparable only from 2017.")
    return _result(t.sort_values(keys), call, "Reporting completeness and timeliness", cautions)


@tool
def get_maternal_deaths(years: str = "", level: str = "national", places: str = "", by: str = "year") -> str:
    """Maternal deaths notified and investigated, 2015-2021. No ratio per live births: the data do not support one.

    Args:
        years: Optional years.
        level: national, region or district.
        places: Optional comma-separated regions or districts.
        by: year or week.
    """
    call = _log("get_maternal_deaths", years=years, level=level, places=places, by=by)
    lev, ys = _level(level), _years(years)
    pl = _places(lev, places)
    if by not in ("year", "week"):
        raise BadInput("by must be year or week.")
    t = _table("maternal_deaths.csv")
    t = t[t.year.isin(ys)].assign(place="Niger" if lev == "national" else t.get(lev, ""))
    if pl:
        t = t[t.place.isin(pl)]
    keys = ["year", "place"] + (["week"] if by == "week" else [])
    # min_count: a year where nothing was recorded stays empty instead of becoming a zero.
    out = t.groupby(keys)[["deaths_notified", "deaths_investigated"]].sum(min_count=1).reset_index()
    out.loc[out.year == 2015, "deaths_investigated"] = float("nan")
    out["investigated_pct"] = (100 * out.deaths_investigated / out.deaths_notified).where(out.deaths_notified > 0).round(1)
    cautions = ["Notified deaths: not the true number of maternal deaths. Investigated deaths are not recorded in 2015."]
    if max(ys) > 2021:
        cautions.append("Maternal deaths are on the sheets to 2021 only.")
    if lev == "district" and min(ys) < FIRST_STABLE_DISTRICT_YEAR:
        cautions.append("Districts are comparable only from 2017.")
    return _result(out.sort_values(keys), call, "Maternal deaths notified and investigated", cautions)


@tool
def compare_dhis2_2024(disease: str = "", by: str = "disease", region: str = "") -> str:
    """The DHIS2 extract for 2024 (weeks 1-37) against the weekly workbook.

    by=disease: totals of both sources per disease, weeks in common. by=week: both sources week by week for one disease.
    by=region: DHIS2 cases and deaths by region for one disease (the workbook comparison is national only).

    Args:
        disease: A disease; required unless by=disease.
        by: disease, week or region.
        region: Optional region, with by=region: gives its weeks.
    """
    call = _log("compare_dhis2_2024", disease=disease, by=by, region=region)
    if by not in ("disease", "week", "region"):
        raise BadInput("by must be disease, week or region.")
    dz = resolve_disease(disease) if str(disease).strip() else ""
    if by != "disease" and not dz:
        raise BadInput(f"by={by} needs a disease.")
    c = _table("dhis2_vs_workbook.csv")
    if dz:
        c = c[c.disease == dz]
    both = c.dropna(subset=["workbook_cases", "dhis2_cases"])
    cautions = ["DHIS2 covers 2024 weeks 1-37 only. The two sources can differ; the workbook is the main series."]
    if by == "disease":
        t = both.groupby("disease")[["workbook_cases", "dhis2_cases"]].sum().reset_index()
        t["weeks_compared"] = t.disease.map(both.groupby("disease").week.nunique())
        t["difference_pct"] = (100 * (t.dhis2_cases - t.workbook_cases) / t.workbook_cases).where(t.workbook_cases > 0).round(1)
        t = t.sort_values("workbook_cases", ascending=False)
    elif by == "week":
        t = both.sort_values("week")
    else:
        d = _table("dhis2_region_week.csv")
        d = d[d.disease == dz]
        if region.strip():
            t = d[d.region.isin(_places("region", region))].sort_values(["region", "week"])
        else:
            t = d.groupby("region", as_index=False)[["cases", "deaths"]].sum()
    return _result(t, call, "DHIS2 and workbook, 2024", cautions)


@tool
def get_validation_checks(year: int = 0, status: str = "", check: str = "") -> str:
    """How the parsed data compare with the totals written in the source files: summary by check and status, or the rows themselves
    when status is given (match, within 1%, differs, no reference).

    Args:
        year: Optional year.
        status: Optional status to list its rows, e.g. differs.
        check: Optional check: sheet_total, synthese, completeness_nat, dhis2_totals, dhis2_cumul, dhis2_spare, mas_2016_rate, mas_2016_region.
    """
    call = _log("get_validation_checks", year=year, status=status, check=check)
    v = _table("validation_checks.csv")
    if year:
        v = v[v.year == year]
    if check.strip():
        v = v[v.check == check.strip()]
    if status.strip():
        return _result(v[v.status == status.strip()], call, f"Validation checks: {status.strip()}")
    t = v.groupby(["check", "status"]).size().rename("items").reset_index()
    return _result(t, call, "Validation checks against the source files")


@tool
def search_data_notes(term: str = "") -> str:
    """The documented rules and limits of the data: definitions, denominators, breaks in the series, missing years. Empty term lists all.
    Use it to explain a jump in a series or a figure that differs from another source.

    Args:
        term: A word in French or English, e.g. denominators, 2024, malaria, districts.
    """
    call = _log("search_data_notes", term=term)
    notes = pd.read_csv(Path(__file__).with_name("data_notes.csv"))
    key = norm(term)
    aliases = {"paludisme": "malaria", "denominateur": "denominators", "semaine": "week", "rapportage": "report", "completude": "completeness", "promptitude": "timeliness",
               "malnutrition": "malnutrition", "meningite": "meningitis", "deces maternels": "maternal"}
    key = aliases.get(key, key)
    if key:
        notes = notes[notes.apply(lambda r: key in norm(r.topic) or key in norm(r.note), axis=1)]
    if notes.empty:
        return f"No note mentions '{term}'. Call search_data_notes with no term to read them all."
    return _result(notes, call, "Data notes")


# ---- Models ---------------------------------------------------------------------------------------------------

@tool
def list_model_results() -> str:
    """List the tables of estimated statistical models: trends with confidence intervals, seasonality, spread between districts, forecast skill, reporting, case fatality, outbreak detection."""
    call = _log("list_model_results")
    rows = [{"table": name, **info, "available": (DATA / "models" / f"{name}.csv").exists()} for name, info in MODEL_TABLES.items()]
    return _result(pd.DataFrame(rows), call, "Model result tables")


@tool
def get_model_result(table: str, term: str = "") -> str:
    """One table of model estimates, unchanged. These are the only confidence intervals and tests available.

    Args:
        table: A table from list_model_results, e.g. t03_year_irr_long.
        term: Optional word to keep matching rows, e.g. Meningitis (English disease names) or 2024.
    """
    call = _log("get_model_result", table=table, term=term)
    name = table.strip()
    if name not in MODEL_TABLES:
        close = difflib.get_close_matches(name, list(MODEL_TABLES), n=1, cutoff=0.4)
        raise BadInput(f"Unknown table '{table}'." + (f" Did you mean {close[0]}?" if close else " Call list_model_results."))
    if not (DATA / "models" / f"{name}.csv").exists():
        raise BadInput(f"{name} is not built: run the project's analysis/run_models.R, then build_agent_data.py.")
    t = _table(f"models/{name}.csv")
    key = norm(term)
    if key:
        key = {norm(k): norm(v["en"]) for k, v in DISEASES.items() if norm(k) not in AMBIGUOUS}.get(key, key)
        t = t[t.apply(lambda r: any(key in norm(v) for v in r.values), axis=1)]
    cautions = ["Estimates on notified cases, 2017-2024 district panels: associations, not causal effects. Year effects also absorb changes in reporting, testing and definitions."]
    if MODEL_TABLES[name]["topic"] == "forecast":
        cautions.append("A validation on past weeks, not a forecast of the coming weeks.")
    return _result(t, call, MODEL_TABLES[name]["about"].split(":")[0], cautions)


# ---- The reader -----------------------------------------------------------------------------------------------

@cache
def regions() -> frozenset[str]:
    return frozenset(_table("places.csv").region.unique())


@tool
def publish_result(result_id: str, chart: str = "table", x: str = "", y: str = "", series: str = "", title: str = "", note: str = "") -> str:
    """Show a table returned by another tool to the reader, with an optional chart and a CSV download. Call it once, last, for the table that best supports your answer.
    You choose columns and chart type; the server checks them, refuses a chart the data cannot support, and adds the table's cautions itself.

    Choosing: yearly trend -> line, x="year", y="incidence_per_100k", series="place" if several; weekly curves -> line, x="week", y="cases", series="year";
    ranking -> bar, x="place", y=the measure; one value per region in one year -> map, x="place", y=the measure; week by year -> heatmap, x="week", y="year", series="cases"; otherwise table.

    Args:
        result_id: The result_id printed by the tool, e.g. R2.
        chart: table, line, bar, scatter, heatmap or map.
        x: Column for the x axis; for a map, the region column.
        y: Column for the y axis; for a map, the value to colour by.
        series: Column that splits lines or colours; for a heatmap, the numeric column of the cells.
        title: Short title stating the finding or the subject.
        note: Optional one-line remark shown under the chart.
    """
    _log("publish_result", result_id=result_id, chart=chart, x=x, y=y, series=series)
    stored = RESULTS.get(result_id.strip())
    if stored is None:
        return f"Unknown result_id '{result_id}'. Available: {list(RESULTS) or 'none yet'}."
    try:
        published = res.build_publication(stored, chart, x, y, series, title, note, LIMITS, regions())
    except res.PublishError as e:
        return f"Not published: {e} Columns: {list(stored['rows'].columns)}."
    PUBLISHED[:] = [published]
    return f"Published {result_id} ({published['row_count']} rows, chart: {published['chart']['type'] if published['chart'] else 'none'})."


def build_info() -> dict:
    return json.loads((DATA / "build_info.json").read_text(encoding="utf-8"))


def regions_geojson() -> dict | None:
    path = DATA / "regions.geojson"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


TOOLS = [list_diseases, list_years, list_places, get_year_overview, get_disease_trend, get_weekly_curve, rank_places, compare_years, get_seasonality,
         get_malaria_testing, get_meningitis_alerts, get_reporting, get_maternal_deaths, compare_dhis2_2024, get_validation_checks,
         search_data_notes, list_model_results, get_model_result, publish_result]
