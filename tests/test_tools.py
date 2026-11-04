"""Every tool on the invented system, against values computed here from the table the build wrote."""
import pandas as pd
import pytest

from mdo_agent import tools
from mdo_agent.catalog import BadInput, resolve_disease


def annual():
    return pd.read_csv(tools.DATA / "annual.csv", keep_default_na=True)


# ---- Names ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("name", "disease"), [("meningite", "Méningite"), ("Meningitis", "Méningite"), ("ROUGEOLE", "Rougeole"), ("measles", "Rougeole"),
                                               ("confirmed malaria", "Paludisme confirmé"), ("SAM", "Malnutrition sévère"), ("afp", "PFA")])
def test_disease_names(name, disease):
    assert resolve_disease(name) == disease


@pytest.mark.parametrize("word", ["malaria", "paludisme", "malnutrition", "tetanus"])
def test_a_word_for_several_series_asks_which(word):
    with pytest.raises(BadInput, match="several series"):
        resolve_disease(word)


def test_wrong_arguments_come_back_as_messages_not_crashes():
    assert "several series" in tools.get_disease_trend.call({"disease": "malaria"})
    assert "Unknown disease" in tools.rank_places.call({"disease": "nothing", "year": 2020})
    assert "No data for [2030]" in tools.get_disease_trend.call({"disease": "Rougeole", "years": "2030"})
    assert "Years look like" in tools.get_disease_trend.call({"disease": "Rougeole", "years": "soon"})
    assert "level must be" in tools.get_disease_trend.call({"disease": "Rougeole", "level": "village"})
    assert "measure must be" in tools.rank_places.call({"disease": "Rougeole", "year": 2020, "measure": "vibes"})
    assert "Unknown table" in tools.get_model_result.call({"table": "t99"})


def test_place_names_ignore_accents_and_suggest():
    assert "Tillabéri" in set(tools.get_disease_trend.call({"disease": "Rougeole", "level": "region", "places": "tillaberi", "years": "2020"}).split(","))
    assert "Did you mean" in tools.get_disease_trend.call({"disease": "Rougeole", "level": "region", "places": "Zindre"})
    assert "is a district" in tools.get_disease_trend.call({"disease": "Rougeole", "level": "region", "places": "Zinder Nord"})


# ---- Trends -----------------------------------------------------------------------------------------------------

def test_trend_national_equals_the_project_table(rows):
    t, _ = rows(tools.get_disease_trend, disease="Rougeole")
    a = annual()
    a = a[(a.disease == "Rougeole") & (a.level == "national")]
    assert t.cases.tolist() == a.cases.tolist() and len(t) == 10


def test_regions_add_up_to_the_nation(rows):
    t, _ = rows(tools.get_disease_trend, disease="Méningite", level="region", years="2019")
    n, _ = rows(tools.get_disease_trend, disease="Méningite", years="2019")
    assert t.cases.sum() == n.cases.iloc[0] and len(t) == 8


def test_incidence_uses_the_one_denominator(rows):
    t, _ = rows(tools.get_disease_trend, disease="Malnutrition sévère", years="2019")
    measles, _ = rows(tools.get_disease_trend, disease="Rougeole", years="2019")
    assert t.population.iloc[0] == measles.population.iloc[0]
    assert t.incidence_per_100k.iloc[0] == pytest.approx(1e5 * t.cases.iloc[0] / t.population.iloc[0], abs=0.01)


def test_through_week_cuts_every_year(rows):
    t, out = rows(tools.get_disease_trend, disease="Rougeole", years="2023-2024", through_week=43)
    w = pd.read_csv(tools.DATA / "weekly.csv")
    w = w[(w.disease == "Rougeole") & (w.level == "national") & (w.year == 2023) & (w.week <= 43)]
    assert t.cases.iloc[0] == w.cases.sum() and not t.partial_year.any() and "Partial year" not in out


def test_a_partial_year_carries_its_caution(rows):
    _, out = rows(tools.get_disease_trend, disease="Rougeole")
    assert "2024 stops at week 43" in out


