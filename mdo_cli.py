"""The assistant's tools from a shell, for any assistant that loads skill/ (or a person). No API key needed.

  python mdo_cli.py list                                the tools and their arguments
  python mdo_cli.py get_disease_trend disease=measles level=region years=2017-2023
  python mdo_cli.py compare_years disease="Paludisme confirmé" year_a=2023 year_b=2024
  python mdo_cli.py get_meningitis_alerts years=2022 by=district
"""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mdo_agent import tools  # noqa: E402

# Publishing is for the web app: a shell host shows the table in its answer.
CLI_TOOLS = {t.name: t for t in tools.TOOLS if t.name != "publish_result"}


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not argv or argv[0] in ("list", "-h", "--help"):
        print(__doc__)
        for name, t in CLI_TOOLS.items():
            props = t.input_schema.get("properties", {})
            need = set(t.input_schema.get("required", []))
            args = " ".join(f"{p}=..." if p in need else f"[{p}=...]" for p in props)
            first = inspect.cleandoc(t.description or "").splitlines()[0]
            print(f"{name} {args}\n    {first}")
        return 0
    tool = CLI_TOOLS.get(argv[0])
    if tool is None:
        print(f"Unknown tool '{argv[0]}'. Run: python mdo_cli.py list", file=sys.stderr)
        return 2
    args = {}
    for a in argv[1:]:
        if "=" not in a:
            print(f"Arguments look like name=value, got '{a}'.", file=sys.stderr)
            return 2
        k, v = a.split("=", 1)
        args[k] = v
    print(tool.call(args))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
