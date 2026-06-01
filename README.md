# GitHub Actions Workflow Validator

A small FastAPI service that validates GitHub Actions workflow YAML files
against a set of common-issue rules and returns a structured JSON report of
violations with rule id, severity, and description.

## Authors Note
This was a live-build during a Yahoo technical interview. I used Claude as a pair-programming assistant to scaffold the validator service, then iterated on the rule set, the auto-fixer behavior, and the YAML round-trip semantics through back-and-forth review. Everything that's here, I can walk through - it's the version I ended with after pushing back on the parts I disagreed with.

## Web UI

Open <http://127.0.0.1:8000/> after starting the service to get a drag-and-drop
page where you can drop one or more `.yml` / `.yaml` workflow files. Files are
sorted alphabetically by name, then each is validated in sequence via the
`/validate` endpoint and the violations are rendered grouped by file and
sorted by severity (error → warning → info).

## Endpoints

### `GET /health`

Liveness check.

```json
{ "status": "ok", "service": "github-actions-validator" }
```

### `POST /fix`

Runs the validator, applies every auto-fix it can, then re-validates. Request
body is identical to `/validate`. Response:

```json
{
  "fixed_content": "<rewritten YAML>",
  "applied_fixes": [
    { "rule": "missing-permissions", "description": "Added minimal `permissions: contents: read`" }
  ],
  "original_violations": [ /* violations before fix */ ],
  "remaining_violations": [ /* violations that couldn't be auto-fixed */ ],
  "valid_after_fix": true
}
```

Auto-fixable rules: `missing-workflow-name`, `missing-permissions`,
`missing-runs-on`, `deprecated-set-output`, `deprecated-save-state`.
Everything else is left to the author to fix — those violations appear in
`remaining_violations`. Structural fixes are applied by round-tripping
through PyYAML, so the rewritten file loses comments and original
formatting.

### `POST /validate`

Body:

```json
{ "content": "<raw workflow YAML>" }
```

Response:

```json
{
  "valid": false,
  "violation_count": 2,
  "violations": [
    {
      "rule": "missing-runs-on",
      "severity": "error",
      "description": "Job `build` is missing `runs-on`",
      "path": "jobs.build.runs-on"
    },
    {
      "rule": "action-not-pinned-to-sha",
      "severity": "warning",
      "description": "Action `actions/checkout@v4` is pinned to a mutable ref; pin to a full 40-char commit SHA for security",
      "path": "jobs.build.steps[0].uses"
    }
  ]
}
```

`valid` is `true` only when there are no `error`-severity violations.

## Rules

| Rule | Severity | What it catches |
| --- | --- | --- |
| `yaml-parse-error` | error | Malformed YAML |
| `empty-workflow` | error | Empty file |
| `invalid-root` | error | Root is not a mapping |
| `missing-on-trigger` | error | No `on:` block |
| `missing-jobs` | error | No `jobs:` block |
| `no-jobs-defined` | error | `jobs:` is empty |
| `missing-workflow-name` | warning | No top-level `name` |
| `unknown-top-level-key` | warning | Unrecognized top-level key |
| `invalid-jobs` | error | `jobs:` is not a mapping |
| `invalid-job` | error | Job value is not a mapping |
| `invalid-job-id` | error | Job id does not match allowed pattern |
| `unknown-job-key` | warning | Unrecognized key inside a job |
| `missing-runs-on` | error | Non-reusable job missing `runs-on` |
| `missing-steps` | error | Non-reusable job missing `steps` |
| `invalid-steps` | error | `steps` is not a list |
| `empty-steps` | warning | `steps` list is empty |
| `invalid-step` | error | Step is not a mapping |
| `step-missing-action` | error | Step has neither `uses` nor `run` |
| `step-uses-and-run` | error | Step has both `uses` and `run` |
| `action-not-pinned-to-sha` | warning | Action reference is a tag/branch rather than a full 40-char SHA |
| `missing-permissions` | info | No top-level `permissions` declared |
| `secret-in-run-command` | warning | `${{ secrets.* }}` interpolated directly into a `run:` step |
| `deprecated-set-output` | warning | Uses `::set-output` workflow command |
| `deprecated-save-state` | warning | Uses `::save-state` workflow command |

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run the service

```bash
uvicorn main:app --reload
```

Interactive docs: <http://127.0.0.1:8000/docs>

## Try it

```bash
curl -s http://127.0.0.1:8000/health

curl -s -X POST http://127.0.0.1:8000/validate \
  -H "content-type: application/json" \
  -d "$(jq -Rs '{content: .}' < .github/workflows/ci.yml)"
```

## Run the tests

```bash
pytest -v
```

The test suite (`test_validator.py`) covers the health endpoint, the
`/validate` endpoint's response shape, and each rule listed above against
hand-crafted workflow snippets.

## Project layout

```
.
├── main.py             # FastAPI app and routes
├── models.py           # Pydantic request/response models
├── validator.py        # Rule implementations
├── fixer.py            # Auto-fix layer for fixable rules
├── static/index.html   # Drag-and-drop web UI
├── samples/            # Example workflow YAMLs
├── test_validator.py   # pytest suite (rules + fixer)
├── requirements.txt
└── README.md
```
