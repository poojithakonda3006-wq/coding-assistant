from fastapi.testclient import TestClient
from main import app
from execution import RunnerUnavailable
import json
import subprocess
import execution
import main
import pytest

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_analyze_python_syntax_error():
    response = client.post("/api/v1/analysis", json={
        "language": "python",
        "code": "def foo()\n    pass"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert len(data["diagnostics"]) > 0
    assert data["diagnostics"][0]["id"] == "syntax_error"

def test_analyze_python_success():
    response = client.post("/api/v1/analysis", json={
        "language": "python",
        "code": "def foo():\n    pass"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert len(data["diagnostics"]) == 0

def test_analyze_python_static_analysis():
    response = client.post("/api/v1/analysis", json={
        "language": "python",
        "code": "def foo():\n    print(undefined_variable)\n"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert len(data["diagnostics"]) > 0
    # E0602 is undefined-variable in pylint
    assert any(d["id"] == "E0602" for d in data["diagnostics"])

def test_explain_code():
    response = client.post("/api/v1/analysis/explain", json={
        "language": "python",
        "code": "def foo():\n    print(undefined_variable)\n"
    })
    assert response.status_code == 200
    assert "Mock explanation" in response.json()["explanation"]

def test_get_hints():
    response = client.post("/api/v1/analysis/hints?level=2", json={
        "language": "python",
        "code": "def foo():\n    print(undefined_variable)\n"
    })
    assert response.status_code == 200
    assert response.json()["hint_level"] == 2
    assert "Level 2:" in response.json()["hint"]

def test_get_repair():
    response = client.post("/api/v1/analysis/repair", json={
        "language": "python",
        "code": "def foo():\n    print(undefined_variable)\n"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["proposed_code"] is None
    assert data["validation_status"] == "not_available"
    assert "OPENAI_API_KEY" in data["explanation"]
    assert "undefined_variable" in data["remaining_issues"][0]

def test_repair_corrects_unique_misspelled_identifier():
    response = client.post("/api/v1/analysis/repair", json={
        "language": "python",
        "code": "print('hello')\npritn('typo')\n"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["proposed_code"] == "print('hello')\nprint('typo')\n"
    assert data["validation_status"] == "validated"
    assert data["validation_checks"] == ["Syntax parsing", "Pylint static analysis"]
    assert data["remaining_issues"] == []

def test_guided_debugging_uses_detected_diagnostic():
    response = client.post("/api/v1/analysis/debug", json={
        "language": "python",
        "code": "print(missing_name)"
    })
    assert response.status_code == 200
    data = response.json()
    assert "E0602" in data["summary"]
    assert len(data["steps"]) == 4
    assert data["steps"][0]["diagnostic_id"] == "E0602"
    assert "runtime behavior" in data["limitations"][0]

def test_guided_debugging_clean_code_discloses_limits():
    response = client.post("/api/v1/analysis/debug", json={
        "language": "python",
        "code": "def add(left, right):\n    return left + right\n"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["steps"][0]["title"] == "Compare expected and actual behavior"
    assert "not executed or verified" in data["limitations"][0]

def test_verify_code():
    response = client.post("/api/v1/analysis/verify", json={
        "language": "python",
        "code": "def foo():\n    pass\n"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "verified"
    assert "Syntax Parsing" in data["passed_checks"]
    assert "Static Analysis" in data["passed_checks"]
    assert "Runtime behavior was not executed" in data["unverified_conditions"][0]

def test_language_status_reports_real_runner_readiness(monkeypatch):
    monkeypatch.setattr(main, "runner_status", lambda: {
        "available": False,
        "image_available": False,
        "message": "Docker CLI is not installed.",
    })
    data = client.get("/api/v1/languages").json()
    assert len(data["languages"]) == 6
    assert data["languages"][0]["id"] == "python"
    assert data["languages"][0]["analysis_available"] is True
    assert all(language["execution_available"] is False for language in data["languages"])

def test_javascript_analysis_uses_sandbox_runner(monkeypatch):
    monkeypatch.setattr(main, "run_in_sandbox", lambda *args: {
        "status": "success",
        "stdout": "",
        "stderr": "",
        "exit_code": 0,
        "timed_out": False,
        "output_limited": False,
    })
    response = client.post("/api/v1/analysis", json={
        "language": "javascript",
        "code": "console.log('hello')",
    })
    assert response.status_code == 200
    assert response.json() == {"status": "success", "diagnostics": []}

def test_javascript_compile_error_becomes_diagnostic(monkeypatch):
    monkeypatch.setattr(main, "run_in_sandbox", lambda *args: {
        "status": "compile_error",
        "stdout": "",
        "stderr": "SyntaxError: Unexpected token",
        "exit_code": 1,
        "timed_out": False,
        "output_limited": False,
    })
    response = client.post("/api/v1/analysis", json={
        "language": "javascript",
        "code": "const =",
    })
    assert response.status_code == 200
    assert response.json()["diagnostics"][0]["category"] == "Compilation"

def test_javascript_execution_passes_stdin_and_timeout(monkeypatch):
    received = {}

    def fake_run(language, code, action, stdin, timeout_ms):
        received.update(language=language, code=code, action=action, stdin=stdin, timeout_ms=timeout_ms)
        return {
            "status": "completed",
            "stdout": "Hello from JS",
            "stderr": "",
            "exit_code": 0,
            "timed_out": False,
            "output_limited": False,
        }

    monkeypatch.setattr(main, "run_in_sandbox", fake_run)
    response = client.post("/api/v1/execute", json={
        "language": "javascript",
        "code": "console.log('Hello from JS')",
        "stdin": "input",
        "timeout_ms": 1500,
    })
    assert response.status_code == 200
    assert response.json()["stdout"] == "Hello from JS"
    assert received == {
        "language": "javascript",
        "code": "console.log('Hello from JS')",
        "action": "execute",
        "stdin": "input",
        "timeout_ms": 1500,
    }

def test_execute_reports_missing_isolation_runner(monkeypatch):
    def missing_runner(*args):
        raise RunnerUnavailable("Docker daemon is not running.")

    monkeypatch.setattr(main, "run_in_sandbox", missing_runner)
    response = client.post("/api/v1/execute", json={
        "language": "cpp",
        "code": "#include <iostream>\nint main() { return 0; }",
    })
    assert response.status_code == 503
    assert "Docker daemon is not running" in response.json()["detail"]

def test_submission_rejects_excessive_runtime_timeout():
    response = client.post("/api/v1/execute", json={
        "language": "python",
        "code": "print('hello')",
        "timeout_ms": 60_000,
    })
    assert response.status_code == 422

def test_sandbox_invocation_uses_resource_and_network_restrictions(monkeypatch):
    monkeypatch.setattr(execution.shutil, "which", lambda name: "docker")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[1:2] == ["info"]:
            return subprocess.CompletedProcess(command, 0, stdout="server", stderr="")
        if command[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, stdout="image", stderr="")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({
                "status": "completed",
                "stdout": "ok",
                "stderr": "",
                "exit_code": 0,
                "timed_out": False,
                "output_limited": False,
            }),
            stderr="",
        )

    monkeypatch.setattr(execution.subprocess, "run", fake_run)
    result = execution.run_in_sandbox("javascript", "console.log('ok')", "execute")
    docker_command = calls[-1][0]
    assert result["stdout"] == "ok"
    assert docker_command[docker_command.index("--network") + 1] == "none"
    assert docker_command[docker_command.index("--read-only")] == "--read-only"
    assert docker_command[docker_command.index("--memory") + 1] == "256m"
    assert docker_command[docker_command.index("--pids-limit") + 1] == "64"
    assert docker_command[docker_command.index("--cap-drop") + 1] == "ALL"
    assert docker_command[docker_command.index("--user") + 1] == "10001:10001"

@pytest.mark.parametrize(
    ("language", "code", "expected_output"),
    [
        ("python", "print('Hello Python')", "Hello Python"),
        ("javascript", "console.log('Hello JavaScript')", "Hello JavaScript"),
        ("typescript", "const message: string = 'Hello TypeScript'; console.log(message);", "Hello TypeScript"),
        ("java", 'public class Main { public static void main(String[] args) { System.out.println("Hello Java"); } }', "Hello Java"),
        ("c", '#include <stdio.h>\nint main(void) { printf("Hello C\\n"); return 0; }', "Hello C"),
        ("cpp", '#include <iostream>\nint main() { std::cout << "Hello C++\\n"; return 0; }', "Hello C++"),
    ],
)
def test_live_sandbox_runs_each_supported_language(language, code, expected_output):
    status = execution.runner_status()
    if not status.get("available") or not status.get("image_available"):
        pytest.skip(status.get("message", "Isolated runner is unavailable."))
    if not status.get("languages", {}).get(language, {}).get("available"):
        pytest.skip(f"{language} toolchain is unavailable.")

    result = execution.run_in_sandbox(language, code, "execute", timeout_ms=10_000)

    assert result["status"] == "completed"
    assert expected_output in result["stdout"]
    assert result["exit_code"] == 0

def test_live_sandbox_hides_host_files_and_disables_network():
    status = execution.runner_status()
    if not status.get("available") or not status.get("image_available"):
        pytest.skip(status.get("message", "Isolated runner is unavailable."))

    result = execution.run_in_sandbox(
        "python",
        "import os; print(os.path.exists('/mnt/c'), os.path.exists('/root'), os.path.exists('/etc/shadow'))",
        "execute",
    )

    assert result["status"] == "completed"
    assert result["stdout"].strip() == "False False False"

def test_live_sandbox_denies_network_access():
    status = execution.runner_status()
    if not status.get("available") or not status.get("image_available"):
        pytest.skip(status.get("message", "Isolated runner is unavailable."))

    code = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 443), timeout=1)\n"
        "except OSError:\n"
        "    print('network blocked')\n"
        "else:\n"
        "    print('network available')\n"
    )
    result = execution.run_in_sandbox("python", code, "execute")

    assert result["status"] == "completed"
    assert result["stdout"].strip() == "network blocked"

def test_live_sandbox_passes_standard_input():
    status = execution.runner_status()
    if not status.get("available") or not status.get("image_available"):
        pytest.skip(status.get("message", "Isolated runner is unavailable."))

    result = execution.run_in_sandbox("python", "print(input())", "execute", stdin="sandbox input")

    assert result["status"] == "completed"
    assert result["stdout"].strip() == "sandbox input"

def test_live_sandbox_stops_timed_out_program():
    status = execution.runner_status()
    if not status.get("available") or not status.get("image_available"):
        pytest.skip(status.get("message", "Isolated runner is unavailable."))

    result = execution.run_in_sandbox("python", "while True: pass", "execute", timeout_ms=1000)

    assert result["status"] == "timed_out"
    assert result["timed_out"] is True

def test_live_sandbox_stops_excessive_output():
    status = execution.runner_status()
    if not status.get("available") or not status.get("image_available"):
        pytest.skip(status.get("message", "Isolated runner is unavailable."))

    result = execution.run_in_sandbox("python", "print('x' * 100000)", "execute")

    assert result["status"] == "output_limited"
    assert len(result["stdout"].encode("utf-8")) <= 65_536
    assert result["output_limited"] is True
