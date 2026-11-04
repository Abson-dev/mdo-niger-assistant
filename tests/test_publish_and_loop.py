"""What the reader sees (checked by the server), the agent loop with a scripted model, the real SDK against a fake API, and the grading of the evals."""
import json
from pathlib import Path

import anthropic
import httpx2
import pandas as pd
import pytest
from run_evals import grade
from scripted_model import NS, ScriptedClient, usage

from mdo_agent import results, tools
from mdo_agent.agent import SYSTEM, MdoAgent


def rid(rows, tool, **kw):
    return rows(tool, **kw)[1].split()[1]


# ---- Publishing ---------------------------------------------------------------------------------------------

def test_publish_a_weekly_curve_by_year(rows):
    r = rid(rows, tools.get_weekly_curve, disease="Méningite", years="2021-2022")
    assert tools.publish_result.call({"result_id": r, "chart": "line", "x": "week", "y": "cases", "series": "year"}).startswith("Published")
    p = tools.PUBLISHED[0]
    assert p["chart"]["x_time"] and p["source"]["tool"] == "get_weekly_curve" and "NaN" not in json.dumps(p)


def test_publish_refuses_a_line_ending_on_a_partial_year(rows):
    r = rid(rows, tools.get_disease_trend, disease="Rougeole")
    assert "partial year" in tools.publish_result.call({"result_id": r, "chart": "line", "x": "year", "y": "cases"})
    assert not tools.PUBLISHED
    cut = rid(rows, tools.get_disease_trend, disease="Rougeole", through_week=43)
    assert tools.publish_result.call({"result_id": cut, "chart": "line", "x": "year", "y": "cases"}).startswith("Published")


def test_publish_refuses_weeks_of_several_years_on_one_line(rows):
    r = rid(rows, tools.get_weekly_curve, disease="Méningite", years="2021-2022")
    assert "More than one row" in tools.publish_result.call({"result_id": r, "chart": "line", "x": "week", "y": "cases"})


def test_cautions_reach_the_reader_whatever_the_model_writes(rows):
    r = rid(rows, tools.get_disease_trend, disease="Paludisme confirmé", years="2019-2022")
    tools.publish_result.call({"result_id": r, "chart": "line", "x": "year", "y": "cases", "note": "All fine."})
    assert any("changes definition" in c for c in tools.PUBLISHED[0]["caveats"])


def test_a_map_needs_one_row_per_region(rows):
    good = rid(rows, tools.rank_places, disease="Méningite", year=2022)
    assert tools.publish_result.call({"result_id": good, "chart": "map", "x": "place", "y": "incidence_per_100k"}).startswith("Published")
    several = rid(rows, tools.get_disease_trend, disease="Méningite", level="region", years="2021-2022")
    assert "one row per region" in tools.publish_result.call({"result_id": several, "chart": "map", "x": "place", "y": "cases"})
    districts = rid(rows, tools.rank_places, disease="Méningite", year=2022, level="district")
    assert "the 8 regions only" in tools.publish_result.call({"result_id": districts, "chart": "map", "x": "place", "y": "cases"})


@pytest.mark.parametrize(("kw", "why"), [
    ({"chart": "pie"}, "Chart must be"),
    ({"chart": "bar", "x": "nope", "y": "cases"}, "No column"),
    ({"chart": "bar", "x": "", "y": "cases"}, "column is required"),
    ({"chart": "scatter", "x": "place", "y": "cases"}, "two numeric"),
    ({"chart": "heatmap", "x": "year", "y": "place", "series": "place"}, "numeric series"),
])
def test_publish_refuses_a_chart_the_data_cannot_support(rows, kw, why):
    r = rid(rows, tools.get_disease_trend, disease="Rougeole", years="2019-2021")
    assert why in tools.publish_result.call({"result_id": r, **kw})


def test_publish_too_many_series(rows):
    r = rid(rows, tools.get_disease_trend, disease="Rougeole", level="district", years="2019-2020")
    assert "Too many series" in tools.publish_result.call({"result_id": r, "chart": "line", "x": "year", "y": "cases", "series": "place"})


def test_publish_unknown_result():
    assert "Unknown result_id" in tools.publish_result.call({"result_id": "R99"})


def test_publish_too_many_rows():
    stored = {"id": "R1", "rows": pd.DataFrame({"a": range(tools.LIMITS["max_rows_shown"] + 1)}), "title": "t", "tool": "x", "args": {}}
    with pytest.raises(results.PublishError):
        results.build_publication(stored, "table", "", "", "", "", "", tools.LIMITS, set())


# ---- The loop ----------------------------------------------------------------------------------------------

def scripted(script, answer="Done."):
    return MdoAgent(client=ScriptedClient(script, answer))


def test_loop_publishes_and_traces():
    a = scripted([[("rank_places", {"disease": "Méningite", "year": 2022})],
                  [("publish_result", {"result_id": "R1", "chart": "map", "x": "place", "y": "incidence_per_100k"})]]).ask("map?")
    assert a.text == "Done." and a.published["chart"]["type"] == "map"
    assert [c["tool"] for c in a.tool_calls] == ["rank_places", "publish_result"]


