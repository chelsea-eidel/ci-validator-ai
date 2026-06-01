from enum import Enum
from typing import List
from pydantic import BaseModel, Field


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Violation(BaseModel):
    rule: str = Field(..., description="Identifier of the rule that was violated")
    severity: Severity = Field(..., description="Severity level of the violation")
    description: str = Field(..., description="Human-readable description of the violation")
    path: str = Field(default="", description="YAML path where the violation occurred")


class ValidationRequest(BaseModel):
    content: str = Field(..., description="Raw YAML content of a GitHub Actions workflow")


class ValidationResponse(BaseModel):
    valid: bool = Field(..., description="True when no error-severity violations were found")
    violation_count: int = Field(..., description="Total number of violations")
    violations: List[Violation] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "github-actions-validator"


class AppliedFix(BaseModel):
    rule: str = Field(..., description="Rule that was auto-fixed")
    description: str = Field(..., description="What the fixer did")


class FixResponse(BaseModel):
    fixed_content: str = Field(..., description="YAML after fixes were applied")
    applied_fixes: List[AppliedFix] = Field(default_factory=list)
    original_violations: List[Violation] = Field(default_factory=list)
    remaining_violations: List[Violation] = Field(default_factory=list)
    valid_after_fix: bool = Field(..., description="True when no error-severity violations remain")
