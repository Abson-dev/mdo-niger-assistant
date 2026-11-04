"""The browser client in a real browser, under the production Content-Security-Policy, with scripted model replies.
Skipped when Playwright or a browser is not available."""
import socket
import threading
import time
from pathlib import Path

import app as webapp
import pytest
import uvicorn
from scripted_model import ScriptedClient

from mdo_agent.agent import MdoAgent

sync_api = pytest.importorskip("playwright.sync_api")

CASES = {
    "plain": ([[("get_year_overview", {"year": 2022})], [("publish_result", {"result_id": "R1", "title": "All diseases, 2022"})]],
              "**Meningitis rose.** See `get_year_overview`.\n\n- First point\n- Second point\n\n| Check | Result |\n| --- | --- |\n| Cases | 10 |"),
    "curve": ([[("get_weekly_curve", {"disease": "Méningite", "years": "2021-2022"})],
               [("publish_result", {"result_id": "R1", "chart": "line", "x": "week", "y": "cases", "series": "year"})]], "Weekly."),
    "trend": ([[("get_disease_trend", {"disease": "Paludisme confirmé", "years": "2019-2022"})],
               [("publish_result", {"result_id": "R1", "chart": "line", "x": "year", "y": "incidence_per_100k"})]], "Yearly."),
    "rank": ([[("rank_places", {"disease": "Méningite", "year": 2022})],
              [("publish_result", {"result_id": "R1", "chart": "bar", "x": "place", "y": "incidence_per_100k"})]], "Bars."),
    "scatter": ([[("rank_places", {"disease": "Méningite", "year": 2022, "level": "district"})],
                 [("publish_result", {"result_id": "R1", "chart": "scatter", "x": "population", "y": "cases"})]], "Scatter."),
    "grid": ([[("get_weekly_curve", {"disease": "Méningite", "years": "2019-2023"})],
              [("publish_result", {"result_id": "R1", "chart": "heatmap", "x": "week", "y": "year", "series": "cases"})]], "Heatmap."),
    "map": ([[("rank_places", {"disease": "Méningite", "year": 2022})],
             [("publish_result", {"result_id": "R1", "chart": "map", "x": "place", "y": "incidence_per_100k"})]], "Map."),
    "attack": ([], "<img src=x onerror=\"window.INJECTED=1\"> <script>window.INJECTED=1</script> **plain**"),
}


class Router(MdoAgent):
    def __init__(self):
        super().__init__(client=ScriptedClient([]))

    def ask(self, question, on_event=None):
        key = next(k for k in CASES if k in question)
        self.client.script, self.client.answer = CASES[key]
        return super().ask(question, on_event)


