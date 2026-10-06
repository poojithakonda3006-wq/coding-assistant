import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

os.environ["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

LANGUAGE_TOOLS = {
    "python": ("python3",),
    "javascript": ("node",),
    "typescript": ("node", "tsc"),
    "java": ("java", "javac"),
    "c": ("gcc",),
    "cpp": ("g++",),
}
SOURCE_FILES = {
    "python": "main.py",
    "javascript": "main.js",
    "typescript": "main.ts",
    "java": "Main.java",
    "c": "main.c",
    "cpp": "main.cpp",
}
MAX_CODE_BYTES = 65_536
MAX_STDIN_BYTES = 16_384
MAX_TIMEOUT_MS = 10_000
RUNNER_WORKER = Path(__file__).with_name("worker.py")


def status() -> dict[str, Any]:
    missing = []
    if shutil.which("bwrap") is None:
        missing.append("bubblewrap")
    if not RUNNER_WORKER.is_file():
        missing.append("runner worker")
    languages = {}
    for language, tools in LANGUAGE_TOOLS.items():
        absent = [tool for tool in tools if shutil.which(tool) is None]
        languages[language] = {"available": not absent, "missing_tools": absent}
        if absent:
            missing.extend(absent)
    if missing:
        unique_missing = list(dict.fromkeys(missing))
        sandbox_ready = shutil.which("bwrap") is not None and RUNNER_WORKER.is_file()
        return {
            "available": sandbox_ready,
            "image_available": sandbox_ready,
            "message": (
                f"WSL sandbox ready; some language tools are missing: {', '.join(unique_missing)}."
                if sandbox_ready
                else f"WSL runner setup incomplete; missing: {', '.join(unique_missing)}."
            ),
            "languages": languages,
        }
    return {
        "available": True,
        "image_available": True,
        "message": "WSL bubblewrap sandbox and all language toolchains are ready.",
        "languages": languages,
    }


def run(request: dict[str, Any]) -> dict[str, Any]:
    language = request.get("language")
    action = request.get("action")
    code = request.get("code")
    stdin = request.get("stdin", "")
    timeout_ms = request.get("timeout_ms", 5000)
    if language not in SOURCE_FILES or action not in {"analyze", "execute"}:
        raise ValueError("Unsupported language or action.")
    if not isinstance(code, str) or not isinstance(stdin, str):
        raise ValueError("Code and standard input must be text.")
    if len(code.encode("utf-8")) > MAX_CODE_BYTES:
        raise ValueError(f"Code exceeds the {MAX_CODE_BYTES}-byte input limit.")
    if len(stdin.encode("utf-8")) > MAX_STDIN_BYTES:
        raise ValueError(f"Standard input exceeds the {MAX_STDIN_BYTES}-byte input limit.")
    if not isinstance(timeout_ms, int) or not 100 <= timeout_ms <= MAX_TIMEOUT_MS:
        raise ValueError(f"timeout_ms must be between 100 and {MAX_TIMEOUT_MS}.")

    ready = status()
    if not ready["available"] or not ready["image_available"]:
        raise RuntimeError(ready["message"])

    with tempfile.TemporaryDirectory(prefix="ai-code-") as temporary_directory:
        staging = Path(temporary_directory)
        source = staging / SOURCE_FILES[language]
        source.write_text(code, encoding="utf-8")
        source.chmod(0o444)
        sandbox_worker = staging / "worker.py"
        shutil.copyfile(RUNNER_WORKER, sandbox_worker)
        sandbox_worker.chmod(0o444)

        passwd = staging / "passwd"
        passwd.write_text("sandbox:x:65534:65534:Sandbox:/tmp:/usr/sbin/nologin\n", encoding="utf-8")
        passwd.chmod(0o444)
        group = staging / "group"
        group.write_text("sandbox:x:65534:\n", encoding="utf-8")
        group.chmod(0o444)
        nsswitch = staging / "nsswitch.conf"
        nsswitch.write_text("passwd: files\ngroup: files\nhosts: files\n", encoding="utf-8")
        nsswitch.chmod(0o444)
        alternatives = staging / "alternatives"
        if Path("/etc/alternatives").is_dir():
            shutil.copytree("/etc/alternatives", alternatives, symlinks=True)

        bwrap = [
            "bwrap",
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--ro-bind", "/usr", "/usr",
            "--symlink", "usr/bin", "/bin",
            "--symlink", "usr/sbin", "/sbin",
            "--symlink", "usr/lib", "/lib",
            "--symlink", "usr/lib64", "/lib64",
            "--proc", "/proc",
            "--dev", "/dev",
            "--size", "67108864",
            "--tmpfs", "/tmp",
            "--dir", "/etc",
            "--ro-bind", str(passwd), "/etc/passwd",
            "--ro-bind", str(group), "/etc/group",
            "--ro-bind", str(nsswitch), "/etc/nsswitch.conf",
            *(["--ro-bind", str(alternatives), "/etc/alternatives"] if alternatives.exists() else []),
            "--dir", "/workspace",
            "--ro-bind", str(source), f"/workspace/{SOURCE_FILES[language]}",
            "--dir", "/runner",
            "--ro-bind", str(sandbox_worker), "/runner/worker.py",
            "--dir", "/scratch",
            "--chdir", "/workspace",
            "--uid", "65534",
            "--gid", "65534",
            "--clearenv",
            "--setenv", "HOME", "/tmp",
            "--setenv", "TMPDIR", "/tmp",
            "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin",
            "--setenv", "LANG", "C.UTF-8",
            "--",
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
                bwrap,
                input=payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=(timeout_ms / 1000) + 15,
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
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"bubblewrap exited with status {result.returncode}.")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError("The isolated WSL worker returned an invalid response.") from error


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--status"]:
            response = status()
        else:
            response = run(json.load(sys.stdin))
    except (OSError, RuntimeError, ValueError) as error:
        response = {"status": "error", "stdout": "", "stderr": str(error), "exit_code": None, "timed_out": False, "output_limited": False}
        print(json.dumps(response), file=sys.stderr)
        sys.exit(1)
    print(json.dumps(response))
