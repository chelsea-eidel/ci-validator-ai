import re
from typing import Any, Dict, List, Tuple

import yaml

from models import AppliedFix


def fix_workflow(content: str) -> Tuple[str, List[AppliedFix]]:
    fixes: List[AppliedFix] = []

    new_content, text_fixes = _apply_textual_fixes(content)
    fixes.extend(text_fixes)

    try:
        data = yaml.safe_load(new_content)
    except yaml.YAMLError:
        return new_content, fixes

    if not isinstance(data, dict):
        return new_content, fixes

    data, struct_fixes = _apply_structural_fixes(data)
    fixes.extend(struct_fixes)

    if struct_fixes:
        if True in data:
            data = {("on" if k is True else k): v for k, v in data.items()}
        new_content = yaml.safe_dump(
            data, sort_keys=False, default_flow_style=False, width=100
        )

    return new_content, fixes


def _apply_textual_fixes(content: str) -> Tuple[str, List[AppliedFix]]:
    fixes: List[AppliedFix] = []

    new_content, n1 = re.subn(
        r'echo\s+"::set-output\s+name=([^:"]+)::([^"]*)"',
        r'echo "\1=\2" >> $GITHUB_OUTPUT',
        content,
    )
    if n1:
        fixes.append(AppliedFix(
            rule="deprecated-set-output",
            description=f"Replaced {n1} `::set-output` command(s) with `$GITHUB_OUTPUT` writes",
        ))

    new_content, n2 = re.subn(
        r'echo\s+"::save-state\s+name=([^:"]+)::([^"]*)"',
        r'echo "\1=\2" >> $GITHUB_STATE',
        new_content,
    )
    if n2:
        fixes.append(AppliedFix(
            rule="deprecated-save-state",
            description=f"Replaced {n2} `::save-state` command(s) with `$GITHUB_STATE` writes",
        ))

    return new_content, fixes


def _apply_structural_fixes(data: Dict[str, Any]) -> Tuple[Dict[str, Any], List[AppliedFix]]:
    fixes: List[AppliedFix] = []

    if "name" not in data:
        data = {"name": "Workflow", **data}
        fixes.append(AppliedFix(
            rule="missing-workflow-name",
            description="Added default top-level `name: Workflow`",
        ))

    if "permissions" not in data:
        new_data: Dict[str, Any] = {}
        inserted = False
        for k, v in data.items():
            new_data[k] = v
            normalized = "on" if k is True else k
            if normalized == "on" and not inserted:
                new_data["permissions"] = {"contents": "read"}
                inserted = True
        if not inserted:
            new_data["permissions"] = {"contents": "read"}
        data = new_data
        fixes.append(AppliedFix(
            rule="missing-permissions",
            description="Added minimal `permissions: contents: read`",
        ))

    jobs = data.get("jobs")
    if isinstance(jobs, dict):
        for job_id, job in list(jobs.items()):
            if isinstance(job, dict) and "uses" not in job and "runs-on" not in job:
                jobs[job_id] = {"runs-on": "ubuntu-latest", **job}
                fixes.append(AppliedFix(
                    rule="missing-runs-on",
                    description=f"Added default `runs-on: ubuntu-latest` to job `{job_id}`",
                ))

    return data, fixes