def serve(password=""):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(webapp.create_app(password, Router), host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            return server, f"http://127.0.0.1:{port}"
        time.sleep(0.05)
    raise RuntimeError("server did not start")


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        b = None
        for channel in ("chrome", "msedge"):
            try:
                b = p.chromium.launch(channel=channel, headless=True)
                break
            except Exception:  # not on this machine
                continue
        if b is None:
            pytest.skip("No Chrome or Edge available")
        yield b
        b.close()


@pytest.fixture
def page(browser):
    server, url = serve()
    context = browser.new_context(accept_downloads=True, viewport={"width": 1280, "height": 900})
    p = context.new_page()
    p.problems, p.outside = [], []
    p.on("pageerror", lambda e: p.problems.append(str(e)))
    # /logo is absent in the tests by design: the app hides the image.
    p.on("console", lambda m: p.problems.append(m.text) if m.type == "error" and "404" not in m.text else None)
    p.on("request", lambda r: p.outside.append(r.url) if not r.url.startswith((url, "data:", "blob:")) else None)
    p.goto(url)
    p.locator("#examples .example").first.wait_for()
    yield p
    context.close()
    server.should_exit = True


def ask(p, question):
    turns = p.locator(".turn .a").count()
    p.fill("#question", question)
    p.press("#question", "Enter")
    # Not wait_for_function: it polls with eval, which the app's Content-Security-Policy rightly blocks.
    p.locator(".turn .a").nth(turns).wait_for(timeout=15000)
    return p.locator(".turn").last


def test_home_page_shows_examples_and_the_synthetic_label(page):
    assert page.locator(".example").count() == 4
    assert page.locator("#welcome").is_visible()
    assert "diseases" in page.locator("#kicker").text_content()
    if "SYNTHETIC" in (page.locator("#banner").text_content() or ""):
        assert page.locator("#banner").is_visible()
    assert not page.locator("#logo").is_visible()


@pytest.mark.parametrize("question", ["curve", "trend", "rank", "scatter", "grid", "map"])
def test_every_chart_type_draws(page, question):
    turn = ask(page, question)
    turn.locator(".chart svg").first.wait_for(timeout=10000)
    assert turn.locator(".chart svg path, .chart svg rect").count() > 0
    assert not page.problems and not page.outside


def test_the_map_has_a_shape_per_region(page):
    turn = ask(page, "map")
    turn.locator(".chart svg").first.wait_for(timeout=10000)
    assert turn.locator(".chart svg path[aria-roledescription='geoshape']").count() == 8


def test_cautions_are_shown_under_the_result(page):
    turn = ask(page, "trend")
    assert "changes definition" in turn.locator(".caveats").text_content()


def test_answer_text_is_rendered_safely(page):
    turn = ask(page, "attack")
    assert turn.locator(".answer-text img, .answer-text script").count() == 0
    assert "<img" in turn.locator(".answer-text").text_content()
    assert turn.locator(".answer-text strong").text_content() == "plain"
    assert page.evaluate("window.INJECTED") is None


def test_years_are_not_formatted_as_thousands(page):
    turn = ask(page, "trend")
    assert "2,019" not in turn.locator("table.data").text_content() and "2019" in turn.locator("table.data").text_content()


def test_table_filter_sort_and_csv(page):
    turn = ask(page, "plain")
    assert turn.locator(".answer-text table.md").count() == 1 and turn.locator(".answer-text code").text_content() == "get_year_overview"
    total = turn.locator("table.data tbody tr").count()
    turn.locator(".table-bar input").fill("Méningite")
    assert turn.locator("table.data tbody tr").count() == 1 < total
    with page.expect_download() as d:
        turn.locator(".table-bar .small").click()
    assert d.value.suggested_filename.endswith(".csv")
    text = Path(d.value.path()).read_text(encoding="utf-8-sig")
    assert text.count("\n") == 1 and "Méningite" in text


def test_sources_list_the_tool_calls(page):
    turn = ask(page, "plain")
    turn.locator(".sources summary").click()
    assert "get_year_overview" in turn.locator(".sources").text_content()
    assert page.locator("#tool-count").text_content() == "2"


def test_history_survives_a_reload(page):
    ask(page, "plain")
    assert page.locator(".history li").count() == 1
    page.reload()
    page.wait_for_selector(".history li")
    page.locator(".history button").first.click()
    assert page.locator(".turn").count() == 1


def test_new_chat_starts_empty(page):
    ask(page, "plain")
    page.click("#new-chat")
    assert page.locator(".turn").count() == 0 and page.locator("#welcome").is_visible()


def test_no_horizontal_scroll_on_a_phone(page):
    page.set_viewport_size({"width": 390, "height": 800})
    ask(page, "curve")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_lock_screen(browser):
    server, url = serve(password="s3cret")
    context = browser.new_context()
    p = context.new_page()
    p.goto(url)
    p.wait_for_selector("#lock")
    assert not p.locator("#app").is_visible()
    p.fill("#password", "wrong")
    p.click("#lock button")
    p.locator("#lock-error:not(:empty)").wait_for()
    p.fill("#password", "s3cret")
    p.click("#lock button")
    p.wait_for_selector("#app:not([hidden])")
    context.close()
    server.should_exit = True
