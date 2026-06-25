from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DC, DCTERMS, OWL, RDF, RDFS, SKOS


TYPE_LABELS = {
    OWL.Class: "Class",
    OWL.ObjectProperty: "Object property",
    OWL.NamedIndividual: "Named individual",
    OWL.DatatypeProperty: "Datatype property",
    OWL.AnnotationProperty: "Annotation property",
}

TYPE_CURIES = {
    "owl:Class": OWL.Class,
    "owl:ObjectProperty": OWL.ObjectProperty,
    "owl:NamedIndividual": OWL.NamedIndividual,
    "owl:DatatypeProperty": OWL.DatatypeProperty,
    "owl:DataProperty": OWL.DatatypeProperty,
    "owl:AnnotationProperty": OWL.AnnotationProperty,
}


@dataclass
class OntologyDoc:
    id: str
    source_path: Path
    page_path: Path
    graph: Graph
    ontology_iri: URIRef | None
    title: str
    description: str
    contributors: list[str]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="ontology-site.yml")
    args = parser.parse_args()

    root = Path.cwd()
    config_path = root / args.config
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    output_dir = root / config["generation"].get("output_dir", "docs")
    generated_dir = root / config["generation"].get("generated_dir", "docs/ontologies")
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_dir.mkdir(parents=True, exist_ok=True)

    imports_graphs = load_import_graphs(root, config.get("imports", {}).get("paths", []))
    docs = [
        build_ontology_doc(root, generated_dir, ontology, imports_graphs, config)
        for ontology in config.get("ontologies", [])
    ]

    write_index(root, output_dir, config, docs)
    for doc, ontology_config in zip(docs, config.get("ontologies", []), strict=False):
        write_ontology_page(root, doc, ontology_config, imports_graphs, config)
    write_qa_page(root, output_dir, config, docs)
    write_mkdocs_nav(root, config, docs)


def parse_graph(path: Path) -> Graph:
    graph = Graph()
    graph.parse(path)
    return graph


def load_import_graphs(root: Path, path_patterns: Iterable[str]) -> dict[Path, Graph]:
    graphs = {}
    for pattern in path_patterns:
        for match in glob.glob(str(root / pattern), recursive=True):
            path = Path(match)
            if path.is_file():
                try:
                    graphs[path] = parse_graph(path)
                except Exception as exc:  # noqa: BLE001
                    print(f"Warning: could not parse import {path}: {exc}")
    return graphs


def build_ontology_doc(root: Path, generated_dir: Path, item: dict, imports_graphs: dict[Path, Graph], config: dict) -> OntologyDoc:
    source_path = root / item["path"]
    if not source_path.exists() and config["generation"].get("fail_on_missing_ontology", True):
        raise FileNotFoundError(source_path)

    graph = parse_graph(source_path)
    ontology_iri = first_subject(graph, RDF.type, OWL.Ontology)
    elicit = item.get("elicit", {})
    overrides = item.get("overrides", {})

    title = choose_text(
        elicit.get("title", True),
        overrides.get("title"),
        first_literal(graph, ontology_iri, DCTERMS.title) if ontology_iri else None,
        fallback=item.get("artifact_label") or item["id"],
    )
    description = choose_text(
        elicit.get("description", True),
        overrides.get("description"),
        first_literal(graph, ontology_iri, DCTERMS.description) if ontology_iri else None,
        fallback="No ontology description was configured or found in ontology metadata.",
    )
    contributors = choose_list(
        elicit.get("contributors", True),
        overrides.get("contributors", []),
        ontology_contributors(graph, ontology_iri),
    )

    page_name = item.get("page", f"{item['id']}.md")
    return OntologyDoc(
        id=item["id"],
        source_path=source_path,
        page_path=generated_dir / page_name,
        graph=graph,
        ontology_iri=ontology_iri,
        title=title,
        description=description,
        contributors=contributors,
    )


