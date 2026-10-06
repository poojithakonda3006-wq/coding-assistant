import ast
import asyncio
import builtins
import difflib
import json
import os
import re
from typing import List, Optional

from openai import AsyncOpenAI
from models import Diagnostic, ExplanationResponse, HintResponse, RepairResponse
from analysis import analyze_python_code
from execution import RunnerUnavailable, run_in_sandbox, runner_status


def _openai_client() -> Optional[AsyncOpenAI]:
    api_key = os.environ.get("OPENAI_API_KEY")
    return AsyncOpenAI(api_key=api_key) if api_key else None

async def generate_explanation(code: str, diagnostics: List[Diagnostic]) -> ExplanationResponse:
    if not diagnostics:
        return ExplanationResponse(explanation="The code looks good.")
    
    # In a real setup, we would call the OpenAI API.
    # For now, if no key is set, we return a mock.
    client = _openai_client()
    if client is None:
        error_names = [d.id for d in diagnostics]
        return ExplanationResponse(explanation=f"Mock explanation: The code contains errors such as {', '.join(error_names)}.")
    
    # Example OpenAI call (simplified)
    # response = await client.chat.completions.create(...)
    return ExplanationResponse(explanation="Generated explanation here.")

async def generate_hint(code: str, diagnostics: List[Diagnostic], hint_level: int) -> HintResponse:
    client = _openai_client()
    if client is None:
        hints = [
            "Level 1: Look at the variables you are using.",
            "Level 2: Ensure all variables are defined before using them.",
            "Level 3: You need to assign a value to variables before use."
        ]
        return HintResponse(
            hint_level=hint_level, 
            hint=hints[min(hint_level - 1, len(hints)-1)]
        )
    return HintResponse(hint_level=hint_level, hint="Generated hint here.")

async def generate_repair(code: str, diagnostics: List[Diagnostic], language: str = "python") -> RepairResponse:
    if not diagnostics:
        return RepairResponse(
            proposed_code=None,
            explanation="No diagnostics were found, so there is no correction to propose.",
            validation_status="validated",
            validation_checks=["Syntax parsing", "Static analysis"],
        )

    deterministic_code = _repair_undefined_name(code, diagnostics) if language == "python" else None
    if deterministic_code is not None:
        return await _validate_repair(
            deterministic_code,
            "Corrected a likely misspelled identifier based on a uniquely similar name already present in the code.",
            language,
        )

    client = _openai_client()
    if client is None:
        return RepairResponse(
            proposed_code=None,
            explanation=(
                "I could not safely infer a correction from the diagnostics alone. "
                "Configure OPENAI_API_KEY in the backend environment to enable AI-generated repair proposals."
            ),
            validation_status="not_available",
            remaining_issues=[_describe_diagnostic(diagnostic) for diagnostic in diagnostics],
        )

    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    response = await client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    f"You propose minimal {language} source repairs. Do not claim to execute code. "
                    "Return JSON with proposed_code (a complete source file) and explanation. "
                    "If the evidence is insufficient, return proposed_code as an empty string and explain why."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "source_code": code,
                        "diagnostics": [diagnostic.model_dump() for diagnostic in diagnostics],
                    }
                ),
            },
        ],
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("The AI provider returned an empty repair response.")
    try:
        proposal = json.loads(content)
        proposed_code = proposal.get("proposed_code")
        explanation = proposal.get("explanation")
    except (json.JSONDecodeError, AttributeError) as error:
        raise ValueError("The AI provider returned an invalid repair response.") from error
    if not isinstance(proposed_code, str) or not isinstance(explanation, str):
        raise ValueError("The AI provider response must include proposed_code and explanation strings.")
    if not proposed_code.strip() or proposed_code == code:
        return RepairResponse(
            proposed_code=None,
            explanation=explanation or "The AI provider could not identify a safe correction.",
            validation_status="not_available",
            remaining_issues=[_describe_diagnostic(diagnostic) for diagnostic in diagnostics],
        )

    return await _validate_repair(proposed_code, explanation, language)


def _repair_undefined_name(code: str, diagnostics: List[Diagnostic]) -> Optional[str]:
    diagnostic = next(
        (item for item in diagnostics if item.id == "E0602" and item.line is not None),
        None,
    )
    if diagnostic is None:
        return None

    match = re.search(r"Undefined variable '([^']+)'", diagnostic.message)
    if match is None:
        return None
    undefined_name = match.group(1)

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    candidates = set(dir(builtins))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            candidates.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            candidates.add(node.name)
        elif isinstance(node, ast.arg):
            candidates.add(node.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            candidates.update(alias.asname or alias.name.split(".")[0] for alias in node.names)

    candidates.discard(undefined_name)
    matches = difflib.get_close_matches(undefined_name, sorted(candidates), n=2, cutoff=0.78)
    if not matches:
        return None
    if len(matches) > 1:
        best = difflib.SequenceMatcher(None, undefined_name, matches[0]).ratio()
        second = difflib.SequenceMatcher(None, undefined_name, matches[1]).ratio()
        if best - second < 0.08:
            return None

    lines = code.splitlines(keepends=True)
    line_index = diagnostic.line - 1
    if line_index < 0 or line_index >= len(lines):
        return None
    line = lines[line_index]
    column = diagnostic.column or 0
    token_pattern = re.compile(rf"\b{re.escape(undefined_name)}\b")
    if line[column : column + len(undefined_name)] == undefined_name:
        start = column
    else:
        occurrences = list(token_pattern.finditer(line))
        if len(occurrences) != 1:
            return None
        start = occurrences[0].start()
    lines[line_index] = line[:start] + matches[0] + line[start + len(undefined_name) :]
    return "".join(lines)


async def _validate_repair(proposed_code: str, explanation: str, language: str) -> RepairResponse:
    if language == "python":
        try:
            ast.parse(proposed_code)
        except SyntaxError as error:
            raise ValueError(f"The proposed repair has a syntax error: {error.msg}.") from error
        result = await analyze_python_code(proposed_code)
        diagnostics = result.diagnostics
        checks = ["Syntax parsing", "Pylint static analysis"]
    else:
        status = runner_status()
        if not status["available"] or not status["image_available"]:
            return RepairResponse(
                proposed_code=proposed_code,
                explanation=explanation,
                validation_status="unverified",
                remaining_issues=["The isolated compiler is not available to validate this proposal."],
            )
        try:
            result = await asyncio.to_thread(run_in_sandbox, language, proposed_code, "analyze")
        except RunnerUnavailable as error:
            return RepairResponse(
                proposed_code=proposed_code,
                explanation=explanation,
                validation_status="unverified",
                remaining_issues=[f"Compiler validation was unavailable: {error}"],
            )
        diagnostics = []
        if result["status"] != "success":
            diagnostics.append(Diagnostic(
                id="compile_error",
                category="Compilation",
                severity="error",
                message=(result.get("stderr") or result.get("stdout") or "Compilation failed.").strip(),
            ))
        checks = ["Language compiler/parser"]

    remaining_issues = [_describe_diagnostic(item) for item in diagnostics]
    return RepairResponse(
        proposed_code=proposed_code,
        explanation=explanation,
        validation_status="validated" if not remaining_issues else "unverified",
        validation_checks=checks,
        remaining_issues=remaining_issues,
    )


def _describe_diagnostic(diagnostic: Diagnostic) -> str:
    location = f"Line {diagnostic.line}: " if diagnostic.line is not None else ""
    return f"{location}{diagnostic.message}"
