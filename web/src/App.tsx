import { useCallback, useRef, useState } from "react";
import { ApiError, analyze, discard, renderDraft } from "./api";
import ErrorPanel from "./components/ErrorPanel";
import Header from "./components/Header";
import Loader, { BUILD_STEPS, READ_STEPS } from "./components/Loader";
import Result from "./components/Result";
import Review from "./components/Review";
import UploadCard from "./components/UploadCard";
import type { AnalyzeResult, AppError, Edits, GenerateResult } from "./types";

type Phase = "idle" | "analyzing" | "review" | "rendering" | "done" | "error";
const toError = (e: unknown): AppError => (e instanceof ApiError ? e.detail : { kind: "error", message: "Unexpected error. Please try again." });

export default function App() {
  const [slip, setSlip] = useState<File | null>(null);
  const [quote, setQuote] = useState<File | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [serverDone, setServerDone] = useState(false);
  const [analysis, setAnalysis] = useState<AnalyzeResult | null>(null);
  const [result, setResult] = useState<GenerateResult | null>(null);
  const [error, setError] = useState<AppError | null>(null);
  const pending = useRef<{ analysis?: AnalyzeResult; result?: GenerateResult; error?: AppError }>({});

  async function start() {
    if (!slip || !quote) return;
    pending.current = {};
    setServerDone(false);
    setPhase("analyzing");
    try {
      pending.current.analysis = await analyze(slip, quote);
    } catch (e) {
      pending.current.error = toError(e);
    }
    setServerDone(true);
  }

  async function generate(values: Record<string, string>, allowBlanks: boolean, edits: Edits) {
    if (!analysis) return;
    if (result) discard(result.token);
    pending.current = {};
    setServerDone(false);
    setPhase("rendering");
    try {
      pending.current.result = await renderDraft(analysis.sessionId, values, allowBlanks, edits);
    } catch (e) {
      pending.current.error = toError(e);
    }
    setServerDone(true);
  }

  // called by the loader after its last animated step
  const finishAnalyze = useCallback(() => {
    const { analysis: a, error: e } = pending.current;
    if (a) {
      setAnalysis(a);
      setPhase("review");
    } else {
      setError(e ?? { kind: "error", message: "Unexpected error." });
      setPhase("error");
    }
  }, []);

  const finishRender = useCallback(() => {
    const { result: r, error: e } = pending.current;
    if (r) {
      setResult(r);
      setPhase("done");
    } else {
      setError(e ?? { kind: "error", message: "Unexpected error." });
      setPhase("error");
    }
  }, []);

  function reset() {
    if (result) discard(result.token);
    setResult(null);
    setAnalysis(null);
    setError(null);
    setSlip(null);
    setQuote(null);
    setPhase("idle");
  }

  function backToReview() {
    if (result) discard(result.token);
    setResult(null);
    setPhase("review");
  }

  const busy = phase === "analyzing";

  return (
    <div className="shell">
      <Header />
      <main className={`stage stage-${phase}`}>
        {(phase === "idle" || phase === "analyzing") && (
          <section className="intro">
            <div className="hero fade-up">
              <span className="pill">Business Protect Policy</span>
              <h1>From closing slip and quote to a <em>policy front pack</em> in seconds.</h1>
              <p className="muted lead">Upload the two Excel files. We read them, show you which mandatory fields were captured and which are missing, and give you the schedule, premium summary, GST block and annexures as a PDF.</p>
            </div>

            <div className="uploads fade-up" style={{ animationDelay: "120ms" }}>
              <UploadCard step={1} title="Closing slip" hint="Magma closing slip workbook" file={slip} onFile={setSlip} disabled={busy} />
              <UploadCard step={2} title="Broker quote" hint="Quote workbook from the broker or underwriter" file={quote} onFile={setQuote} disabled={busy} />
            </div>

            <div className="cta fade-up" style={{ animationDelay: "220ms" }}>
              <button className="btn btn-primary btn-lg" disabled={!slip || !quote || busy} onClick={start}>
                Read the files
                <svg viewBox="0 0 24 24" className="btn-ico"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
              </button>
              <p className="muted small">Nothing is saved. Files are removed as soon as they have been read.</p>
            </div>
          </section>
        )}

        {phase === "review" && analysis && <Review data={analysis} onBack={reset} onGenerate={generate} />}
        {phase === "done" && result && <Result result={result} onReset={reset} onBack={backToReview} />}
        {phase === "error" && error && <ErrorPanel error={error} onReset={reset} />}
      </main>
      {phase === "analyzing" && <Loader key="a" title="Reading your files" steps={READ_STEPS} ready={serverDone} onDone={finishAnalyze} />}
      {phase === "rendering" && <Loader key="r" title="Drafting your front pack" steps={BUILD_STEPS} ready={serverDone} onDone={finishRender} />}
      <footer className="foot muted small">Magma General Insurance · Internal demo · Not for customer use</footer>
    </div>
  );
}
