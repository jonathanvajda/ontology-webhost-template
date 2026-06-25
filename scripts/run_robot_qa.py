from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

import yaml


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="ontology-site.yml")
    parser.add_argument("--robot-image", default="obolibrary/robot:latest")
    parser.add_argument("--no-fail", action="store_true", help="Write result files without failing on fail-query matches.")
    args = parser.parse_args()

    root = Path.cwd()
    config = yaml.safe_load((root / args.config).read_text(encoding="utf-8"))
    qa_dir = root / config["generation"].get("qa_results_dir", "build/qa")
    qa_dir.mkdir(parents=True, exist_ok=True)

    total_failures = 0
    for ontology in config.get("ontologies", []):
        profile_name = ontology.get("qa", {}).get("profile", "default")
        profile = config.get("qa", {}).get("profiles", {}).get(profile_name, {})
        for severity in ("fail", "warn"):
            for query in profile.get(severity, []):
                result_path = qa_dir / ontology["id"] / severity / f"{Path(query).stem}.csv"
                result_path.parent.mkdir(parents=True, exist_ok=True)
                run_robot_query(args.robot_image, ontology["path"], query, result_path)
                rows = count_rows(result_path)
                print(f"{ontology['id']} {severity} {query}: {rows} result rows")
                if severity == "fail":
                    total_failures += rows

    if total_failures and not args.no_fail:
        print(f"ROBOT QA failed with {total_failures} blocking result rows.", file=sys.stderr)
        raise SystemExit(1)


def run_robot_query(robot_image: str, ontology_path: str, query_path: str, result_path: Path) -> None:
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{Path.cwd()}:/work",
        "-w",
        "/work",
        robot_image,
        "query",
        "--input",
        ontology_path.replace("\\", "/"),
        "--query",
        query_path.replace("\\", "/"),
        str(result_path.relative_to(Path.cwd())).replace("\\", "/"),
        "--format",
        "CSV",
    ]
    subprocess.run(command, check=True)


def count_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    return max(0, len(rows) - 1)


if __name__ == "__main__":
    main()