def test_loop_shows_the_only_table_when_nothing_is_published():
    a = scripted([[("list_years", {})]]).ask("how?")
    assert a.published and a.published["chart"] is None and a.published["row_count"] == 10


def test_loop_shows_nothing_when_several_tables_are_unpublished():
    assert scripted([[("list_years", {})], [("list_diseases", {})]]).ask("?").published is None


def test_a_new_question_forgets_earlier_results():
    agent = scripted([[("list_years", {})]])
    agent.ask("one")
    agent.client.script = []
    assert agent.ask("two").published is None


def test_follow_up_keeps_only_question_and_answer():
    agent = scripted([], "First answer.")
    agent.ask("first")
    agent.ask("second")
    assert [m["content"] for m in agent.client.calls[-1]["messages"]] == ["first", "First answer.", "second"]


def test_the_request_uses_the_limits_and_the_cached_prompt():
    agent = scripted([])
    agent.ask("q")
    kw = agent.client.calls[0]
    assert kw["max_iterations"] == tools.LIMITS["max_tool_rounds"] and kw["model"] == "claude-opus-5-5"
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert {t.name for t in kw["tools"]} == {t.name for t in tools.TOOLS}


def fixed_reply(stop_reason):
    client = ScriptedClient([])
    client.beta.messages.tool_runner = lambda **kw: iter([NS(content=[], stop_reason=stop_reason, usage=usage())])
    return MdoAgent(client=client)


def test_a_refusal_is_reported():
    a = fixed_reply("refusal").ask("q")
    assert a.refused and "declined" in a.text


def test_running_out_of_rounds_says_so():
    assert "limit for one question" in fixed_reply("tool_use").ask("q").text


def test_tool_events_reach_the_listener():
    seen = []
    scripted([[("list_years", {})]]).ask("years", on_event=seen.append)
    assert seen and seen[0]["type"] == "tool" and seen[0]["tool"] == "list_years"


def test_the_instructions_cover_the_tools_and_the_cautions():
    for name in ("compare_years", "get_model_result", "publish_result", "search_data_notes", "get_reporting"):
        assert name in SYSTEM
    for caution in ("Never estimate", "significant", "week 43", "not zero", "from 2017", "positive tests"):
        assert caution in SYSTEM


# ---- The real SDK against a fake API: the request is accepted by the SDK and the tools run through its loop -----

def fake_api(replies, seen):
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json=replies.pop(0), headers={"content-type": "application/json"})
    return handler


def reply(content, stop):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": content, "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 50, "cache_creation_input_tokens": 0}}


def test_the_real_sdk_runs_the_loop():
    replies = [reply([{"type": "tool_use", "id": "t1", "name": "get_disease_trend", "input": {"disease": "malaria"}}], "tool_use"),
               reply([{"type": "tool_use", "id": "t2", "name": "list_years", "input": {}}], "tool_use"),
               reply([{"type": "tool_use", "id": "t3", "name": "publish_result", "input": {"result_id": "R1", "chart": "bar", "x": "year", "y": "population"}}], "tool_use"),
               reply([{"type": "text", "text": "Final answer."}], "end_turn")]
    seen: list[dict] = []
    client = anthropic.Anthropic(api_key="test", http_client=httpx2.Client(transport=httpx2.MockTransport(fake_api(replies, seen))))
    a = MdoAgent(client=client).ask("How many?")

    assert a.text == "Final answer." and a.published["chart"]["type"] == "bar" and a.input_tokens == 600 and a.output_tokens == 80
    first = seen[0]
    assert first["model"] == "claude-opus-5-5" and first["output_config"] == {"effort": "high"} and first["fallbacks"] == "default"
    assert "thinking" not in first and "temperature" not in first
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    # A wrong argument goes back to the model as text it can act on.
    result = seen[1]["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and "several series" in str(result["content"])


# ---- Evals: the grading itself -------------------------------------------------------------------------------

def test_grade_finds_the_value_within_tolerance():
    assert grade("It was 41.4 per 100,000.", 41.5, "")[0]
    assert grade("Il était de 41,4 pour 100 000.", 41.5, "")[0]
    assert grade("There were 2,718,281 cases.", 2718281, "")[0]
    assert grade("Il y a eu 2 718 281 cas.", 2718281, "")[0]
    assert not grade("It was 45.", 41.5, "")[0]


def test_grade_checks_required_words_and_tools():
    assert grade("No data for that year", None, "no data|pas de données")[0]
    assert not grade("It is 5", None, "no data")[0]
    assert grade("x", None, "", "get_reporting|list_years", ("list_years",))[0]
    assert not grade("x", None, "", "get_reporting", ("list_years",))[0]


def test_every_eval_question_is_well_formed():
    q = pd.read_csv(Path(tools.AGENT_DIR) / "evals" / "questions.csv", dtype=str, keep_default_na=False)
    assert q["id"].is_unique and len(q) >= 18 and (q["question"].str.len() > 5).all()
    names = {t.name for t in tools.TOOLS}
    for calls in q["must_call"]:
        assert not calls or set(calls.split("|")) <= names