def test_districts_start_in_2017(rows):
    t, out = rows(tools.get_disease_trend, disease="Rougeole", level="district", places="Zinder Nord")
    assert t.year.min() == 2017 and "left out at district level" in out
    assert "comparable only from 2017" in tools.get_disease_trend.call({"disease": "Rougeole", "level": "district", "years": "2015"})


def test_definition_change_in_confirmed_malaria(rows):
    _, across = rows(tools.get_disease_trend, disease="Paludisme confirmé", years="2019-2022")
    assert "changes definition" in across and "deaths were recorded under suspected" in across
    _, after = rows(tools.get_disease_trend, disease="Paludisme confirmé", years="2021-2023")
    assert "changes definition" not in after


def test_missing_years_are_not_zero():
    out = tools.get_disease_trend.call({"disease": "Paludisme (femmes enceintes)", "years": "2020-2021"})
    assert "No rows" in out and "no data, not zero" in out


def test_compare_years_is_like_for_like(rows):
    t, _ = rows(tools.compare_years, disease="Rougeole", year_a=2023, year_b=2024)
    w = pd.read_csv(tools.DATA / "weekly.csv")
    w = w[(w.disease == "Rougeole") & (w.level == "national") & (w.week <= 43)]
    a, b = w[w.year == 2023].cases.sum(), w[w.year == 2024].cases.sum()
    assert t.cases_2023.iloc[0] == a and t.cases_2024.iloc[0] == b
    assert t.weeks_compared.iloc[0] == "1-43"
    assert t.cases_change_pct.iloc[0] == pytest.approx(100 * (b - a) / a, abs=0.05)


def test_compare_years_refuses_districts_before_2017_and_missing_years():
    assert "only from 2017" in tools.compare_years.call({"disease": "Rougeole", "year_a": 2016, "year_b": 2020, "level": "district"})
    assert "no data" in tools.compare_years.call({"disease": "COVID-19", "year_a": 2019, "year_b": 2022})


def test_rank_is_sorted_and_gives_the_nation(rows):
    t, out = rows(tools.rank_places, disease="Méningite", year=2022)
    assert t.incidence_per_100k.is_monotonic_decreasing and t["rank"].iloc[0] == 1 and "# national 2022" in out
    top, _ = rows(tools.rank_places, disease="Méningite", year=2022, level="district", measure="cases", top=5)
    assert len(top) == 5 and top.cases.is_monotonic_decreasing


def test_weekly_curve_and_a_report_not_received_is_unknown(rows):
    t, _ = rows(tools.get_weekly_curve, disease="Méningite", years="2020", weeks="1-10")
    assert t.week.max() == 10 and "reports_not_received" in t.columns
    grid = pd.read_csv(tools.DATA / "reporting_grid.csv")
    gone = grid[(grid.status == "N") & (grid.year == 2020)].iloc[0]
    d, _ = rows(tools.get_weekly_curve, disease="Méningite", years="2020", level="district", places=gone.district, weeks=str(gone.week))
    assert d.report.iloc[0] == "not received" and pd.isna(d.cases.iloc[0])


def test_too_many_rows_asks_to_narrow():
    assert "too many" in tools.get_weekly_curve.call({"disease": "Méningite", "level": "region"})


def test_seasonality_leaves_out_partial_years(rows):
    t, out = rows(tools.get_seasonality, disease="Méningite")
    assert t.years.max() == 9 and "# peak week:" in out


def test_year_overview(rows):
    t, _ = rows(tools.get_year_overview, year=2022)
    assert t.cases.is_monotonic_decreasing and "english" in t.columns


# ---- Surveillance ----------------------------------------------------------------------------------------------

def test_meningitis_alerts_list_only_the_weeks_over_a_threshold(rows):
    t, out = rows(tools.get_meningitis_alerts, years="2017-2018")
    assert set(t.status) <= {"alert", "epidemic"} and "not an official declaration" in out
    y, _ = rows(tools.get_meningitis_alerts, years="2017-2018", by="year")
    assert y.alert_weeks.sum() + y.epidemic_weeks.sum() == len(t)


