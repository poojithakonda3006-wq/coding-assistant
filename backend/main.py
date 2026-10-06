from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from models import (
    CodeSubmission,
    AnalysisResult,
    DebugStep,
    Diagnostic,
    ExecutionResponse,
    ExplanationResponse,
    GuidedDebuggingResponse,
    HintResponse,
    RepairResponse,
    VerificationResponse,
)
from analysis import analyze_python_code
from ai_service import generate_explanation, generate_hint, generate_repair
from execution import RunnerUnavailable, run_in_sandbox, runner_status

app = FastAPI(title="AI Coding Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _sandbox_error(error: RunnerUnavailable) -> HTTPException:
    return HTTPException(status_code=503, detail=str(error))

async def _analyze_submission(submission: CodeSubmission) -> AnalysisResult:
    if submission.language == "python":
        return await analyze_python_code(submission.code)
    try:
        result = await run_in_threadpool(
            run_in_sandbox,
            submission.language,
            submission.code,
            "analyze",
            "",
            submission.timeout_ms,
        )
    except RunnerUnavailable as error:
        raise _sandbox_error(error) from error
    diagnostics = []
    if result["status"] != "success":
        diagnostics.append(Diagnostic(
            id="compile_error",
            category="Compilation",
            severity="error",
            message=(result.get("stderr") or result.get("stdout") or "Compilation failed.").strip(),
        ))
    return AnalysisResult(
        status="failed" if diagnostics else "success",
        diagnostics=diagnostics,
    )

@app.post("/api/v1/analysis", response_model=AnalysisResult)
async def analyze_code(submission: CodeSubmission):
    return await _analyze_submission(submission)

@app.post("/api/v1/analysis/explain", response_model=ExplanationResponse)
async def explain_code(submission: CodeSubmission):
    result = await _analyze_submission(submission)
    explanation = await generate_explanation(submission.code, result.diagnostics)
    return explanation

@app.post("/api/v1/analysis/hints", response_model=HintResponse)
async def get_hints(submission: CodeSubmission, level: int = 1):
    result = await _analyze_submission(submission)
    hint = await generate_hint(submission.code, result.diagnostics, level)
    return hint

@app.post("/api/v1/analysis/repair", response_model=RepairResponse)
async def get_repair(submission: CodeSubmission):
    result = await _analyze_submission(submission)
    try:
        repair = await generate_repair(submission.code, result.diagnostics, submission.language)
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Repair provider failed: {error}") from error
    return repair

@app.post("/api/v1/analysis/debug", response_model=GuidedDebuggingResponse)
async def guide_debugging(submission: CodeSubmission):
    result = await _analyze_submission(submission)
    if not result.diagnostics:
        return GuidedDebuggingResponse(
            summary="No syntax or static-analysis findings were detected.",
            steps=[
                DebugStep(
                    title="Compare expected and actual behavior",
                    instruction=(
                        "If the program still behaves incorrectly, provide its expected output and "
                        "the output you actually observed, then analyze it again."
                    ),
                ),
                DebugStep(
                    title="Review the relevant logic",
                    instruction="Trace the inputs through the code and check boundary cases and assumptions.",
                ),
                DebugStep(
                    title="Run your own tests",
                    instruction="Add or run tests for the expected behavior; this service does not execute submitted code.",
                ),
            ],
            limitations=["Runtime behavior and logical correctness were not executed or verified."],
        )

    primary = result.diagnostics[0]
    location = f" on line {primary.line}" if primary.line is not None else ""
    return GuidedDebuggingResponse(
        summary=f"Found {len(result.diagnostics)} diagnostic(s). Start with {primary.id}{location}: {primary.message}",
        steps=[
            DebugStep(
                title="Inspect the finding",
                instruction=f"Review the {primary.category.lower()} finding{location}: {primary.message}",
                diagnostic_id=primary.id,
            ),
            DebugStep(
                title="Examine the surrounding code",
                instruction="Read the affected statement and nearby definitions, inputs, and control flow before changing it.",
                diagnostic_id=primary.id,
            ),
            DebugStep(
                title="Try one focused change",
                instruction="Make a small change that addresses this finding. Keep the original code until you have reviewed the result.",
                diagnostic_id=primary.id,
            ),
            DebugStep(
                title="Analyze the updated code",
                instruction="Submit the updated code again and check whether this diagnostic disappeared or new findings appeared.",
                diagnostic_id=primary.id,
            ),
        ],
        limitations=["Static analysis cannot confirm runtime behavior or logical correctness."],
    )

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/api/v1/languages")
async def get_languages():
    runner = await run_in_threadpool(runner_status)
    return {
        "runner": runner,
        "languages": [
            {
                "id": language,
                "name": name,
                "analysis_available": (
                    language == "python"
                    or runner["available"]
                    and runner["image_available"]
                    and runner.get("languages", {}).get(language, {}).get("available", False)
                ),
                "execution_available": (
                    runner["available"]
                    and runner["image_available"]
                    and runner.get("languages", {}).get(language, {}).get("available", False)
                ),
            }
            for language, name in [
                ("python", "Python"),
                ("javascript", "JavaScript"),
                ("typescript", "TypeScript"),
                ("java", "Java"),
                ("c", "C"),
                ("cpp", "C++"),
            ]
        ],
    }

@app.post("/api/v1/execute", response_model=ExecutionResponse)
async def execute_code(submission: CodeSubmission):
    try:
        result = await run_in_threadpool(
            run_in_sandbox,
            submission.language,
            submission.code,
            "execute",
            submission.stdin,
            submission.timeout_ms,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RunnerUnavailable as error:
        raise _sandbox_error(error) from error
    return ExecutionResponse(language=submission.language, **result)

@app.post("/api/v1/analysis/verify", response_model=VerificationResponse)
async def verify_code(submission: CodeSubmission):
    result = await _analyze_submission(submission)
    
    passed_checks = []
    failed_checks = []

    if submission.language == "python":
        if result.status == "success":
            passed_checks.extend(["Syntax Parsing", "Static Analysis"])
        else:
            if any(d.id == "syntax_error" for d in result.diagnostics):
                failed_checks.append("Syntax Parsing")
            else:
                passed_checks.append("Syntax Parsing")

            if any(d.category == "StaticAnalysis" and d.severity == "error" for d in result.diagnostics):
                failed_checks.append("Static Analysis")
            else:
                passed_checks.append("Static Analysis")
    else:
        if result.status == "success":
            passed_checks.append("Language compiler/parser")
        else:
            failed_checks.append("Language compiler/parser")

    status = "verified" if not failed_checks else "failed"

    return VerificationResponse(
        status=status,
        message="Static checks passed or failed as listed. Runtime execution is a separate action.",
        executed_checks=["Syntax Parsing", "Static Analysis"] if submission.language == "python" else ["Language compiler/parser"],
        passed_checks=passed_checks,
        failed_checks=failed_checks,
        unverified_conditions=["Runtime behavior was not executed by verification."]
    )
