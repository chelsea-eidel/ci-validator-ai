import re
from typing import Any, Dict, List

import yaml

from models import Severity, Violation


VALID_TOP_LEVEL_KEYS = {
    "name", "on", "permissions", "env", "defaults", "concurrency",
    "jobs", "run-name",
}

VALID_JOB_KEYS = {
    "name", "needs", "if", "runs-on", "environment", "concurrency",
    "outputs", "env", "defaults", "steps", "timeout-minutes", "strategy",
    "continue-on-error", "container", "services", "uses", "with",
    "secrets", "permissions",
}

UNPINNED_ACTION_RE = re.compile(r"^[^/]+/[^@]+@(main|master|v?\d+)$")
SHA_PINNED_RE = re.compile(r"@[0-9a-f]{40}$")


def _walk(node: Any, path: str = ""):
    yield path, node
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")


def validate_workflow(content: str) -> List[Violation]:
    violations: List[Violation] = []

    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        violations.append(Violation(
            rule="yaml-parse-error",
            severity=Severity.ERROR,
            description=f"Invalid YAML: {e}",
        ))
        return violations

    if data is None:
        violations.append(Violation(
            rule="empty-workflow",
            severity=Severity.ERROR,
            description="Workflow file is empty",
        ))
        return violations

    if not isinstance(data, dict):
        violations.append(Violation(
            rule="invalid-root",
            severity=Severity.ERROR,
            description="Workflow root must be a mapping",
        ))
        return violations

    violations.extend(_check_required_top_level(data))
    violations.extend(_check_unknown_top_level(data))
    violations.extend(_check_jobs(data.get("jobs")))
    violations.extend(_check_permissions(data))
    violations.extend(_check_secret_exposure(data))
    violations.extend(_check_deprecated_commands(content))

    return violations


def _check_required_top_level(data: Dict[str, Any]) -> List[Violation]:
    out: List[Violation] = []
    # PyYAML parses the bare key `on` as True (YAML 1.1 boolean). Accept both.
    if "on" not in data and True not in data:
        out.append(Violation(
            rule="missing-on-trigger",
            severity=Severity.ERROR,
            description="Workflow must define an `on` trigger",
            path="on",
        ))
    if "jobs" not in data:
        out.append(Violation(
            rule="missing-jobs",
            severity=Severity.ERROR,
            description="Workflow must define a `jobs` block",
            path="jobs",
        ))
    if "name" not in data:
        out.append(Violation(
            rule="missing-workflow-name",
            severity=Severity.WARNING,
            description="Workflow should define a top-level `name`",
            path="name",
        ))
    return out


def _check_unknown_top_level(data: Dict[str, Any]) -> List[Violation]:
    out: List[Violation] = []
    for key in data.keys():
        normalized = "on" if key is True else key
        if normalized not in VALID_TOP_LEVEL_KEYS:
            out.append(Violation(
                rule="unknown-top-level-key",
                severity=Severity.WARNING,
                description=f"Unknown top-level key `{normalized}`",
                path=str(normalized),
            ))
    return out


def _check_jobs(jobs: Any) -> List[Violation]:
    out: List[Violation] = []
    if jobs is None:
        return out
    if not isinstance(jobs, dict):
        out.append(Violation(
            rule="invalid-jobs",
            severity=Severity.ERROR,
            description="`jobs` must be a mapping of job id to job definition",
            path="jobs",
        ))
        return out
    if len(jobs) == 0:
        out.append(Violation(
            rule="no-jobs-defined",
            severity=Severity.ERROR,
            description="`jobs` block defines no jobs",
            path="jobs",
        ))
    for job_id, job in jobs.items():
        out.extend(_check_job(str(job_id), job))
    return out


