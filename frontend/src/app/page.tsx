"use client";

import { useCallback, useEffect, useState } from "react";

type Diagnostic = {
  id: string;
  category: string;
  severity: string;
  message: string;
  line: number | null;
  column: number | null;
};

type AnalysisResult = {
  status: string;
  diagnostics: Diagnostic[];
};

type GuidedDebugging = {
  summary: string;
  steps: { title: string; instruction: string; diagnostic_id: string | null }[];
  limitations: string[];
};

type RepairResult = {
  proposed_code: string | null;
  explanation: string;
  validation_status: "validated" | "unverified" | "not_available";
  validation_checks: string[];
  remaining_issues: string[];
};

type LanguageOption = {
  id: string;
  name: string;
  analysis_available: boolean;
  execution_available: boolean;
};

type LanguageStatus = {
  runner: { available: boolean; image_available: boolean; message: string };
  languages: LanguageOption[];
};

type ExecutionResult = {
  language: string;
  status: string;
  stdout: string;
  stderr: string;
  exit_code: number | null;
  timed_out: boolean;
  output_limited: boolean;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function postJson<T>(
  path: string,
  code: string,
  language: string,
  extra: Record<string, string | number> = {},
): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ language, code, ...extra }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail ?? `Request failed (${response.status})`);
  }
  return data as T;
}

