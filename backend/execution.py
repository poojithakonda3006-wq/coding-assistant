import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from models import SUPPORTED_LANGUAGES

RUNNER_IMAGE = os.environ.get("CODE_RUNNER_IMAGE", "ai-coding-assistant-runner:latest")
WORKER_PATH = Path(__file__).resolve().parent.parent / "runner" / "worker.py"
MAX_CODE_BYTES = 65_536
MAX_STDIN_BYTES = 16_384
MAX_OUTPUT_BYTES = 65_536
MAX_TIMEOUT_MS = 10_000

SOURCE_FILES = {
    "python": "main.py",
    "javascript": "main.js",
    "typescript": "main.ts",
    "java": "Main.java",
    "c": "main.c",
    "cpp": "main.cpp",
}


class RunnerUnavailable(RuntimeError):
    pass


def runner_status() -> dict[str, Any]:
    wsl_status = _wsl_runner_status()
    if wsl_status is not None and wsl_status["available"]:
        return wsl_status

    return _docker_runner_status() or wsl_status or {
        "available": False,
        "image_available": False,
        "message": "Neither the WSL sandbox nor Docker runner is available.",
        "languages": {},
    }


def _wsl_runner_status() -> dict[str, Any] | None:
    if shutil.which("wsl.exe") is None and os.name != "nt":
        return None
    try:
        worker_path = _wsl_path(WORKER_PATH.with_name("wsl_worker.py"))
        command = [
            "wsl.exe",
            "--distribution", os.environ.get("WSL_DISTRO", "Ubuntu"),
            "--user", "root",
            "--exec", "/usr/bin/env",
            "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "python3", worker_path, "--status",
        ]
        response = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired, RunnerUnavailable):
        return None
    if response.returncode != 0:
        return {
            "available": False,
            "image_available": False,
            "message": response.stderr.strip()[:500] or "WSL sandbox is not ready.",
            "languages": {},
        }
    try:
        status = json.loads(response.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(status, dict) or "available" not in status or "image_available" not in status:
        return None
    status["runner_type"] = "wsl-bubblewrap"
    return status


def _wsl_path(path: Path) -> str:
    try:
        result = subprocess.run(
            ["wsl.exe", "--distribution", os.environ.get("WSL_DISTRO", "Ubuntu"), "--user", "root", "--exec", "/usr/bin/wslpath", "-a", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RunnerUnavailable(f"Could not resolve the runner path inside WSL: {error}") from error
    if result.returncode != 0 or not result.stdout.strip():
        raise RunnerUnavailable(result.stderr.strip() or "Could not resolve the runner path inside WSL.")
    return result.stdout.strip()


def _docker_runner_status() -> dict[str, Any] | None:
    if shutil.which("docker") is None:
        return None

    try:
        daemon = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"available": False, "image_available": False, "message": "Docker daemon health check timed out.", "languages": {}}
    if daemon.returncode != 0:
        message = daemon.stderr.strip() or "Docker daemon is not running."
        return {"available": False, "image_available": False, "message": message[:500], "languages": {}}

    try:
        image = subprocess.run(
            ["docker", "image", "inspect", RUNNER_IMAGE],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"available": True, "image_available": False, "message": "Docker image check timed out.", "languages": {}}
    if image.returncode != 0:
        return {
            "available": True,
            "image_available": False,
            "message": f"Runner image {RUNNER_IMAGE} is not built yet.",
            "languages": {},
        }
    return {
        "available": True,
        "image_available": True,
        "message": "Docker isolated runner is ready.",
        "runner_type": "docker",
        "languages": {language: {"available": True, "missing_tools": []} for language in SUPPORTED_LANGUAGES},
    }


def run_in_sandbox(language: str, code: str, action: str, stdin: str = "", timeout_ms: int = 5000) -> dict[str, Any]:
    _validate_request(language, code, stdin, timeout_ms)
    status = runner_status()
    language_status = status.get("languages", {}).get(language, {})
    if not status["available"] or not status["image_available"] or not language_status.get("available", False):
        raise RunnerUnavailable(status["message"])
    if not WORKER_PATH.is_file():
        raise RunnerUnavailable(f"Isolated runner worker is missing: {WORKER_PATH}")

    try:
        code_bytes = code.encode("utf-8")
        stdin_bytes = stdin.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("Code and standard input must be valid UTF-8 text.") from error
    if len(code_bytes) > MAX_CODE_BYTES:
        raise ValueError(f"Code exceeds the {MAX_CODE_BYTES}-byte input limit.")
    if len(stdin_bytes) > MAX_STDIN_BYTES:
        raise ValueError(f"Standard input exceeds the {MAX_STDIN_BYTES}-byte input limit.")

    with tempfile.TemporaryDirectory(prefix="ai-code-") as source_dir:
        Path(source_dir, SOURCE_FILES[language]).write_bytes(code_bytes)
        if status.get("runner_type") == "wsl-bubblewrap":
            return _run_in_wsl(language, code, action, stdin, timeout_ms)

        container_name = f"ai-code-{uuid.uuid4().hex[:20]}"
        cid_file = Path(source_dir, "container.cid")
        command = [
            "docker", "run", "--rm",
            "--name", container_name,
            "--cidfile", str(cid_file),
            "--network", "none",
            "--memory", "256m",
            "--memory-swap", "256m",
            "--cpus", "0.5",
            "--pids-limit", "64",
            "--read-only",
            "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=32m,uid=10001,gid=10001,mode=1777",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true",
            "--user", "10001:10001",
            "--mount", f"type=bind,source={source_dir},target=/workspace,readonly",
            "--mount", f"type=bind,source={WORKER_PATH},target=/runner/worker.py,readonly",
            RUNNER_IMAGE,
            "python3", "/runner/worker.py",
        ]
        payload = json.dumps({
            "language": language,
            "action": action,
            "stdin": stdin,
            "timeout_ms": timeout_ms,
        })
        try:
            result = subprocess.run(
                command,
                input=payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=(timeout_ms / 1000) + 20,
                check=False,
            )
        except subprocess.TimeoutExpired:
            _stop_container(cid_file, container_name)
            return {
                "status": "timed_out",
                "stdout": "",
                "stderr": "The isolated runner did not respond before its deadline.",
                "exit_code": None,
                "timed_out": True,
                "output_limited": False,
            }
        except OSError as error:
            raise RunnerUnavailable(f"Could not start Docker runner: {error}") from error

        if result.returncode != 0:
            detail = result.stderr.strip() or f"Docker exited with status {result.returncode}."
            raise RunnerUnavailable(detail[:1000])
        try:
            response = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RunnerUnavailable("The isolated worker returned an invalid response.") from error
        return response


def _run_in_wsl(language: str, code: str, action: str, stdin: str, timeout_ms: int) -> dict[str, Any]:
    worker_path = _wsl_path(Path(__file__).resolve().parent.parent / "runner" / "wsl_worker.py")
    try:
        result = subprocess.run(
            [
                "wsl.exe",
                "--distribution", os.environ.get("WSL_DISTRO", "Ubuntu"),
                "--user", "root",
                "--exec", "/usr/bin/env",
                "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "python3", worker_path,
            ],
            input=json.dumps({
                "language": language,
                "code": code,
                "action": action,
                "stdin": stdin,
                "timeout_ms": timeout_ms,
            }),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=(timeout_ms / 1000) + 20,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "timed_out",
            "stdout": "",
            "stderr": "The isolated WSL runner exceeded its deadline.",
            "exit_code": None,
            "timed_out": True,
            "output_limited": False,
        }
    except OSError as error:
        raise RunnerUnavailable(f"Could not start the WSL sandbox: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or f"WSL sandbox exited with status {result.returncode}."
        raise RunnerUnavailable(detail[:1000])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RunnerUnavailable("The isolated WSL worker returned an invalid response.") from error


def _validate_request(language: str, code: str, stdin: str, timeout_ms: int) -> None:
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language. Choose one of: {', '.join(SUPPORTED_LANGUAGES)}.")
    if not isinstance(code, str) or not isinstance(stdin, str):
        raise ValueError("Code and standard input must be text.")
    if len(code.encode("utf-8")) > MAX_CODE_BYTES:
        raise ValueError(f"Code exceeds the {MAX_CODE_BYTES}-byte input limit.")
    if len(stdin.encode("utf-8")) > MAX_STDIN_BYTES:
        raise ValueError(f"Standard input exceeds the {MAX_STDIN_BYTES}-byte input limit.")
    if not isinstance(timeout_ms, int) or not 100 <= timeout_ms <= MAX_TIMEOUT_MS:
        raise ValueError(f"timeout_ms must be between 100 and {MAX_TIMEOUT_MS}.")


def _stop_container(cid_file: Path, container_name: str) -> None:
    container_id = cid_file.read_text(encoding="utf-8").strip() if cid_file.is_file() else container_name
    for command in (["docker", "kill", container_id], ["docker", "rm", "--force", container_id]):
        try:
            subprocess.run(command, capture_output=True, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