def write_index(root: Path, output_dir: Path, config: dict, docs: list[OntologyDoc]) -> None:
    lines = [
        f"# {config['site'].get('name', 'Ontology Repository')}",
        "",
        config.get("metadata", {}).get("introduction") or config["site"].get("description", ""),
        "",
        "## Ontologies",
        "",
    ]
    for doc in docs:
        rel_page = relative_markdown_link(output_dir / "index.md", doc.page_path)
        lines.append(f"- [{doc.title}]({rel_page}) - {doc.description}")

    contacts = config.get("metadata", {}).get("contacts", [])
    if contacts:
        lines.extend(["", "## Contacts", ""])
        for contact in contacts:
            label = contact["name"]
            email = contact.get("email")
            lines.append(f"- [{label}](mailto:{email})" if email else f"- {label}")

    users = config.get("metadata", {}).get("users", [])
    if users:
        lines.extend(["", "## Ontology Users", "", '<div class="grid cards" markdown>', ""])
        for user in users:
            website = user.get("website", "#")
            image = user.get("image")
            if image:
                lines.append(f"-   [{user['name']}]({website})")
                lines.append("")
                lines.append(f"    ![{user['name']}]({image})")
            else:
                lines.append(f"-   [{user['name']}]({website})")
        lines.extend(["", "</div>"])

    patterns = config.get("design_patterns", [])
    if patterns:
        lines.extend(["", "## Design Patterns", ""])
        for pattern in patterns:
            lines.extend(render_mermaid_file(root / pattern["path"], pattern.get("title")))

    qa_page = config.get("qa", {}).get("summary_page", "qa.md")
    lines.extend(["", "## Quality Assurance", "", f"- [Quality assurance report]({qa_page})"])
    write_text(output_dir / "index.md", lines)


def write_ontology_page(root: Path, doc: OntologyDoc, item: dict, imports_graphs: dict[Path, Graph], config: dict) -> None:
    published_source = publish_artifact(root, doc.source_path, doc.id, config)
    rel_source = relative_markdown_link(doc.page_path, published_source)
    lines = [
        f"# {doc.title}",
        "",
        doc.description,
        "",
        "## Artifact",
        "",
        f"- Source ontology: [{doc.source_path.relative_to(root).as_posix()}]({rel_source})",
    ]

    downloads = item.get("downloads", [])
    if downloads:
        lines.extend(["", "### Downloads", ""])
        for download in downloads:
            path = root / download["path"]
            if path.exists():
                published = publish_artifact(root, path, doc.id, config)
                rel = relative_markdown_link(doc.page_path, published)
                lines.append(f"- [{download['label']}]({rel})")
            else:
                lines.append(f"- {download['label']} (missing: `{download['path']}`)")

    if doc.contributors:
        lines.extend(["", "## Contributors", ""])
        for contributor in doc.contributors:
            lines.append(f"- {contributor}")

    if item.get("elicit", {}).get("import_diagram", True):
        lines.extend(["", "## Import Diagram", "", "```mermaid"])
        lines.extend(import_mermaid(doc, imports_graphs).splitlines())
        lines.append("```")
    elif item.get("overrides", {}).get("import_diagram"):
        lines.extend(["", "## Import Diagram", ""])
        lines.extend(render_mermaid_file(root / item["overrides"]["import_diagram"]))

    patterns = [
        p for p in config.get("design_patterns", [])
        if doc.id in p.get("ontologies", []) or not p.get("ontologies")
    ]
    if patterns:
        lines.extend(["", "## Design Patterns", ""])
        for pattern in patterns:
            lines.extend(render_mermaid_file(root / pattern["path"], pattern.get("title")))

    if config.get("generation", {}).get("term_table", {}).get("enabled", True):
        lines.extend(["", "## Terms", ""])
        lines.extend(term_table(doc, imports_graphs, config))

    write_text(doc.page_path, lines)


def write_qa_page(root: Path, output_dir: Path, config: dict, docs: list[OntologyDoc]) -> None:
    qa_dir = root / config["generation"].get("qa_results_dir", "build/qa")
    lines = [
        "# Quality Assurance",
        "",
        "The CI workflow runs ROBOT verify with the configured SPARQL checks. Fail-level violations and warnings are both published here so reviewers can see the complete QA state of the ontology.",
        "",
        "| Ontology | Profile | Failures | Warnings |",
        "|:---|:---:|---:|---:|",
    ]
    for doc in docs:
        profile = find_ontology_config(config, doc.id).get("qa", {}).get("profile", "default")
        failures = count_query_rows(qa_dir / doc.id / "fail")
        warnings = count_query_rows(qa_dir / doc.id / "warn")
        rel_page = relative_markdown_link(output_dir / config.get("qa", {}).get("summary_page", "qa.md"), doc.page_path)
        lines.append(f"| [{doc.title}]({rel_page}) | {profile} | {failures} | {warnings} |")

    lines.extend(["", "## Query Inventory", ""])
    for profile_name, profile in config.get("qa", {}).get("profiles", {}).items():
        lines.append(f"### {profile_name}")
        for severity in ("fail", "warn"):
            lines.append(f"- {severity.title()}: {len(profile.get(severity, []))} queries")
    write_text(output_dir / config.get("qa", {}).get("summary_page", "qa.md"), lines)


