"""The README screenshots, on the invented system with scripted replies: real figures must never appear here.

    python demo/make_demo_data.py
    python docs/make_screenshots.py
"""
import os
import socket
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
os.environ["MDO_AGENT_DATA"] = str(REPO / "demo_data")
for p in (REPO, REPO / "web", REPO / "tests"):
    sys.path.insert(0, str(p))

import app as webapp
import uvicorn
from playwright.sync_api import sync_playwright
from scripted_model import ScriptedClient

from mdo_agent import tools
from mdo_agent.agent import MdoAgent

assert tools.build_info()["synthetic"], "Screenshots are taken on the invented data only."

CASES = {
    "How does confirmed malaria": ([[("get_weekly_curve", {"disease": "Paludisme confirmé", "years": "2021-2024"})],
                                    [("publish_result", {"result_id": "R1", "chart": "line", "x": "week", "y": "cases", "series": "year", "title": "Confirmed malaria by week, 2021 to 2024"})]],
                                   "**Synthetic data: every figure here is invented.** Cases peak around week 38 each year. To compare 2024 with a full year, cut both to week 43, where 2024 stops."),
    "Which regions": ([[("rank_places", {"disease": "Méningite", "year": 2022})],
                       [("publish_result", {"result_id": "R1", "chart": "map", "x": "place", "y": "incidence_per_100k", "title": "Meningitis incidence by region, 2022"})]],
                      "**Synthetic data: every figure here is invented, and the map shapes too.** The table gives each region with its cases, deaths and rate per 100,000."),
}


class Router(MdoAgent):
    def __init__(self):
        super().__init__(client=ScriptedClient([]))

    def ask(self, question, on_event=None):
        key = next(k for k in CASES if k in question)
        self.client.script, self.client.answer = CASES[key]
        return super().ask(question, on_event)


def main():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(webapp.create_app("", Router), host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    out = REPO / "docs" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = None
        for channel in ("chrome", "msedge"):
            try:
                browser = p.chromium.launch(channel=channel, headless=True)
                break
            except Exception:
                continue
        page = browser.new_context(viewport={"width": 1320, "height": 900}).new_page()
        page.goto(f"http://127.0.0.1:{port}")
        page.locator("#examples .example").first.wait_for()
        page.screenshot(path=out / "home.png")
        for name, question in [("weekly-curves", "How does confirmed malaria look week by week?"), ("region-map", "Which regions had the highest meningitis incidence in 2022?")]:
            page.click("#new-chat")
            page.fill("#question", question)
            page.press("#question", "Enter")
            page.locator(".turn .chart svg").last.wait_for(timeout=15000)
            page.wait_for_timeout(600)
            page.locator(".turn").last.evaluate("e => e.scrollIntoView()")
            page.screenshot(path=out / f"{name}.png")
        browser.close()
    server.should_exit = True


if __name__ == "__main__":
    main()
