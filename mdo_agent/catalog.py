"""What the assistant knows without the data: disease names, the rules that go with them, and the model tables.

No figure from the surveillance data is written here, so this file can be public.
"""
from __future__ import annotations

import re
import unicodedata

# id (the French label used in the source workbooks) -> English label and other names people use.
DISEASES: dict[str, dict] = {
    "Paludisme suspect": {"en": "Malaria (suspected)", "aliases": ["suspected malaria", "palu suspect", "paludisme suspecte"]},
    "Paludisme confirmé": {"en": "Malaria (confirmed)", "aliases": ["confirmed malaria", "palu confirme", "paludisme confirme"]},
    "Paludisme (femmes enceintes)": {"en": "Malaria in pregnancy", "aliases": ["malaria in pregnant women", "palu femmes enceintes", "paludisme chez la femme enceinte", "paludisme grossesse"]},
    "Rougeole": {"en": "Measles", "aliases": []},
    "Méningite": {"en": "Meningitis", "aliases": []},
    "Choléra": {"en": "Cholera", "aliases": []},
    "Diphtérie": {"en": "Diphtheria", "aliases": []},
    "Coqueluche": {"en": "Pertussis", "aliases": ["whooping cough"]},
    "Malnutrition sévère": {"en": "Severe acute malnutrition", "aliases": ["sam", "mas", "severe malnutrition", "malnutrition aigue severe"]},
    "Malnutrition modérée": {"en": "Moderate acute malnutrition", "aliases": ["mam", "moderate malnutrition", "malnutrition aigue moderee"]},
    "PFA": {"en": "Acute flaccid paralysis", "aliases": ["afp", "paralysie flasque aigue", "polio"]},
    "Hépatite virale E": {"en": "Hepatitis E", "aliases": ["hepatite e", "hepatitis e virus", "hev"]},
    "COVID-19": {"en": "COVID-19", "aliases": ["covid", "coronavirus", "sars-cov-2"]},
    "Fièvre jaune (suspect)": {"en": "Yellow fever (suspected)", "aliases": ["yellow fever", "fievre jaune"]},
    "Fièvres hémorragiques virales": {"en": "Viral haemorrhagic fevers", "aliases": ["viral hemorrhagic fever", "vhf", "fhv", "fievre hemorragique"]},
    "Diarrhée sanglante": {"en": "Bloody diarrhoea", "aliases": ["bloody diarrhea", "dysentery", "dysenterie"]},
    "Autre tétanos": {"en": "Other tetanus", "aliases": ["tetanos autre"]},
    "Tétanos néonatal": {"en": "Neonatal tetanus", "aliases": ["tetanos neonatal", "tnn"]},
    "Dengue": {"en": "Dengue", "aliases": []},
    "Grippe": {"en": "Influenza", "aliases": ["flu"]},
    "Rage": {"en": "Rabies", "aliases": []},
    "Ebola": {"en": "Ebola", "aliases": ["evd", "mve"]},
    "MERS-CoV": {"en": "MERS", "aliases": ["mers"]},
    "SRAS": {"en": "SARS", "aliases": ["sars"]},
    "Ver de Guinée": {"en": "Guinea worm", "aliases": ["dracunculiasis", "dracunculose"]},
}

# A word that means several diseases: the tool asks which one rather than choose.
AMBIGUOUS = {
    "malaria": ["Paludisme confirmé", "Paludisme suspect", "Paludisme (femmes enceintes)"],
    "paludisme": ["Paludisme confirmé", "Paludisme suspect", "Paludisme (femmes enceintes)"],
    "palu": ["Paludisme confirmé", "Paludisme suspect", "Paludisme (femmes enceintes)"],
    "malnutrition": ["Malnutrition sévère", "Malnutrition modérée"],
    "tetanus": ["Tétanos néonatal", "Autre tétanos"],
    "tetanos": ["Tétanos néonatal", "Autre tétanos"],
}

FIRST_STABLE_DISTRICT_YEAR = 2017

