# Ontology Webhost Template

This repository is boilerplate for publishing ontology artifacts with GitHub Pages.
Edit `ontology-site.yml`, keep ontology files in the configured paths, and the
generator will create MkDocs pages for:

- a repository landing page;
- one page per ontology artifact;
- download links;
- extracted ontology title, description, and contributors;
- Mermaid import diagrams from `owl:imports`;
- optional Mermaid design pattern diagrams;
- generated term tables;
- CI-generated quality assurance summaries.

## Quick Start

For a new demo clone of this template:

```powershell
pip install -r requirements.txt
python scripts/generate_ontology_site.py --config ontology-site.yml
mkdocs serve
```

The GitHub Actions workflow in `.github/workflows/static.yml` runs the same page
generation and publishes the built `site/` directory to GitHub Pages after the
configured ROBOT checks pass.

## Add To An Existing Repository

Most ontology repositories should not fork this whole repository. Instead, build
the starter zip and extract it at the root of the ontology repository:

```powershell
python scripts/build_starter_zip.py
```

The zip is written to `dist/ontology-webhost-starter.zip`. By default it contains
only the reusable webhost machinery:

- `ontology-site.yml`
- `mkdocs.yml`
- `requirements.txt`
- `.github/workflows/static.yml`
- `scripts/generate_ontology_site.py`
- `scripts/run_robot_qa.py`
- `qa/queries/fail/*.rq`
- `qa/queries/warn/*.rq`
- `docs/patterns/example-pattern.mmd`
- `ONTOLOGY_WEBHOST_README.md`

It intentionally does not include generated output such as `site/`,
`docs/index.md`, `docs/qa.md`, `docs/ontologies/`, `docs/artifacts/`, or
`scripts/__pycache__/`.

If someone wants a runnable demo ontology in the zip too, build it with:

```powershell
python scripts/build_starter_zip.py --include-example-ontology
```

After extracting the zip into an existing repo, edit `ontology-site.yml` so the
`ontologies[*].path`, `imports.paths`, download paths, QA profiles, and design
pattern paths point at real files in that repository. If the repository already
has a `mkdocs.yml`, merge the generated `markdown_extensions`, `plugins`, and
workflow commands into the existing MkDocs setup instead of replacing it.

If GitHub already created `.github/workflows/static.yml` for Pages, replace that
file with this template's version or merge in the build steps. The GitHub
default static workflow uploads the whole repository with `path: '.'`; this
template instead generates the ontology pages, builds MkDocs, and uploads only
the built `site/` directory.

## YAML Configuration

The main configuration file is `ontology-site.yml`.

Key sections:

- `site`: MkDocs site name, repository URL, and short site description.
- `metadata`: repository-level introduction, license, contacts, and user or
  stakeholder buttons.
- `generation`: output directories and term table behavior.
- `ontologies`: ontology files that should each receive a generated page.
- `imports`: optional local import files used to resolve import diagram titles
  and parent labels.
- `design_patterns`: Mermaid files rendered on the landing page or selected
  ontology pages.
- `qa`: ROBOT QA profiles and SPARQL query paths.

Each ontology can configure extraction flags under `elicit`:

```yaml
ontologies:
  - id: core
    path: ontologies/core.ttl
    page: core.md
    elicit:
      title: true
      description: true
      contributors: true
      import_diagram: true
    overrides:
      title:
      description:
      contributors: []
      import_diagram:
```

When an `elicit` flag is `true`, the generator reads ontology metadata from RDF.
When it is `false`, it uses the corresponding value in `overrides`.

## Term Table Generation

Term tables include configured OWL entity types and emit:

| Column | Source |
|:---|:---|
| IRI | CURIE when a prefix is bound, otherwise full IRI |
| Type | OWL entity type |
| Label | `rdfs:label` |
| Alternative term | concatenated `skos:altLabel` |
| Definition | `skos:definition` |
| Parent | class `rdfs:subClassOf`, property `rdfs:subPropertyOf`, or named individual `rdf:type`, resolved to labels when available |

