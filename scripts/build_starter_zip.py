from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


BASE_FILES = {
    "ontology-site.yml": "ontology-site.yml",
    "mkdocs.yml": "mkdocs.yml",
    "requirements.txt": "requirements.txt",
    ".github/workflows/static.yml": ".github/workflows/static.yml",
    "scripts/generate_ontology_site.py": "scripts/generate_ontology_site.py",
    "scripts/run_robot_qa.py": "scripts/run_robot_qa.py",
    "docs/patterns/example-pattern.mmd": "docs/patterns/example-pattern.mmd",
    "README.md": "ONTOLOGY_WEBHOST_README.md",
}

OPTIONAL_EXAMPLE_FILES = [
    "ontologies/example.ttl",
]

GLOB_PATTERNS = [
    "qa/queries/fail/*.rq",
    "qa/queries/warn/*.rq",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a zip containing only the files needed to add the ontology webhost template to an existing repository."
    )
    parser.add_argument(
        "--output",
        default="dist/ontology-webhost-starter.zip",
        help="Path to the zip file to create.",
    )
    parser.add_argument(
        "--include-example-ontology",
        action="store_true",
        help="Include ontologies/example.ttl for a fully runnable demo.",
    )
    args = parser.parse_args()

    root = Path.cwd()
    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)

    files = collect_files(root, args.include_example_ontology)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path, archive_name in files:
            archive.write(path, archive_name)

    print(f"Wrote {output.relative_to(root)}")
    print("Included files:")
    for _path, archive_name in files:
        print(f"  - {archive_name}")


def collect_files(root: Path, include_example_ontology: bool) -> list[tuple[Path, str]]:
    candidates = [(root / source, archive_name) for source, archive_name in BASE_FILES.items()]
    if include_example_ontology:
        candidates.extend((root / name, name) for name in OPTIONAL_EXAMPLE_FILES)
    for pattern in GLOB_PATTERNS:
        candidates.extend((path, path.relative_to(root).as_posix()) for path in root.glob(pattern))

    files = []
    seen = set()
    for path, archive_name in candidates:
        if path.exists() and path.is_file() and archive_name not in seen:
            files.append((path, archive_name))
            seen.add(archive_name)
    return sorted(files, key=lambda item: item[1])


if __name__ == "__main__":
    main()
