import ast
import json
import functools
import os
import resource
import re
import selectors
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SOURCE_FILES = {
    "python": "main.py",
    "javascript": "main.js",
    "typescript": "main.ts",
    "java": "Main.java",
    "c": "main.c",
    "cpp": "main.cpp",
}
MAX_OUTPUT_BYTES = 65_536


def _tool(name: str) -> str:
    executable = shutil.which(name)
    return os.path.realpath(executable) if executable else name


def _set_process_limits(address_space_limit: int) -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (15, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024 * 1024, 4 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if hasattr(resource, "RLIMIT_NPROC"):
        resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
    if hasattr(resource, "RLIMIT_AS"):
        resource.setrlimit(resource.RLIMIT_AS, (address_space_limit, address_space_limit))


def _run_command(command: list[str], stdin: str, deadline: float) -> dict[str, Any]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return {"status": "timed_out", "stdout": "", "stderr": "Execution timed out.", "exit_code": None, "timed_out": True, "output_limited": False}
    executable = os.path.basename(command[0])
    address_space_limit = (
        8 * 1024 * 1024 * 1024 if executable == "node"
        else 4 * 1024 * 1024 * 1024 if executable in {"java", "javac"}
        else 768 * 1024 * 1024
    )
    try:
        process = subprocess.Popen(
            command,
            cwd="/workspace",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            preexec_fn=functools.partial(_set_process_limits, address_space_limit),
            env={"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "HOME": "/tmp", "TMPDIR": "/tmp"},
        )
    except OSError as error:
        return {"status": "compile_error", "stdout": "", "stderr": str(error), "exit_code": None, "timed_out": False, "output_limited": False}

    selector = selectors.DefaultSelector()
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    os.set_blocking(process.stdin.fileno(), False)
    os.set_blocking(process.stdout.fileno(), False)
    os.set_blocking(process.stderr.fileno(), False)
    stdin_fd = process.stdin.fileno()
    stdout_fd = process.stdout.fileno()
    stderr_fd = process.stderr.fileno()
    selector.register(stdin_fd, selectors.EVENT_WRITE, "stdin")
    selector.register(stdout_fd, selectors.EVENT_READ, "stdout")
    selector.register(stderr_fd, selectors.EVENT_READ, "stderr")
    pending_input = memoryview(stdin.encode("utf-8"))
    stdin_open = True
    if not pending_input:
        selector.unregister(stdin_fd)
        process.stdin.close()
        stdin_open = False
    captured = {"stdout": bytearray(), "stderr": bytearray()}
    output_limited = False
    timed_out = False
    total_output = 0
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            if process.poll() is not None and stdin_open:
                selector.unregister(stdin_fd)
                process.stdin.close()
                stdin_open = False
            for key, _ in selector.select(min(remaining, 0.1)):
                if key.data == "stdin":
                    try:
                        written = os.write(stdin_fd, pending_input[:8192])
                    except (BrokenPipeError, ConnectionResetError):
                        written = len(pending_input)
                    pending_input = pending_input[written:]
                    if not pending_input:
                        selector.unregister(stdin_fd)
                        process.stdin.close()
                        stdin_open = False
                else:
                    try:
                        chunk = os.read(key.fileobj, 8192)
                    except OSError:
                        chunk = b""
                    if not chunk:
                        selector.unregister(key.fileobj)
                        (process.stdout if key.data == "stdout" else process.stderr).close()
                        continue
                    total_output += len(chunk)
                    allowance = MAX_OUTPUT_BYTES - len(captured[key.data])
                    if allowance > 0:
                        captured[key.data].extend(chunk[:allowance])
                    if total_output > MAX_OUTPUT_BYTES:
                        output_limited = True
                        break
            if output_limited:
                break
    finally:
        selector.close()

    if timed_out or output_limited:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()

    stdout = captured["stdout"].decode("utf-8", errors="replace")
    stderr = captured["stderr"].decode("utf-8", errors="replace")
    if output_limited:
        stderr += "\nOutput limit reached; the process was stopped."
    if timed_out:
        stderr += "\nExecution timed out."
    status = "timed_out" if timed_out else "output_limited" if output_limited else "completed" if process.returncode == 0 else "runtime_error"
    return {
        "status": status,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "output_limited": output_limited,
    }


def _command(language: str, action: str) -> tuple[list[list[str]], bool]:
    source = f"/workspace/{SOURCE_FILES[language]}"
    if action == "analyze":
        if language == "python":
            return [[sys.executable, "-c", f"compile(open({source!r}, encoding='utf-8').read(), {source!r}, 'exec')"]], False
        if language == "javascript":
            return [[_tool("node"), "--max-old-space-size=256", "--max-semi-space-size=4", "--check", source]], False
        if language == "typescript":
            return [[_tool("node"), "--max-old-space-size=256", "--max-semi-space-size=4", _tool("tsc"), "--noEmit", "--target", "ES2022", "--module", "commonjs", "--skipLibCheck", source]], False
        if language == "java":
            return [[_tool("javac"), "-J-Xmx128m", "-J-XX:ReservedCodeCacheSize=32m", "-J-XX:MaxMetaspaceSize=96m", "-J-XX:CompressedClassSpaceSize=64m", "-J-Xss512k", "-d", "/tmp", source]], False
        if language == "c":
            return [[_tool("gcc"), "-fsyntax-only", "-std=c11", source]], False
        return [[_tool("g++"), "-fsyntax-only", "-std=c++17", source]], False
    if language == "python":
        return [
            [sys.executable, "-c", f"compile(open({source!r}, encoding='utf-8').read(), {source!r}, 'exec')"],
            [sys.executable, source],
        ], True
    if language == "javascript":
        return [[_tool("node"), "--max-old-space-size=256", "--max-semi-space-size=4", "--check", source], [_tool("node"), "--max-old-space-size=256", "--max-semi-space-size=4", source]], True
    if language == "typescript":
        return [
            [_tool("node"), "--max-old-space-size=256", "--max-semi-space-size=4", _tool("tsc"), "--noEmit", "--target", "ES2022", "--module", "commonjs", "--skipLibCheck", source],
            [_tool("node"), "--max-old-space-size=256", "--max-semi-space-size=4", _tool("tsc"), "--target", "ES2022", "--module", "commonjs", "--skipLibCheck", "--outDir", "/tmp/ts-out", source],
            [_tool("node"), "--max-old-space-size=256", "--max-semi-space-size=4", "/tmp/ts-out/main.js"],
        ], True
    if language == "java":
        return [
            [_tool("javac"), "-J-Xmx128m", "-J-XX:ReservedCodeCacheSize=32m", "-J-XX:MaxMetaspaceSize=96m", "-J-XX:CompressedClassSpaceSize=64m", "-J-Xss512k", "-d", "/tmp", source],
            [_tool("java"), "-Xmx128m", "-XX:ReservedCodeCacheSize=32m", "-XX:MaxMetaspaceSize=96m", "-XX:CompressedClassSpaceSize=64m", "-Xss512k", "-cp", "/tmp", "Main"],
        ], True
    if language == "c":
        return [["gcc", "-O0", "-std=c11", "-o", "/tmp/main", source], ["/tmp/main"]], True
    return [["g++", "-O0", "-std=c++17", "-o", "/tmp/main", source], ["/tmp/main"]], True


def handle(request: dict[str, Any]) -> dict[str, Any]:
    language = request.get("language")
    action = request.get("action")
    if language not in SOURCE_FILES or action not in {"analyze", "execute"}:
        return {"status": "error", "stdout": "", "stderr": "Unsupported language or action.", "exit_code": None, "timed_out": False, "output_limited": False}
    source = Path("/workspace", SOURCE_FILES[language])
    try:
        code = source.read_text(encoding="utf-8")
        if language == "python":
            compile(code, str(source), "exec")
    except SyntaxError as error:
        return {"status": "compile_error", "stdout": "", "stderr": f"Line {error.lineno}, column {error.offset}: {error.msg}", "exit_code": 1, "timed_out": False, "output_limited": False}
    except (OSError, UnicodeDecodeError) as error:
        return {"status": "error", "stdout": "", "stderr": str(error), "exit_code": 1, "timed_out": False, "output_limited": False}

    commands, execute = _command(language, action)
    if execute and language == "java":
        package = re.search(r"^\s*package\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;", code, re.MULTILINE)
        if package is not None:
            commands[-1] = [_tool("java"), "-Xmx128m", "-XX:ReservedCodeCacheSize=32m", "-XX:MaxMetaspaceSize=96m", "-Xss1m", "-cp", "/tmp", f"{package.group(1)}.Main"]
    deadline = time.monotonic() + max(100, min(int(request.get("timeout_ms", 5000)), 10_000)) / 1000
    combined_stdout = ""
    combined_stderr = ""
    last_result: dict[str, Any] = {}
    for index, command in enumerate(commands):
        run_stdin = request.get("stdin", "") if execute and index == len(commands) - 1 else ""
        last_result = _run_command(command, run_stdin, deadline)
        combined_stdout += last_result["stdout"]
        combined_stderr += last_result["stderr"]
        if last_result["status"] != "completed":
            if action == "analyze" and last_result["status"] == "runtime_error":
                last_result["status"] = "compile_error"
            elif execute and index < len(commands) - 1:
                last_result["status"] = "compile_error"
            last_result["stdout"] = combined_stdout[:MAX_OUTPUT_BYTES]
            last_result["stderr"] = combined_stderr[:MAX_OUTPUT_BYTES]
            return last_result

    last_result["status"] = "completed" if execute else "success"
    last_result["stdout"] = combined_stdout[:MAX_OUTPUT_BYTES]
    last_result["stderr"] = combined_stderr[:MAX_OUTPUT_BYTES]
    if action == "analyze":
        last_result.update(exit_code=0, timed_out=False, output_limited=False)
    return last_result


if __name__ == "__main__":
    try:
        payload = json.load(sys.stdin)
        result = handle(payload)
    except Exception as error:
        result = {"status": "error", "stdout": "", "stderr": f"Worker error: {error}", "exit_code": None, "timed_out": False, "output_limited": False}
    sys.stdout.write(json.dumps(result, ensure_ascii=True))