## Quality Assurance

The default workflow uses the `obolibrary/robot` Docker image and SPARQL query
files in `qa/queries`. Python is used only to read `ontology-site.yml`, write a
small ROBOT command script, and summarize the generated CSV files; ROBOT itself
runs inside the `obolibrary/robot` container.

`scripts/run_robot_qa.py` does not execute ROBOT in CI. It exists so
`ontology-site.yml` can stay the single source of truth for which queries run,
and so fail-query result rows can be counted after ROBOT writes CSV outputs.

The `qa.profiles` section in `ontology-site.yml` is a declarative list of ROBOT
queries. For example:

```yaml
ontologies:
  - id: example
    path: ontologies/example.ttl
    qa:
      profile: default

qa:
  profiles:
    default:
      fail:
        - qa/queries/fail/missing-definition.rq
      warn:
        - qa/queries/warn/missing-alt-label.rq
```

That YAML is translated into ROBOT CLI commands like:

```bash
robot -vvv query --input ontologies/example.ttl --query qa/queries/fail/missing-definition.rq build/qa/example/fail/missing-definition.csv --format CSV
```

The workflow prints the generated `build/qa/run_robot_queries.sh` file before it
runs, so the Actions log shows the exact ROBOT commands. The generated commands
include ROBOT's `-vvv` flag by default for verbose failure messages.

### Add QA Queries

To add a custom QA check for an ontology:

1. Add a SPARQL `SELECT` query file under `qa/queries/fail/` or
   `qa/queries/warn/`.
2. Add that file path to a profile in `ontology-site.yml`.
3. Assign the profile to each ontology that should use it with
   `ontologies[*].qa.profile`.
4. Preview the ROBOT commands with:

```powershell
python scripts/run_robot_qa.py --config ontology-site.yml --write-script build/qa/run_robot_queries.sh
Get-Content build\qa\run_robot_queries.sh
```

Use `fail` for checks that should block publication when ROBOT returns any rows.
Use `warn` for checks that should appear in the generated QA report without
blocking the GitHub Pages deploy.

For example:

```yaml
ontologies:
  - id: core
    path: ontologies/core.ttl
    qa:
      profile: strict

qa:
  profiles:
    strict:
      fail:
        - qa/queries/fail/q_class-missing-skos-definition.rq
        - qa/queries/fail/q_duplicateLabels.rq
      warn:
        - qa/queries/warn/q_class-missing-skos-example.rq
```

Multiple ontologies can reuse the same profile, or each ontology can point to a
different profile if the QA rules should vary by artifact.

Suggested query categories:

- `fail`: missing labels, missing definitions, malformed required metadata,
  unintended cycles, duplicate exact synonyms, unsatisfiable classes after
  reasoning, or invalid ontology IRI/version IRI conventions.
- `warn`: missing alternative labels, unresolved external parents, broad
  annotation hygiene issues, or modeling patterns that need curator review.

In CI, `scripts/run_robot_qa.py --write-script build/qa/run_robot_queries.sh`
writes the configured ROBOT commands. The workflow runs that script with:

```bash
docker run --rm -v "$PWD:/work" -w /work obolibrary/robot:latest sh build/qa/run_robot_queries.sh
```

Then `scripts/run_robot_qa.py --summarize-only` counts the CSV rows under
`build/qa`. The page generator counts those rows into `docs/qa.md`. Any rows
from a `fail` query make the workflow fail, which prevents publishing a site
that advertises a failed ontology release.

## Adapting For A New Repository

1. Replace `ontologies/example.ttl` with your ontology files.
2. Edit `ontology-site.yml`.
3. Add Mermaid diagrams under `docs/patterns` or point to your own paths.
4. Customize or add SPARQL checks under `qa/queries`.
5. Enable GitHub Pages with GitHub Actions as the source.