def test_reporting_matches_the_grid_and_marks_2024(rows):
    grid = pd.read_csv(tools.DATA / "reporting_grid.csv")
    g = grid[grid.year == 2020]
    t, out = rows(tools.get_reporting, years="2020,2024")
    assert t.completeness_pct.iloc[0] == pytest.approx(100 * g.received.mean(), abs=0.05)
    assert t.timeliness_pct.iloc[0] == pytest.approx(100 * g.on_time.mean(), abs=0.05)
    assert t.year.tolist() == [2020, 2024] and "cumulative to week 43" in out


def test_weekly_reporting_2024_is_labelled_as_another_measure(rows):
    t, out = rows(tools.get_reporting, years="2024", level="region", places="Zinder", by="week")
    assert t.week.max() == 37 and t.source.iloc[0].startswith("DHIS2") and "different measure" in out


def test_maternal_deaths_never_give_a_ratio(rows):
    t, out = rows(tools.get_maternal_deaths, years="2015-2016")
    assert "live_births" not in t.columns and pd.isna(t.deaths_investigated.iloc[0]) and t.deaths_investigated.iloc[1] >= 0
    assert "Notified deaths" in out
    assert not (tools.DATA / "maternal_deaths.csv").read_text(encoding="utf-8").startswith("year,week,region,district,live_births")


def test_malaria_testing(rows):
    t, _ = rows(tools.get_malaria_testing)
    assert t.year.max() == 2020 and t.positivity_pct.iloc[0] == pytest.approx(100 * t.positive.iloc[0] / t.tested.iloc[0], abs=0.05)


def test_dhis2_comparison(rows):
    t, out = rows(tools.compare_dhis2_2024)
    assert {"workbook_cases", "dhis2_cases", "difference_pct"} <= set(t.columns) and "weeks 1-37" in out
    w, _ = rows(tools.compare_dhis2_2024, disease="Rougeole", by="week")
    assert w.week.max() == 37
    r, _ = rows(tools.compare_dhis2_2024, disease="Rougeole", by="region")
    assert len(r) == 8
    assert "needs a disease" in tools.compare_dhis2_2024.call({"by": "week"})


def test_validation_checks(rows):
    s, _ = rows(tools.get_validation_checks)
    assert {"check", "status", "items"} == set(s.columns)
    d, _ = rows(tools.get_validation_checks, status="differs")
    assert d.item.tolist() == ["Méningite"]


def test_data_notes_search_in_two_languages(rows):
    assert "denominators" in rows(tools.search_data_notes, term="denominators")[1]
    assert "malaria definition" in rows(tools.search_data_notes, term="paludisme")[1]
    assert "No note" in tools.search_data_notes.call({"term": "xyzzy"})


def test_model_results(rows):
    t, _ = rows(tools.list_model_results)
    assert t[t.table == "t03_year_irr_long"].available.iloc[0] and not t[t.table == "t01_overdispersion"].available.iloc[0]
    m, out = rows(tools.get_model_result, table="t03_year_irr_long", term="méningite")
    assert set(m.disease) == {"Meningitis"} and "not causal" in out
    assert "not built" in tools.get_model_result.call({"table": "t01_overdispersion"})


# ---- Rules that hold for every tool -----------------------------------------------------------------------------

def test_every_tool_is_read_only_and_described():
    for t in tools.TOOLS:
        assert t.description and t.input_schema["type"] == "object"
    assert len({t.name for t in tools.TOOLS}) == len(tools.TOOLS) == 19


def test_synthetic_data_says_so(rows):
    if not tools.build_info()["synthetic"]:
        pytest.skip("real tables")
    _, out = rows(tools.list_years)
    assert "SYNTHETIC" in out


def test_calls_are_logged():
    tools.list_years.call({})
    assert tools.TRACE[-1]["tool"] == "list_years"
