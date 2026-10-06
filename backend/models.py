from pydantic import BaseModel, Field
from typing import List, Literal, Optional

class CodeSubmission(BaseModel):
    language: Literal["python", "javascript", "typescript", "java", "c", "cpp"]
    code: str = Field(max_length=65_536)
    context: Optional[str] = None
    stdin: str = Field(default="", max_length=16_384)
    timeout_ms: int = Field(default=5000, ge=100, le=10_000)

SUPPORTED_LANGUAGES = ("python", "javascript", "typescript", "java", "c", "cpp")

class Diagnostic(BaseModel):
    id: str
    category: str
    severity: str
    message: str
    line: Optional[int] = None
    column: Optional[int] = None

class AnalysisResult(BaseModel):
    status: str
    diagnostics: List[Diagnostic]

class ExplanationResponse(BaseModel):
    explanation: str

class HintResponse(BaseModel):
    hint_level: int
    hint: str

class RepairResponse(BaseModel):
    proposed_code: Optional[str] = None
    explanation: str
    validation_status: Literal["validated", "unverified", "not_available"]
    validation_checks: List[str] = Field(default_factory=list)
    remaining_issues: List[str] = Field(default_factory=list)

class DebugStep(BaseModel):
    title: str
    instruction: str
    diagnostic_id: Optional[str] = None

class GuidedDebuggingResponse(BaseModel):
    summary: str
    steps: List[DebugStep]
    limitations: List[str] = Field(default_factory=list)

class VerificationResponse(BaseModel):
    status: str
    message: str
    executed_checks: List[str]
    passed_checks: List[str]
    failed_checks: List[str]
    unverified_conditions: List[str]

class ExecutionResponse(BaseModel):
    language: str
    status: Literal["completed", "compile_error", "runtime_error", "timed_out", "output_limited", "error"]
    stdout: str
    stderr: str
    exit_code: Optional[int] = None
    timed_out: bool = False
    output_limited: bool = False