# Model output tables copied by the build. The tables come from the analysis/ folder of the msf-mdo-niger project.
MODEL_TABLES: dict[str, dict] = {
    "t01_overdispersion": {"topic": "overdispersion", "about": "Overdispersion tests: variance / mean, Cameron-Trivedi, NB theta, NB vs Poisson. Why negative binomial models are needed."},
    "t02_nb_summary": {"topic": "trend", "about": "Negative binomial district panels, 2017-2024: seasonal peak week, peak / trough, incidence rate ratio of the last year vs 2017 with 95% CI."},
    "t03_year_irr_long": {"topic": "trend", "about": "Year effects vs 2017 by disease: incidence rate ratios with 95% CI, negative binomial (irr, lo, hi) and PPML (irr_ppml, lo_ppml, hi_ppml)."},
    "t04_nb_vs_ppml": {"topic": "robustness", "about": "Robustness: largest difference between NB and PPML year effects, and their correlation."},
    "t05_regional_seasonality": {"topic": "seasonality", "about": "Estimated seasonal peak week by region for confirmed malaria, meningitis and measles."},
    "t06_hurdle_comparison": {"topic": "rare diseases", "about": "Rare diseases: share of zero weeks; AIC of NB, zero-inflated NB and hurdle NB."},
    "t07_hurdle_effects": {"topic": "spread", "about": "Hurdle models: effect of last week's cases in the same district, the same region and the rest of Niger on any case (OR) and on the count (IRR)."},
    "t08_hhh4_parameters": {"topic": "spread", "about": "Endemic-epidemic (hhh4) parameters for meningitis and measles."},
    "t09_hhh4_shares": {"topic": "spread", "about": "Share of expected cases from the endemic background, within the district, and from other districts."},
    "t10_hhh4_scores": {"topic": "spread", "about": "Out-of-sample scores of the endemic-epidemic model variants."},
    "t11_forecasts_long": {"topic": "forecast", "about": "Rolling-origin national forecasts, week by week: observed, NB autoregression and harmonic NB with 90% intervals, seasonal naive. h = horizon in weeks. Past validation, not a forecast of the future."},
    "t12_forecast_accuracy": {"topic": "forecast", "about": "Forecast accuracy by disease and horizon: mean absolute error, skill vs seasonal naive, 90% interval coverage."},
    "t13_reporting_logit": {"topic": "reporting", "about": "Mixed logit of a report arriving on time: odds ratios with 95% CI."},
    "t14_cfr_models": {"topic": "case fatality", "about": "Quasi-binomial case fatality models: district-years, cases, deaths, crude CFR, dispersion, test of regional differences."},
    "t15_cfr_by_region": {"topic": "case fatality", "about": "Adjusted case fatality by region with 95% CI, for meningitis, measles, cholera and diphtheria."},
    "t16_outbreak_alarms": {"topic": "outbreak detection", "about": "Farrington flexible outbreak detection: weeks monitored and alarm weeks by disease and year."},
}


def norm(s: object) -> str:
    """Lower case, no accents, single spaces: what two spellings of a name must share."""
    text = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text).strip().lower()


class BadInput(ValueError):
    """A wrong argument: the message goes back to the model, which can correct the call."""


def resolve_disease(name: str) -> str:
    key = norm(name)
    if not key:
        raise BadInput("Name a disease. Call list_diseases to see them.")
    if key in AMBIGUOUS:
        raise BadInput(f"'{name}' can mean several series: {', '.join(AMBIGUOUS[key])}. Choose one, and say which you used in your answer.")
    for disease, info in DISEASES.items():
        if key in {norm(disease), norm(info["en"]), *map(norm, info["aliases"])}:
            return disease
    raise BadInput(f"Unknown disease '{name}'. Call list_diseases to see the {len(DISEASES)} series.")


def caveats_for(disease: str, years: list[int], level: str = "national", cut_to_week: bool = False, last_weeks: dict[int, int] | None = None) -> list[str]:
    """The cautions that must travel with a table of this disease and these years, whatever the model writes."""
    out: list[str] = []
    ys = set(years)
    if disease == "Paludisme confirmé" and min(ys, default=9999) <= 2020:
        if max(ys, default=0) >= 2021:
            out.append("Confirmed malaria changes definition: 2015-2020 counts positive tests, from 2021 confirmed cases. Compare within each period.")
        out.append("Confirmed malaria has no deaths recorded for 2015-2020: deaths were recorded under suspected malaria until then.")
    if disease == "Paludisme suspect":
        if ys & {2018}:
            out.append("Suspected malaria for 2018 is incomplete in the source workbook.")
        if min(ys, default=9999) <= 2020 and max(ys, default=0) >= 2021:
            out.append("From 2021 malaria deaths are recorded under confirmed malaria, not suspected.")
    if disease == "Paludisme (femmes enceintes)" and ys & {2020, 2021}:
        out.append("Malaria in pregnancy is missing for 2020 and 2021: this is no data, not zero.")
    if disease in ("Malnutrition sévère", "Malnutrition modérée"):
        if max(ys, default=0) >= 2022:
            out.append("Malnutrition is only reported to 2021.")
        out.append("Rates per total population, not per child under 5: the sheets' own target populations are inconsistent across years.")
    if disease == "COVID-19" and min(ys, default=9999) < 2021:
        out.append("COVID-19 is on the sheets from 2021 only.")
    if disease == "Dengue" and min(ys, default=9999) < 2023:
        out.append("Dengue is on the sheets from 2023 only.")
    if disease == "PFA":
        out.append("Acute flaccid paralysis is a syndromic surveillance indicator; rates here use total population, not children under 15.")
    if disease == "Tétanos néonatal":
        out.append("Rates use total population, not live births, which the data do not give reliably.")
    if disease in ("MERS-CoV", "SRAS", "Ver de Guinée"):
        out.append("No case was reported for this disease in the sheets.")
    if level == "district" and min(ys, default=9999) < FIRST_STABLE_DISTRICT_YEAR:
        out.append("Districts are comparable only from 2017: there were 46 to 48 before the split into 72.")
    if not cut_to_week and last_weeks:
        partial = sorted(y for y in ys if last_weeks.get(y, 53) < 52)
        if partial:
            weeks = ", ".join(f"{y} stops at week {last_weeks[y]}" for y in partial)
            out.append(f"Partial year: {weeks}. Its total and rate are not comparable with full years: compare the same weeks.")
    return out
