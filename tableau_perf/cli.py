"""Command line: tableau-perf run | tableau-perf report."""

from __future__ import annotations

import sys

from tableau_perf import __version__
from tableau_perf.report_cmd import main as report_main
from tableau_perf.run import main as run_main


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(f"tableau-perf {__version__}")
        print("usage: tableau-perf run  [run options] <scenario.yaml>")
        print("       tableau-perf report [report options] <result.json> [other.json]")
        print("\nSame entry points: python3 run.py …    python3 report.py …")
        return 0 if args and args[0] in ("-h", "--help") else 2
    command, rest = args[0], args[1:]
    if command == "run":
        return run_main(rest)
    if command == "report":
        return report_main(rest)
    if command in ("-V", "--version"):
        print(__version__)
        return 0
    print(f"unknown command '{command}'. Expected 'run' or 'report'.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
