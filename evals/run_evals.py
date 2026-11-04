"""Run the agent on evals/questions.csv and grade the answers.

A question passes when
  - the answer contains the expected value, if check_call is given. The value comes from running that tool on the
    current tables, so the eval stays valid after a rebuild. Tolerance: 0.15 for rates, exact for large counts; and
  - the answer contains at least one of the must_contain alternatives (|-separated), if given; and
  - the agent called at least one of the must_call tools (|-separated), if given.

    python evals/run_evals.py --dry-run     # show questions and expected values, no API calls
    python evals/run_evals.py               # calls the API once per question, plus its tool rounds (costs money)
    python evals/run_evals.py --only q01,q06
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from mdo_agent import tools  # noqa: E402

NUM = re.compile(r"\d{1,3}(?:[ ,.]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")


def numbers(text: str) -> list[float]:
    """Numbers as written in English or French: 3,129,109 / 3 129 109 / 41.4 / 41,4."""
    out = []
    for raw in NUM.findall(text.replace(" ", " ").replace(" ", " ")):
        grouped = re.fullmatch(r"\d{1,3}(?:[ ,.]\d{3})+", raw)
        if grouped:
            out.append(float(re.sub(r"[ ,.]", "", raw)))
        else:
            head = re.match(r"(\d{1,3}(?:[ ,.]\d{3})+)([.,]\d+)$", raw)
            out.append(float(re.sub(r"[ ,.]", "", head.group(1)) + "." + head.group(2)[1:]) if head else float(raw.replace(",", ".")))
    return out


def expected(row) -> float | None:
    """The value the answer must hold: tool;arg=value;arg=value, then where (column=value) and column."""
    if not row.check_call:
        return None
    name, *args = row.check_call.split(";")
    tool = {t.name: t for t in tools.TOOLS}[name]
    tools.begin_question()
    out = tool.call(dict(a.split("=", 1) for a in args))
    if not out.startswith("result_id:"):
        raise ValueError(f"{row.id}: {out[:200]}")
    t = tools.RESULTS[out.split()[1]]["rows"]
    for cond in filter(None, row.where.split(";")):
        col, value = cond.split("=", 1)
        t = t[t[col].astype(str) == value]
    if len(t) != 1 or pd.isna(t[row.column].iloc[0]):
        raise ValueError(f"{row.id}: no single value in {row.column}")
    return float(t[row.column].iloc[0])


def grade(text: str, value: float | None, must: str, must_call: str = "", called: tuple[str, ...] = ()) -> tuple[bool, str]:
    reasons = []
    if must_call and not set(must_call.split("|")) & set(called):
        reasons.append(f"called none of [{must_call}]")
    if value is not None:
        tolerance = 0.15 if abs(value) < 1000 else 0.5
        if not any(abs(n - abs(value)) <= tolerance for n in numbers(text)):
            reasons.append(f"expected {value:g} not found")
    if isinstance(must, str) and must and not any(alt.lower() in text.lower() for alt in must.split("|")):
        reasons.append(f"none of [{must}]")
    return not reasons, "; ".join(reasons)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--only", default="")
    a = p.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    qs = pd.read_csv(HERE / "questions.csv", dtype=str, keep_default_na=False)
    if a.only:
        qs = qs[qs.id.isin(a.only.split(","))]
    values = {r.id: expected(r) for r in qs.itertuples()}

    if a.dry_run:
        for r in qs.itertuples():
            exp = values[r.id]
            print(f"{r.id}  expected={'-' if exp is None else f'{exp:g}':>10}  must=[{r.must_contain}]  {r.question}")
        return 0

    from mdo_agent.agent import MdoAgent
    results = []
    for r in qs.itertuples():
        agent = MdoAgent()  # fresh conversation per question
        ans = agent.ask(r.question)
        ok, why = grade(ans.text, values[r.id], r.must_contain, r.must_call, tuple(c["tool"] for c in ans.tool_calls))
        results.append({"id": r.id, "pass": ok, "why": why, "tools": len(ans.tool_calls), "input_tokens": ans.input_tokens, "output_tokens": ans.output_tokens,
                        "question": r.question, "answer": ans.text})
        print(f"{'PASS' if ok else 'FAIL'}  {r.id}  {why}")
    res = pd.DataFrame(results)
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    f = out / f"results_{datetime.now():%Y%m%d_%H%M%S}.csv"
    res.to_csv(f, index=False, encoding="utf-8")
    print(f"\n{int(res['pass'].sum())}/{len(res)} passed · {int(res.input_tokens.sum()):,} input / {int(res.output_tokens.sum()):,} output tokens · {f}")
    return 0 if res["pass"].all() else 1


if __name__ == "__main__":
    sys.exit(main())
