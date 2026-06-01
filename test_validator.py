from fastapi.testclient import TestClient

from fixer import fix_workflow
from main import app
from validator import validate_workflow

client = TestClient(app)


def _fix_and_revalidate(content):
    fixed, applied = fix_workflow(content)
    remaining = validate_workflow(fixed)
    return fixed, applied, remaining


VALID_WORKFLOW = """
name: CI
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@8f4b7f84864484a7bf31766abe9204da3cbe65b3
      - run: echo hello
"""


def _rules(violations):
    return {v.rule for v in violations}


def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_valid_workflow_has_no_errors():
    violations = validate_workflow(VALID_WORKFLOW)
    errors = [v for v in violations if v.severity == "error"]
    assert errors == []


def test_invalid_yaml():
    content = "name: CI\non: [push\njobs: {}"
    rules = _rules(validate_workflow(content))
    assert "yaml-parse-error" in rules


def test_empty_content():
    rules = _rules(validate_workflow(""))
    assert "empty-workflow" in rules


def test_missing_on_trigger():
    content = """
name: CI
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
"""
    rules = _rules(validate_workflow(content))
    assert "missing-on-trigger" in rules


def test_missing_jobs():
    content = """
name: CI
on: push
"""
    rules = _rules(validate_workflow(content))
    assert "missing-jobs" in rules


def test_missing_runs_on():
    content = """
on: push
jobs:
  build:
    steps:
      - run: echo hi
"""
    rules = _rules(validate_workflow(content))
    assert "missing-runs-on" in rules


def test_step_without_uses_or_run():
    content = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: bad step
"""
    rules = _rules(validate_workflow(content))
    assert "step-missing-action" in rules


def test_step_with_both_uses_and_run():
    content = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        run: echo hi
"""
    rules = _rules(validate_workflow(content))
    assert "step-uses-and-run" in rules


def test_action_not_pinned_to_sha():
    content = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
"""
    rules = _rules(validate_workflow(content))
    assert "action-not-pinned-to-sha" in rules


def test_deprecated_set_output():
    content = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo "::set-output name=foo::bar"
"""
    rules = _rules(validate_workflow(content))
    assert "deprecated-set-output" in rules


def test_secret_in_run_command():
    content = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: 'curl -H "Authorization: ${{ secrets.TOKEN }}" https://example.com'
"""
    rules = _rules(validate_workflow(content))
    assert "secret-in-run-command" in rules


def test_invalid_job_id():
    content = """
on: push
jobs:
  "1bad":
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
"""
    rules = _rules(validate_workflow(content))
    assert "invalid-job-id" in rules


def test_unknown_top_level_key():
    content = """
on: push
bogus: true
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
"""
    rules = _rules(validate_workflow(content))
    assert "unknown-top-level-key" in rules


def test_validate_endpoint_returns_structured_response():
    resp = client.post("/validate", json={"content": VALID_WORKFLOW})
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["violation_count"] == len(body["violations"])
    for v in body["violations"]:
        assert set(v.keys()) >= {"rule", "severity", "description"}


def test_validate_endpoint_flags_errors():
    resp = client.post("/validate", json={"content": "jobs: {}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert body["violation_count"] > 0


# ---------------------------------------------------------------------------
# Fixer tests: each confirms the violation exists before fix and is gone after.
# ---------------------------------------------------------------------------


def test_fix_adds_missing_workflow_name():
    content = """
on: push
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
"""
    assert "missing-workflow-name" in _rules(validate_workflow(content))
    _, applied, remaining = _fix_and_revalidate(content)
    assert "missing-workflow-name" in {f.rule for f in applied}
    assert "missing-workflow-name" not in _rules(remaining)


def test_fix_adds_missing_permissions():
    content = """
name: CI
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
"""
    assert "missing-permissions" in _rules(validate_workflow(content))
    _, applied, remaining = _fix_and_revalidate(content)
    assert "missing-permissions" in {f.rule for f in applied}
    assert "missing-permissions" not in _rules(remaining)


def test_fix_adds_missing_runs_on():
    content = """
name: CI
on: push
permissions:
  contents: read
jobs:
  build:
    steps:
      - run: echo hi
"""
    assert "missing-runs-on" in _rules(validate_workflow(content))
    _, applied, remaining = _fix_and_revalidate(content)
    assert "missing-runs-on" in {f.rule for f in applied}
    assert "missing-runs-on" not in _rules(remaining)


def test_fix_rewrites_deprecated_set_output():
    content = """
name: CI
on: push
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo "::set-output name=version::1.2.3"
"""
    assert "deprecated-set-output" in _rules(validate_workflow(content))
    fixed, applied, remaining = _fix_and_revalidate(content)
    assert "deprecated-set-output" in {f.rule for f in applied}
    assert "deprecated-set-output" not in _rules(remaining)
    assert "$GITHUB_OUTPUT" in fixed
    assert "::set-output" not in fixed


def test_fix_rewrites_deprecated_save_state():
    content = """
name: CI
on: push
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo "::save-state name=cache::true"
"""
    assert "deprecated-save-state" in _rules(validate_workflow(content))
    fixed, applied, remaining = _fix_and_revalidate(content)
    assert "deprecated-save-state" in {f.rule for f in applied}
    assert "deprecated-save-state" not in _rules(remaining)
    assert "$GITHUB_STATE" in fixed


def test_fix_is_noop_for_clean_workflow():
    content = """
name: CI
on: push
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@8f4b7f84864484a7bf31766abe9204da3cbe65b3
      - run: echo hi
"""
    _, applied, remaining = _fix_and_revalidate(content)
    assert applied == []
    assert [v for v in remaining if v.severity == "error"] == []


def test_fix_partial_when_some_issues_not_fixable():
    # missing-on-trigger is not auto-fixable; make sure fixer still runs what it can
    content = """
name: Partial
jobs:
  build:
    steps:
      - run: echo hi
"""
    rules_before = _rules(validate_workflow(content))
    assert {"missing-on-trigger", "missing-runs-on"}.issubset(rules_before)
    _, applied, remaining = _fix_and_revalidate(content)
    applied_rules = {f.rule for f in applied}
    assert "missing-runs-on" in applied_rules
    rules_after = _rules(remaining)
    assert "missing-runs-on" not in rules_after
    assert "missing-on-trigger" in rules_after  # still present, can't auto-fix


def test_fix_endpoint_returns_structured_response():
    content = """
on: push
jobs:
  build:
    steps:
      - run: echo "::set-output name=x::1"
"""
    resp = client.post("/fix", json={"content": content})
    assert resp.status_code == 200
    body = resp.json()
    assert "fixed_content" in body
    assert "applied_fixes" in body
    assert "original_violations" in body
    assert "remaining_violations" in body
    original_rules = {v["rule"] for v in body["original_violations"]}
    remaining_rules = {v["rule"] for v in body["remaining_violations"]}
    assert {"missing-runs-on", "missing-workflow-name", "deprecated-set-output"}.issubset(original_rules)
    assert "deprecated-set-output" not in remaining_rules
    assert "missing-runs-on" not in remaining_rules
    assert "missing-workflow-name" not in remaining_rules