def _check_job(job_id: str, job: Any) -> List[Violation]:
    out: List[Violation] = []
    base = f"jobs.{job_id}"

    if not isinstance(job, dict):
        out.append(Violation(
            rule="invalid-job",
            severity=Severity.ERROR,
            description=f"Job `{job_id}` must be a mapping",
            path=base,
        ))
        return out

    if not re.match(r"^[A-Za-z_][A-Za-z0-9_-]*$", job_id):
        out.append(Violation(
            rule="invalid-job-id",
            severity=Severity.ERROR,
            description=f"Job id `{job_id}` must match [A-Za-z_][A-Za-z0-9_-]*",
            path=base,
        ))

    for key in job.keys():
        if key not in VALID_JOB_KEYS:
            out.append(Violation(
                rule="unknown-job-key",
                severity=Severity.WARNING,
                description=f"Unknown job key `{key}` in job `{job_id}`",
                path=f"{base}.{key}",
            ))

    is_reusable = "uses" in job
    if not is_reusable:
        if "runs-on" not in job:
            out.append(Violation(
                rule="missing-runs-on",
                severity=Severity.ERROR,
                description=f"Job `{job_id}` is missing `runs-on`",
                path=f"{base}.runs-on",
            ))
        if "steps" not in job:
            out.append(Violation(
                rule="missing-steps",
                severity=Severity.ERROR,
                description=f"Job `{job_id}` is missing `steps`",
                path=f"{base}.steps",
            ))
        else:
            out.extend(_check_steps(job_id, job.get("steps")))

    return out


def _check_steps(job_id: str, steps: Any) -> List[Violation]:
    out: List[Violation] = []
    base = f"jobs.{job_id}.steps"

    if not isinstance(steps, list):
        out.append(Violation(
            rule="invalid-steps",
            severity=Severity.ERROR,
            description=f"`steps` in job `{job_id}` must be a list",
            path=base,
        ))
        return out

    if len(steps) == 0:
        out.append(Violation(
            rule="empty-steps",
            severity=Severity.WARNING,
            description=f"Job `{job_id}` has an empty `steps` list",
            path=base,
        ))

    for i, step in enumerate(steps):
        path = f"{base}[{i}]"
        if not isinstance(step, dict):
            out.append(Violation(
                rule="invalid-step",
                severity=Severity.ERROR,
                description=f"Step {i} in job `{job_id}` must be a mapping",
                path=path,
            ))
            continue

        has_uses = "uses" in step
        has_run = "run" in step
        if has_uses and has_run:
            out.append(Violation(
                rule="step-uses-and-run",
                severity=Severity.ERROR,
                description=f"Step {i} in job `{job_id}` must not set both `uses` and `run`",
                path=path,
            ))
        elif not has_uses and not has_run:
            out.append(Violation(
                rule="step-missing-action",
                severity=Severity.ERROR,
                description=f"Step {i} in job `{job_id}` must define either `uses` or `run`",
                path=path,
            ))

        if has_uses:
            uses = step["uses"]
            if isinstance(uses, str) and "@" in uses and not SHA_PINNED_RE.search(uses):
                if UNPINNED_ACTION_RE.match(uses):
                    out.append(Violation(
                        rule="action-not-pinned-to-sha",
                        severity=Severity.WARNING,
                        description=(
                            f"Action `{uses}` is pinned to a mutable ref; "
                            "pin to a full 40-char commit SHA for security"
                        ),
                        path=f"{path}.uses",
                    ))

    return out


def _check_permissions(data: Dict[str, Any]) -> List[Violation]:
    out: List[Violation] = []
    if "permissions" not in data:
        out.append(Violation(
            rule="missing-permissions",
            severity=Severity.INFO,
            description=(
                "Workflow does not declare top-level `permissions`; "
                "consider restricting the default GITHUB_TOKEN scope"
            ),
            path="permissions",
        ))
    return out


def _check_secret_exposure(data: Dict[str, Any]) -> List[Violation]:
    out: List[Violation] = []
    for path, node in _walk(data):
        if not isinstance(node, str):
            continue
        if path.endswith(".run") or path.endswith(".if"):
            if re.search(r"\$\{\{\s*secrets\.[A-Z0-9_]+\s*\}\}", node):
                if path.endswith(".run"):
                    out.append(Violation(
                        rule="secret-in-run-command",
                        severity=Severity.WARNING,
                        description=(
                            "Secret is interpolated directly into a shell command; "
                            "pass via `env:` instead to avoid leaking in logs"
                        ),
                        path=path,
                    ))
    return out


def _check_deprecated_commands(content: str) -> List[Violation]:
    out: List[Violation] = []
    if re.search(r"::set-output\s+name=", content):
        out.append(Violation(
            rule="deprecated-set-output",
            severity=Severity.WARNING,
            description=(
                "`::set-output` is deprecated; write to $GITHUB_OUTPUT instead"
            ),
        ))
    if re.search(r"::save-state\s+name=", content):
        out.append(Violation(
            rule="deprecated-save-state",
            severity=Severity.WARNING,
            description=(
                "`::save-state` is deprecated; write to $GITHUB_STATE instead"
            ),
        ))
    return out
