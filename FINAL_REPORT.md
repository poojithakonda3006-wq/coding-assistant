# COMPLETED
- Code submission (Python only).
- Multi-level error detection (Syntax via AST, Static Analysis via Pylint).
- Structured diagnostic report (Line numbers, Error codes).
- AI-assisted error explanation (with mock fallback).
- Progressive hints (with mock fallback).
- Code correction proposals (with mock fallback).
- Explicit repair verification limitations (Non-execution safe mode enabled).
- End-to-End Next.js UI integration.

# CHANGED
- Initialized Next.js 15+ App Router application in `/frontend`.
- Initialized FastAPI backend in `/backend`.
- Setup models and API routes for analysis, hints, repair, and verification.

# VERIFIED
- Frontend Type Checking & Build: PASS
- Backend Unit Tests (pytest): PASS
- Static Analysis test case detection: PASS
- Security constraints: Runtime Execution Isolated Worker explicitly documented as "Blocked due to security constraints" on verification endpoint.

# ARCHITECTURE
- **Frontend**: Next.js (TypeScript, React, Tailwind CSS)
- **Backend**: Python (FastAPI, Uvicorn, Pydantic)
- **Database/Persistence**: Skipped for Phase 1 as no user account/history requirement was mandated yet.
- **AI Provider**: OpenAI Python SDK wrapper configured (falls back safely if API Key is omitted).
- **Execution Worker**: Explicitly replaced with safe static-verification-only path to meet isolation constraints.

# SECURITY
- Untrusted user code is strictly passed to `ast.parse` and written to a secure temporary file purely for `pylint`.
- Subprocess for pylint captures output safely.
- No arbitrary remote command execution permitted.
- `OPENAI_API_KEY` expected from environment variables.

# REMAINING
- Persistent analysis session history (requires Supabase integration).
- True sandboxed execution worker (Docker/gVisor) for runtime tests.
- Support for secondary languages.

# GUIDED DEBUGGING AND REPAIR UPDATE
- Added a backend guided-debugging endpoint that creates actionable steps from current syntax/static-analysis findings and discloses that runtime behavior is not tested.
- Added a step-by-step frontend flow with Previous/Next navigation.
- Repair proposals now validate Python syntax and rerun Pylint; the UI reports the checks and unresolved findings, and only applies a proposal after the user selects **Use Proposed Code**.
- Without `OPENAI_API_KEY`, deterministic repair only handles uniquely identifiable misspelled names. For ambiguous cases it returns no fabricated code and explains that an AI provider must be configured.
- With `OPENAI_API_KEY`, repair proposals use OpenAI (default model `gpt-4o-mini`, configurable with `OPENAI_MODEL`) and are syntax-checked and statically analyzed before being shown.
- Neither guided debugging nor repair executes submitted code. Logical correctness and runtime behavior remain unverified without an isolated execution worker.

# MULTI-LANGUAGE ANALYSIS AND ISOLATED EXECUTION
- Added support paths for Python, JavaScript, TypeScript, Java, C, and C++.
- Python analysis uses the existing AST and Pylint path. Other languages use syntax/compiler checks in the language-runner container.
- Added a Docker runner image and setup script at `runner/`; submitted programs run with no network, a read-only root filesystem, a non-root user, dropped Linux capabilities, memory/CPU/process limits, a bounded deadline, and bounded stdout/stderr.
- Added execution support for stdin, runtime output/status, compilation failures, timeouts, and output-limit termination.
- The runtime reports actual Docker/image readiness per language. Without Docker Desktop running and the runner image built, execution and non-Python analysis remain unavailable; the UI must not mark them ready.
- Runtime sandbox behavior has not been certified until Docker Desktop/WSL2 and the image have been built and the integration tests have run on the target machine.

# WSL BUBBLEWRAP RUNNER ALTERNATIVE
- Added a Docker-free runner using Bubblewrap namespaces in the existing WSL2 Ubuntu distribution.
- `runner/setup-wsl.ps1` installs Bubblewrap, Python 3, Node.js, TypeScript, Java, and C/C++ compilers inside Ubuntu.
- WSL runner status is detected dynamically with Windows interop paths removed from the compiler search path; the frontend only enables each language after its toolchain and sandbox are available.
- Submitted code runs as UID/GID 65534 in isolated user/PID/mount/network/IPC/UTS namespaces. The sandbox exposes read-only source/compiler files only, has no network, uses a 64 MiB private temporary filesystem, and enforces process CPU/address-space/file/process/fd limits, a bounded wall-clock, and bounded output.
- Docker Desktop installation was blocked by the Windows administrator-approval prompt; this WSL alternative does not need Docker. Live code execution remains unavailable until WSL dependencies are installed and the sandbox backtest passes.

# COMMANDS
### Start Backend
```bash
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt # (Or run manual pip installs for fastapi uvicorn pydantic supabase openai httpx pytest pylint)
uvicorn main:app --reload --port 8000
```

### Run Backend Tests
```bash
cd backend
.\venv\Scripts\activate
pytest
```

### Start Frontend
```bash
cd frontend
npm install
npm run dev
```