export default function Home() {
  const [language, setLanguage] = useState("python");
  const [code, setCode] = useState("def foo():\n    print(undefined_variable)\n");
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);
  const [explanation, setExplanation] = useState("");
  const [hint, setHint] = useState("");
  const [hintLevel, setHintLevel] = useState(1);
  const [repair, setRepair] = useState<RepairResult | null>(null);
  const [guidedDebugging, setGuidedDebugging] = useState<GuidedDebugging | null>(null);
  const [debugStep, setDebugStep] = useState(0);
  const [error, setError] = useState("");
  const [busyAction, setBusyAction] = useState("");
  const [verification, setVerification] = useState<{
    status: string;
    passed_checks: string[];
    failed_checks: string[];
    unverified_conditions: string[];
  } | null>(null);
  const [stdin, setStdin] = useState("");
  const [execution, setExecution] = useState<ExecutionResult | null>(null);
  const [languageStatus, setLanguageStatus] = useState<LanguageStatus | null>(null);
  const selectedLanguage = languageStatus?.languages.find((item) => item.id === language);
  const analysisAvailable = selectedLanguage?.analysis_available ?? false;
  const executionAvailable = selectedLanguage?.execution_available ?? false;

  const refreshLanguageStatus = useCallback(async () => {
    const response = await fetch(`${API_URL}/api/v1/languages`);
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail ?? `Runner status request failed (${response.status})`);
    }
    setLanguageStatus(data as LanguageStatus);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void fetch(`${API_URL}/api/v1/languages`, { signal: controller.signal })
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.detail ?? `Runner status request failed (${response.status})`);
        }
        return data as LanguageStatus;
      })
      .then(setLanguageStatus)
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : "Could not load language availability.");
        }
      });
    return () => controller.abort();
  }, []);

  const runAction = async (action: string, callback: () => Promise<void>) => {
    setBusyAction(action);
    setError("");
    try {
      await callback();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The request failed.");
    } finally {
      setBusyAction("");
    }
  };

  const clearAssistance = () => {
    setExplanation("");
    setHint("");
    setHintLevel(1);
    setRepair(null);
    setGuidedDebugging(null);
    setDebugStep(0);
    setVerification(null);
    setExecution(null);
  };

  const handleAnalyze = () =>
    runAction("analyze", async () => {
      const result = await postJson<AnalysisResult>("/api/v1/analysis", code, language);
      setAnalysisResult(result);
      clearAssistance();
    });

  const handleExplain = () =>
    runAction("explain", async () => {
      const result = await postJson<{ explanation: string }>("/api/v1/analysis/explain", code, language);
      setExplanation(result.explanation);
    });

  const handleHint = () =>
    runAction("hint", async () => {
      const result = await postJson<{ hint: string; hint_level: number }>(
        `/api/v1/analysis/hints?level=${hintLevel}`,
        code,
        language,
      );
      setHint(result.hint);
      setHintLevel(result.hint_level + 1);
    });

  const handleRepair = () =>
    runAction("repair", async () => {
      const result = await postJson<RepairResult>("/api/v1/analysis/repair", code, language);
      setRepair(result);
    });

  const handleGuidedDebugging = () =>
    runAction("debug", async () => {
      const result = await postJson<GuidedDebugging>("/api/v1/analysis/debug", code, language);
      setGuidedDebugging(result);
      setDebugStep(0);
    });

  const handleVerify = () =>
    runAction("verify", async () => {
      const result = await postJson<{
        status: string;
        passed_checks: string[];
        failed_checks: string[];
        unverified_conditions: string[];
      }>("/api/v1/analysis/verify", code, language);
      setVerification(result);
    });

  const handleExecute = () =>
    runAction("execute", async () => {
      const result = await postJson<ExecutionResult>(
        "/api/v1/execute",
        code,
        language,
        { stdin, timeout_ms: 5000 },
      );
      setExecution(result);
    });

  return (
    <main className="assistant-page min-h-screen px-4 py-8 font-sans sm:px-8 sm:py-12">
      <div className="assistant-page-content mx-auto max-w-7xl">
      <header className="mb-8 flex flex-col gap-6 rounded-3xl border border-white/15 bg-white/10 p-6 shadow-2xl shadow-slate-950/20 backdrop-blur-xl sm:flex-row sm:items-center sm:justify-between sm:p-8">
        <div>
          <p className="mb-3 text-xs font-semibold uppercase tracking-[0.3em] text-cyan-200">Your learning workspace</p>
          <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">AI Coding Assistant</h1>
          <p className="mt-2 text-slate-300">Beginner-friendly debugging, one step at a time.</p>
        </div>
        <div className="w-full sm:max-w-xs">
          <label htmlFor="language-select" className="mb-2 block text-sm font-semibold text-white">
            Programming language
          </label>
          <select
            id="language-select"
            value={language}
            onChange={(event) => {
              const selectedLanguage = event.target.value;
              setLanguage(selectedLanguage);
              const starterCode: Record<string, string> = {
                python: "def foo():\n    print(undefined_variable)\n",
                javascript: "console.log('Hello, world!');\n",
                typescript: "const message: string = 'Hello, world!';\nconsole.log(message);\n",
                java: "public class Main {\n    public static void main(String[] args) {\n        System.out.println(\"Hello, world!\");\n    }\n}\n",
                c: "#include <stdio.h>\n\nint main(void) {\n    printf(\"Hello, world!\\\\n\");\n    return 0;\n}\n",
                cpp: "#include <iostream>\n\nint main() {\n    std::cout << \"Hello, world!\\\\n\";\n    return 0;\n}\n",
              };
              setCode(starterCode[selectedLanguage] ?? "");
              setExecution(null);
              setAnalysisResult(null);
              clearAssistance();
            }}
            className="w-full rounded-xl border border-white/20 bg-slate-950/70 px-4 py-3 text-white shadow-lg outline-none transition focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/40"
          >
            {[
              ["python", "Python"],
              ["javascript", "JavaScript"],
              ["typescript", "TypeScript"],
              ["java", "Java"],
              ["c", "C"],
              ["cpp", "C++"],
            ].map(([id, name]) => {
              const availability = languageStatus?.languages.find((item) => item.id === id);
              const label = availability?.analysis_available
                ? availability.execution_available ? "analysis & execution available" : "analysis available · runner setup needed"
                : languageStatus ? "runner setup needed" : "checking runner...";
              return <option key={id} value={id}>{name} — {label}</option>;
            })}
          </select>
          <p className="mt-2 text-xs text-slate-300">
            {languageStatus?.runner.message ?? "Checking isolated runner availability..."}
          </p>
          <button
            type="button"
            disabled={busyAction !== ""}
            onClick={() => void runAction("status", refreshLanguageStatus)}
            className="mt-2 text-sm font-medium text-cyan-200 underline decoration-cyan-400/60 underline-offset-4 hover:text-white disabled:opacity-50"
          >
            Refresh runner status
          </button>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
        <section className="rounded-3xl border border-white/60 bg-white/95 p-6 shadow-2xl shadow-slate-950/15 backdrop-blur sm:p-8">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h2 className="text-xl font-semibold text-gray-800">Code Workspace</h2>
            <span className={`rounded-full px-3 py-1 text-xs font-bold ${analysisAvailable ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-900"}`}>
              {analysisAvailable ? "ANALYSIS READY" : "RUNNER REQUIRED"}
            </span>
          </div>
          <textarea
            aria-label={`${language} source code`}
            placeholder={`Write or paste ${language} code here...`}
            className="h-80 w-full rounded-2xl border border-slate-700 bg-slate-950 p-4 font-mono text-sm text-slate-100 shadow-inner outline-none focus:ring-2 focus:ring-cyan-400"
            value={code}
            onChange={(event) => {
              setCode(event.target.value);
              setExecution(null);
              setAnalysisResult(null);
              setVerification(null);
              clearAssistance();
            }}
          />
          <button
            onClick={handleAnalyze}
            disabled={busyAction !== "" || !analysisAvailable}
            className="mt-4 rounded-xl bg-blue-600 px-6 py-3 font-semibold text-white shadow-lg shadow-blue-900/20 transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {!analysisAvailable ? "Runner setup required" : busyAction === "analyze" ? "Analyzing..." : "Analyze Code"}
          </button>
          {!analysisAvailable && (
            <p className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              {languageStatus?.runner.message ?? "Waiting for the isolated runner status."} Build and start the isolated runner to enable analysis and execution for this language.
            </p>
          )}
          <div className="mt-6 border-t border-slate-200 pt-5">
            <label htmlFor="program-input" className="mb-2 block text-sm font-semibold text-gray-800">
              Program input (stdin, optional)
            </label>
            <textarea
              id="program-input"
              value={stdin}
              onChange={(event) => setStdin(event.target.value)}
              placeholder="Text your program should read from standard input..."
              className="h-24 w-full rounded-xl border border-slate-300 bg-white p-3 font-mono text-sm text-slate-900 outline-none focus:ring-2 focus:ring-cyan-500"
            />
            <button
              onClick={handleExecute}
              disabled={busyAction !== "" || !executionAvailable}
              className="mt-3 rounded-xl bg-emerald-700 px-6 py-3 font-semibold text-white shadow-lg transition hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {!executionAvailable ? "Execution runner required" : busyAction === "execute" ? "Running in sandbox..." : "Run & Debug Code"}
            </button>
          </div>
          {error && (
            <p role="alert" className="mt-3 rounded border border-red-200 bg-red-50 p-3 text-red-700">
              {error}
            </p>
          )}
        </section>

        <section className="space-y-6">
          {analysisResult && (
            <div className="rounded-3xl border border-white/60 bg-white/95 p-6 shadow-xl shadow-slate-950/10 backdrop-blur">
              <h2 className="mb-4 text-xl font-semibold text-gray-800">Diagnostic Panel</h2>
              <p className="mb-4">
                Status:{" "}
                <span className={analysisResult.status === "success" ? "font-bold text-green-600" : "font-bold text-red-600"}>
                  {analysisResult.status.toUpperCase()}
                </span>
              </p>
              {analysisResult.diagnostics.length > 0 ? (
                <ul className="mb-4 space-y-3">
                  {analysisResult.diagnostics.map((diagnostic, index) => (
                    <li key={`${diagnostic.id}-${diagnostic.line}-${index}`} className="rounded border border-red-200 bg-red-50 p-3">
                      <strong className="text-red-700">[{diagnostic.category}]</strong> {diagnostic.message}
                      {diagnostic.line !== null && (
                        <span className="ml-2 text-sm text-red-600">(Line {diagnostic.line})</span>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mb-4 text-green-600">No issues detected by syntax parsing or static analysis.</p>
              )}

              <div className="mt-4 flex flex-wrap gap-2">
                <button disabled={busyAction !== ""} onClick={handleGuidedDebugging} className="rounded bg-sky-100 px-4 py-2 text-sky-800 hover:bg-sky-200 disabled:opacity-50">
                  {busyAction === "debug" ? "Preparing steps..." : "Guided Debugging"}
                </button>
                <button disabled={busyAction !== ""} onClick={handleExplain} className="rounded bg-indigo-100 px-4 py-2 text-indigo-700 hover:bg-indigo-200 disabled:opacity-50">
                  {busyAction === "explain" ? "Explaining..." : "Explain Issue"}
                </button>
                <button disabled={busyAction !== ""} onClick={handleHint} className="rounded bg-emerald-100 px-4 py-2 text-emerald-700 hover:bg-emerald-200 disabled:opacity-50">
                  {busyAction === "hint" ? "Getting hint..." : `Get Hint (Level ${hintLevel})`}
                </button>
                <button disabled={busyAction !== ""} onClick={handleRepair} className="rounded bg-amber-100 px-4 py-2 text-amber-800 hover:bg-amber-200 disabled:opacity-50">
                  {busyAction === "repair" ? "Preparing repair..." : "Propose Repair"}
                </button>
                <button disabled={busyAction !== ""} onClick={handleVerify} className="rounded bg-teal-100 px-4 py-2 text-teal-800 hover:bg-teal-200 disabled:opacity-50">
                  {busyAction === "verify" ? "Verifying..." : "Verify Code"}
                </button>
              </div>
            </div>
          )}

          {guidedDebugging && (
            <div className="rounded-3xl border border-sky-200 bg-white/95 p-6 shadow-xl shadow-slate-950/10 backdrop-blur">
              <h2 className="mb-2 text-lg font-semibold text-sky-900">Guided Debugging</h2>
              <p className="mb-4 text-gray-700">{guidedDebugging.summary}</p>
              <div aria-live="polite" className="rounded bg-sky-50 p-4">
                <p className="text-sm font-medium text-sky-900">
                  Step {debugStep + 1} of {guidedDebugging.steps.length}: {guidedDebugging.steps[debugStep].title}
                </p>
                <p className="mt-2 text-gray-700">{guidedDebugging.steps[debugStep].instruction}</p>
              </div>
              <div className="mt-4 flex gap-2">
                <button
                  disabled={debugStep === 0}
                  onClick={() => setDebugStep((step) => Math.max(0, step - 1))}
                  className="rounded border border-sky-300 px-4 py-2 text-sky-900 disabled:opacity-50"
                >
                  Previous
                </button>
                {debugStep < guidedDebugging.steps.length - 1 && (
                  <button
                    onClick={() => setDebugStep((step) => Math.min(guidedDebugging.steps.length - 1, step + 1))}
                    className="rounded bg-sky-700 px-4 py-2 text-white hover:bg-sky-800"
                  >
                    Next step
                  </button>
                )}
              </div>
              {guidedDebugging.limitations.map((limitation) => (
                <p key={limitation} className="mt-4 text-sm text-amber-800">{limitation}</p>
              ))}
            </div>
          )}

          {explanation && (
            <div className="rounded-3xl border border-indigo-200 bg-white/95 p-6 shadow-xl shadow-slate-950/10 backdrop-blur">
              <h2 className="mb-2 text-lg font-semibold text-indigo-800">Explanation</h2>
              <p className="text-gray-700">{explanation}</p>
            </div>
          )}

          {hint && (
            <div className="rounded-3xl border border-emerald-200 bg-white/95 p-6 shadow-xl shadow-slate-950/10 backdrop-blur">
              <h2 className="mb-2 text-lg font-semibold text-emerald-800">Hint (Level {hintLevel - 1})</h2>
              <p className="text-gray-700">{hint}</p>
            </div>
          )}

          {repair && (
            <div className="rounded-3xl border border-amber-200 bg-white/95 p-6 shadow-xl shadow-slate-950/10 backdrop-blur">
              <h2 className="mb-2 text-lg font-semibold text-amber-900">Proposed Repair</h2>
              <p className="mb-3 text-gray-700">{repair.explanation}</p>
              <p className="mb-3 text-sm">
                Validation: <strong>{repair.validation_status.replaceAll("_", " ")}</strong>
              </p>
              {repair.proposed_code !== null && (
                <>
                  <pre className="overflow-auto rounded bg-gray-900 p-4 font-mono text-sm text-gray-100">
                    {repair.proposed_code}
                  </pre>
                  <button
                    onClick={() => {
                      setCode(repair.proposed_code ?? "");
                      setAnalysisResult(null);
                      setVerification(null);
                      clearAssistance();
                    }}
                    className="mt-3 rounded bg-amber-700 px-4 py-2 text-white hover:bg-amber-800"
                  >
                    Use Proposed Code
                  </button>
                </>
              )}
              {repair.validation_checks.length > 0 && (
                <p className="mt-3 text-sm text-gray-600">Checks run: {repair.validation_checks.join(", ")}</p>
              )}
              {repair.remaining_issues.length > 0 && (
                <div className="mt-3">
                  <p className="font-medium text-red-700">Remaining issues or blockers:</p>
                  <ul className="list-disc pl-5 text-sm text-red-700">
                    {repair.remaining_issues.map((issue) => <li key={issue}>{issue}</li>)}
                  </ul>
                </div>
              )}
            </div>
          )}

          {verification && (
            <div className="rounded-3xl border border-teal-200 bg-white/95 p-6 shadow-xl shadow-slate-950/10 backdrop-blur">
              <h2 className="mb-2 text-lg font-semibold text-teal-900">Verification Report</h2>
              <p className="mb-2 font-medium text-gray-700">Status: {verification.status.toUpperCase()}</p>
              <p><strong>Passed checks:</strong> {verification.passed_checks.join(", ") || "None"}</p>
              {verification.failed_checks.length > 0 && (
                <p className="text-red-700"><strong>Failed checks:</strong> {verification.failed_checks.join(", ")}</p>
              )}
              <p className="mt-2 text-amber-800"><strong>Not verified:</strong> {verification.unverified_conditions.join("; ")}</p>
            </div>
          )}
          {execution && (
            <div className="rounded-3xl border border-emerald-200 bg-white/95 p-6 shadow-xl shadow-slate-950/10 backdrop-blur">
              <h2 className="mb-2 text-lg font-semibold text-emerald-900">Sandbox Execution</h2>
              <p className="mb-3 text-gray-700">
                Status: <strong>{execution.status.replaceAll("_", " ").toUpperCase()}</strong>
                {execution.exit_code !== null && ` · exit code ${execution.exit_code}`}
              </p>
              {execution.stdout && (
                <>
                  <h3 className="mb-1 text-sm font-semibold text-gray-700">Standard output</h3>
                  <pre className="mb-3 overflow-auto rounded-xl bg-slate-950 p-4 font-mono text-sm text-emerald-200">{execution.stdout}</pre>
                </>
              )}
              {execution.stderr && (
                <>
                  <h3 className="mb-1 text-sm font-semibold text-gray-700">Errors / diagnostics</h3>
                  <pre className="overflow-auto rounded-xl bg-slate-950 p-4 font-mono text-sm text-rose-200">{execution.stderr}</pre>
                </>
              )}
              {execution.timed_out && <p className="mt-3 text-amber-800">Stopped after the execution time limit.</p>}
              {execution.output_limited && <p className="mt-3 text-amber-800">Stopped after reaching the output limit.</p>}
            </div>
          )}
        </section>
      </div>
      </div>
    </main>
  );
}
