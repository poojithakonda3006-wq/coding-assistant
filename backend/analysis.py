import ast
import tempfile
import os
import subprocess
import json
from typing import List
from models import Diagnostic, AnalysisResult

async def analyze_python_code(code: str) -> AnalysisResult:
    diagnostics: List[Diagnostic] = []
    
    # 1. Syntax Parsing
    try:
        ast.parse(code)
    except SyntaxError as e:
        diagnostics.append(Diagnostic(
            id="syntax_error",
            category="Syntax",
            severity="error",
            message=str(e),
            line=e.lineno,
            column=e.offset
        ))
        return AnalysisResult(status="failed", diagnostics=diagnostics)
        
    # 2. Static Analysis with Pylint
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.py', delete=False) as f:
        f.write(code)
        temp_path = f.name
        
    try:
        import sys
        # Run pylint, output JSON. Disabling conventions (C) and refactoring (R) to focus on actual warnings/errors for beginners
        result = subprocess.run(
            [sys.executable, '-m', 'pylint', temp_path, '--output-format=json', '--disable=C,R'], 
            capture_output=True, 
            text=True
        )
        if result.stdout:
            try:
                issues = json.loads(result.stdout)
                for issue in issues:
                    diagnostics.append(Diagnostic(
                        id=issue.get("message-id", "unknown"),
                        category="StaticAnalysis",
                        severity="warning" if issue.get("type") == "warning" else "error",
                        message=issue.get("message", "Unknown error"),
                        line=issue.get("line"),
                        column=issue.get("column")
                    ))
            except json.JSONDecodeError:
                pass
    except Exception as e:
        print(f"Pylint analysis failed: {e}")
    finally:
        os.remove(temp_path)
    
    status = "failed" if any(d.severity == "error" for d in diagnostics) else "success"
    return AnalysisResult(status=status, diagnostics=diagnostics)
