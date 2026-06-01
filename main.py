from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from fixer import fix_workflow
from models import (
    FixResponse,
    HealthResponse,
    Severity,
    ValidationRequest,
    ValidationResponse,
)
from validator import validate_workflow

app = FastAPI(
    title="GitHub Actions Workflow Validator",
    description="Validates GitHub Actions workflow YAML files against a set of rules.",
    version="1.0.0",
)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.post("/validate", response_model=ValidationResponse)
def validate(req: ValidationRequest) -> ValidationResponse:
    violations = validate_workflow(req.content)
    has_error = any(v.severity == Severity.ERROR for v in violations)
    return ValidationResponse(
        valid=not has_error,
        violation_count=len(violations),
        violations=violations,
    )


@app.post("/fix", response_model=FixResponse)
def fix(req: ValidationRequest) -> FixResponse:
    original_violations = validate_workflow(req.content)
    fixed_content, applied_fixes = fix_workflow(req.content)
    remaining = validate_workflow(fixed_content)
    has_error = any(v.severity == Severity.ERROR for v in remaining)
    return FixResponse(
        fixed_content=fixed_content,
        applied_fixes=applied_fixes,
        original_violations=original_violations,
        remaining_violations=remaining,
        valid_after_fix=not has_error,
    )