def write_mkdocs_nav(root: Path, config: dict, docs: list[OntologyDoc]) -> None:
    mkdocs_path = root / "mkdocs.yml"
    output_dir = root / config["generation"].get("output_dir", "docs")
    lines = [
        f"site_name: {yaml_scalar(config['site'].get('name', 'Ontology Repository'))}",
        f"site_description: {yaml_scalar(config['site'].get('description', 'Generated ontology documentation.'))}",
    ]
    if config["site"].get("repo_url"):
        lines.append(f"repo_url: {yaml_scalar(config['site']['repo_url'])}")
    lines.extend(
        [
            "",
            "theme:",
            "  name: material",
            "  features:",
            "    - navigation.sections",
            "    - navigation.indexes",
            "    - content.code.copy",
            "",
            "markdown_extensions:",
            "  - admonition",
            "  - attr_list",
            "  - md_in_html",
            "  - pymdownx.details",
            "  - pymdownx.superfences:",
            "      custom_fences:",
            "        - name: mermaid",
            "          class: mermaid",
            "          format: !!python/name:pymdownx.superfences.fence_code_format",
            "  - tables",
            "  - toc:",
            "      permalink: true",
            "",
            "plugins:",
            "  - search",
            "",
            "nav:",
            "  - Home: index.md",
            "  - Ontologies:",
        ]
    )
    for doc in docs:
        page = doc.page_path.relative_to(output_dir).as_posix()
        lines.append(f"      - {yaml_scalar(doc.title)}: {page}")
    lines.append(f"  - Quality Assurance: {config.get('qa', {}).get('summary_page', 'qa.md')}")
    mkdocs_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def term_table(doc: OntologyDoc, imports_graphs: dict[Path, Graph], config: dict) -> list[str]:
    settings = config.get("generation", {}).get("term_table", {})
    allowed = [TYPE_CURIES[t] for t in settings.get("types", TYPE_CURIES) if t in TYPE_CURIES]
    include_deprecated = settings.get("include_deprecated", False)
    graph = doc.graph
    label_graph = combined_graph([graph, *imports_graphs.values()])
    rows = [
        "| IRI | Type | Label | Alternative term | Definition | Parent |",
        "|:---:|:---:|:---:|:---:|:---|:---:|",
    ]

    terms: list[tuple[str, URIRef, URIRef]] = []
    for rdf_type in allowed:
        for term in graph.subjects(RDF.type, rdf_type):
            if isinstance(term, URIRef) and (include_deprecated or not is_deprecated(graph, term)):
                terms.append((label_for_type(rdf_type), rdf_type, term))

    for type_label, rdf_type, term in sorted(terms, key=lambda row: str(row[2])):
        rows.append(
            "| "
            + " | ".join(
                escape_table_cell(value)
                for value in [
                    curie(graph, term),
                    type_label,
                    first_literal(graph, term, RDFS.label) or "",
                    "; ".join(literals(graph, term, SKOS.altLabel)),
                    first_literal(graph, term, SKOS.definition) or "",
                    parent_text(graph, label_graph, term, rdf_type),
                ]
            )
            + " |"
        )
    return rows


def import_mermaid(doc: OntologyDoc, imports_graphs: dict[Path, Graph]) -> str:
    graph_by_iri = {}
    for graph in [doc.graph, *imports_graphs.values()]:
        ontology = first_subject(graph, RDF.type, OWL.Ontology)
        if ontology:
            graph_by_iri[ontology] = graph

    lines = ["flowchart BT"]
    seen_edges = set()
    queue = [doc.ontology_iri] if doc.ontology_iri else []
    visited = set()
    while queue:
        iri = queue.pop(0)
        if iri in visited or iri is None:
            continue
        visited.add(iri)
        graph = graph_by_iri.get(iri, doc.graph if iri == doc.ontology_iri else None)
        if not graph:
            continue
        node = node_id(str(iri))
        title = first_literal(graph, iri, DCTERMS.title) or str(iri)
        lines.append(f'  {node}("{escape_mermaid(title)}")')
        for imported in graph.objects(iri, OWL.imports):
            if isinstance(imported, URIRef):
                imported_graph = graph_by_iri.get(imported)
                imported_title = first_literal(imported_graph, imported, DCTERMS.title) if imported_graph else str(imported)
                imported_node = node_id(str(imported))
                lines.append(f'  {imported_node}("{escape_mermaid(imported_title)}")')
                edge = (node, imported_node)
                if edge not in seen_edges:
                    lines.append(f'  {node} -- "owl:imports" --> {imported_node}')
                    seen_edges.add(edge)
                queue.append(imported)
    if len(lines) == 1:
        lines.append(f'  {node_id(doc.id)}("{escape_mermaid(doc.title)}")')
    return "\n".join(lines)


