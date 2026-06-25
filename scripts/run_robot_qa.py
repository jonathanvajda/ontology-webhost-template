from __future__ import annotations

import argparse
import csv
import shlex
import sys
from pathlib import Path

import yaml


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="ontology-site.yml")
    parser.add_argument("--write-script", help="Write a POSIX shell script that runs the configured ROBOT queries.")
    parser.add_argument("--summarize-only", action="store_true", help="Only count existing result files and enforce fail-query status.")
    parser.add_argument("--robot-command", default="robot")
    parser.add_argument("--no-fail", action="store_true", help="Write result files without failing on fail-query matches.")
    args = parser.parse_args()

    if not args.write_script and not args.summarize_only:
        parser.error("choose --write-script to generate ROBOT commands or --summarize-only to summarize existing ROBOT CSV outputs")

    root = Path.cwd()
    config = yaml.safe_load((root / args.config).read_text(encoding="utf-8"))
    qa_dir = root / config["generation"].get("qa_results_dir", "build/qa")
    qa_dir.mkdir(parents=True, exist_ok=True)
    planned_queries = list(iter_planned_queries(config, qa_dir))

    if args.write_script:
        write_robot_script(root, args.write_script, planned_queries, args.robot_command)
        if not args.summarize_only:
            return

    total_failures = 0
    for planned in planned_queries:
        rows = count_rows(planned["result_path"])
        print(f"{planned['ontology_id']} {planned['severity']} {planned['query_path']}: {rows} result rows")
        if planned["severity"] == "fail":
            total_failures += rows

    if total_failures and not args.no_fail:
        print(f"ROBOT QA failed with {total_failures} blocking result rows.", file=sys.stderr)
        raise SystemExit(1)


def iter_planned_queries(config: dict, qa_dir: Path) -> list[dict]:
    planned = []
    for ontology in config.get("ontologies", []):
        profile_name = ontology.get("qa", {}).get("profile", "default")
        profile = config.get("qa", {}).get("profiles", {}).get(profile_name, {})
        for severity in ("fail", "warn"):
            for query_path in profile.get(severity, []):
                planned.append(
                    {
                        "ontology_id": ontology["id"],
                        "severity": severity,
                        "ontology_path": ontology["path"],
                        "query_path": query_path,
                        "result_path": qa_dir / ontology["id"] / severity / f"{Path(query_path).stem}.csv",
                    }
                )
    return planned


def write_robot_script(root: Path, script_path: str, planned_queries: list[dict], robot_command: str) -> None:
    path = root / script_path
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["#!/bin/sh", "set -eu", ""]
    for planned in planned_queries:
        result_path = relative_posix(planned["result_path"])
        result_dir = str(Path(result_path).parent).replace("\\", "/")
        lines.append(f"mkdir -p {shlex.quote(result_dir)}")
        lines.append(
            " ".join(
                shlex.quote(part)
                for part in [
                    robot_command,
                    "query",
                    "--input",
                    planned["ontology_path"].replace("\\", "/"),
                    "--query",
                    planned["query_path"].replace("\\", "/"),
                    result_path,
                    "--format",
                    "CSV",
                ]
            )
        )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def relative_posix(path: Path) -> str:
    return str(path.relative_to(Path.cwd())).replace("\\", "/")


def count_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    return max(0, len(rows) - 1)


if __name__ == "__main__":
    main()
