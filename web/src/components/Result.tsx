import { pageUrl, pdfUrl } from "../api";
import type { GenerateResult } from "../types";

interface Props {
  result: GenerateResult;
  onReset: () => void;
  onBack: () => void;
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="kv-row">
      <span className="muted">{k}</span>
      <strong>{v}</strong>
    </div>
  );
}

export default function Result({ result, onReset, onBack }: Props) {
  const d = result.draft;
  return (
    <section className="result">
      <aside className="side">
        <div className="card fade-up" style={{ animationDelay: "0ms" }}>
          <div className="ready">
            <span className="ready-ico"><svg viewBox="0 0 20 20" className="tick"><path d="M4 10.5l4 4 8-9" /></svg></span>
            <div>
              <h2>Front pack ready</h2>
              <p className="muted">{result.pages} pages · PDF</p>
            </div>
          </div>
          <a className="btn btn-primary btn-block" href={pdfUrl(result.token, true)} download={result.fileName}>
            <svg viewBox="0 0 24 24" className="btn-ico"><path d="M12 4v11M7 10l5 5 5-5" /><path d="M4 19h16" /></svg>
            Download PDF
          </a>
          <button className="btn btn-ghost btn-block" onClick={onBack}>Edit fields</button>
          <button className="btn btn-ghost btn-block" onClick={onReset}>Start over</button>
        </div>

        <div className="card fade-up" style={{ animationDelay: "90ms" }}>
          <h3>Policy at a glance</h3>
          <Row k="Insured" v={d.insured} />
          <Row k="Policy no." v={d.policyNo} />
          <Row k="Product" v={d.product} />
          <Row k="Period" v={d.period} />
          <Row k="Net premium" v={`₹ ${d.netPremium}`} />
          <Row k={`Final premium (${d.tax})`} v={`₹ ${d.finalPremium}`} />
          <div className="chips">
            {d.sections.map((s) => <span className="chip" key={s}>{s}</span>)}
          </div>
        </div>

        {result.blanks.length > 0 && (
          <div className="card fade-up blank-card" style={{ animationDelay: "140ms" }}>
            <h3>Left blank in this PDF</h3>
            <ul>{result.blanks.map((b) => <li key={b.key}>{b.label}</li>)}</ul>
          </div>
        )}

        <div className="card fade-up note-card" style={{ animationDelay: "180ms" }}>
          <span className="pill pill-demo">Demo mode</span>
          <ul>
            {result.notes.map((n) => <li key={n}>{n}</li>)}
          </ul>
        </div>
      </aside>

      <div className="viewer fade-up" style={{ animationDelay: "120ms" }}>
        <div className="viewer-bar">
          <span className="dots"><i /><i /><i /></span>
          <span className="viewer-name" title={result.fileName}>{result.fileName}</span>
          <a className="open-link" href={pdfUrl(result.token)} target="_blank" rel="noreferrer">Open PDF</a>
        </div>
        <div className="pages">
          {Array.from({ length: result.pages }, (_, i) => (
            <figure key={i} className="page" style={{ animationDelay: `${Math.min(i, 6) * 70}ms` }}>
              <img src={pageUrl(result.token, i + 1)} alt={`Page ${i + 1} of ${result.pages}`} loading="lazy" />
              <figcaption>Page {i + 1} of {result.pages}</figcaption>
            </figure>
          ))}
        </div>
      </div>
    </section>
  );
}