def parent_text(graph: Graph, label_graph: Graph, term: URIRef, rdf_type: URIRef) -> str:
    predicates = []
    if rdf_type == OWL.Class:
        predicates.append(RDFS.subClassOf)
    elif rdf_type in {OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty}:
        predicates.append(RDFS.subPropertyOf)
    elif rdf_type == OWL.NamedIndividual:
        predicates.append(RDF.type)
    values = []
    for predicate in predicates:
        for obj in graph.objects(term, predicate):
            if isinstance(obj, URIRef) and not str(obj).startswith(str(OWL)):
                values.append(label_or_curie(label_graph, graph, obj))
    return "; ".join(values)


def ontology_contributors(graph: Graph, ontology_iri: URIRef | None) -> list[str]:
    if not ontology_iri:
        return []
    values = []
    for predicate in (DCTERMS.creator, DC.creator, DCTERMS.contributor, DC.contributor):
        values.extend(literals(graph, ontology_iri, predicate))
    return unique(values)


def render_mermaid_file(path: Path, title: str | None = None) -> list[str]:
    if not path.exists():
        return [f"!!! warning \"Missing diagram\"", f"    `{path}` was not found."]
    lines = []
    if title:
        lines.extend([f"### {title}", ""])
    lines.extend(["```mermaid", path.read_text(encoding="utf-8").strip(), "```", ""])
    return lines


def count_query_rows(path: Path) -> int:
    total = 0
    for result in path.glob("*.csv"):
        with result.open(newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            rows = list(reader)
            total += max(0, len(rows) - 1)
    return total


def first_subject(graph: Graph, predicate: URIRef, obj: URIRef) -> URIRef | None:
    for subject in graph.subjects(predicate, obj):
        if isinstance(subject, URIRef):
            return subject
    return None


def first_literal(graph: Graph | None, subject: URIRef | None, predicate: URIRef) -> str | None:
    if graph is None or subject is None:
        return None
    for value in graph.objects(subject, predicate):
        if isinstance(value, Literal):
            return str(value)
        if isinstance(value, URIRef):
            return str(value)
    return None


def literals(graph: Graph, subject: URIRef, predicate: URIRef) -> list[str]:
    return [str(value) for value in graph.objects(subject, predicate) if isinstance(value, Literal)]


def choose_text(elicit: bool, override: str | None, extracted: str | None, fallback: str) -> str:
    if elicit:
        return extracted or override or fallback
    return override or fallback


def choose_list(elicit: bool, override: list[str], extracted: list[str]) -> list[str]:
    return unique(extracted if elicit else override)


def unique(values: Iterable[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def is_deprecated(graph: Graph, term: URIRef) -> bool:
    return any(str(value).lower() == "true" for value in graph.objects(term, OWL.deprecated))


def label_for_type(rdf_type: URIRef) -> str:
    return TYPE_LABELS.get(rdf_type, str(rdf_type))


def label_or_curie(label_graph: Graph, curie_graph: Graph, iri: URIRef) -> str:
    return first_literal(label_graph, iri, RDFS.label) or curie(curie_graph, iri)


def curie(graph: Graph, iri: URIRef) -> str:
    normalized = graph.namespace_manager.normalizeUri(iri)
    return normalized if not normalized.startswith("<") else str(iri)


def combined_graph(graphs: Iterable[Graph]) -> Graph:
    combined = Graph()
    for graph in graphs:
        for prefix, namespace in graph.namespaces():
            combined.bind(prefix, namespace)
        for triple in graph:
            combined.add(triple)
    return combined


def escape_table_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def escape_mermaid(value: str) -> str:
    return value.replace('"', "'")


def node_id(value: str) -> str:
    return "n_" + re.sub(r"[^A-Za-z0-9_]", "_", value).strip("_")


def relative_markdown_link(from_path: Path, to_path: Path) -> str:
    return os.path.relpath(to_path.resolve(), from_path.parent.resolve()).replace("\\", "/")


def yaml_scalar(value: str) -> str:
    return json.dumps(value)


def find_ontology_config(config: dict, ontology_id: str) -> dict:
    return next(item for item in config.get("ontologies", []) if item["id"] == ontology_id)


def write_text(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def publish_artifact(root: Path, source_path: Path, ontology_id: str, config: dict) -> Path:
    artifact_dir = root / config["generation"].get("artifact_dir", "docs/artifacts") / ontology_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    destination = artifact_dir / source_path.name
    if source_path.resolve() != destination.resolve():
        shutil.copy2(source_path, destination)
    return destination


if __name__ == "__main__":
    main()
