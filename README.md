# AI Coding Assistant

An educational coding workspace for analyzing, debugging, and running code in
an isolated sandbox. Supported languages are Python, JavaScript, TypeScript,
Java, C, and C++.

## Public project preview

The public interface preview will be available at
**[https://poojithakonda3006-wq.github.io/coding-assistant/](https://poojithakonda3006-wq.github.io/coding-assistant/)**.
GitHub Actions deploys it from `main` after GitHub Pages is enabled for this
repository. If the first deployment asks for Pages configuration, open the
repository's **Settings → Pages** and set the build source to **GitHub Actions**.
The public static preview lets visitors explore the interface, but does not
connect to a backend or execute code.

## Review locally

**[Open the app at http://localhost:3001](http://localhost:3001)**

This address works only on the computer where the frontend is running. It is
not a public website link; anyone reviewing the project on another device must
run the app locally or use a deployed URL.

On Windows, run `.\start-local.ps1` from PowerShell to start the frontend and
backend in the background and configure them to start automatically the next
time you sign in. The FastAPI backend runs at `http://127.0.0.1:8000`. See
[frontend/README.md](frontend/README.md) for WSL sandbox setup and runtime
details.

## Features

- Static analysis and beginner-friendly debugging workflows.
- Guided debugging, repair proposals, and verification.
- Code execution with standard input and bounded runtime/output.
- WSL2 Bubblewrap sandbox with network isolation.

## Repository

[View this project on GitHub](https://github.com/poojithakonda3006-wq/coding-assistant)
