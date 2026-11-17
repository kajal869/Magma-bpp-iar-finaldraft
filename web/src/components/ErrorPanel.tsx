import type { AppError } from "../types";

interface Props {
  error: AppError;
  onReset: () => void;
}

export default function ErrorPanel({ error, onReset }: Props) {
  const unsupported = error.kind === "unsupported";
  return (
    <section className="card error-card shake">
      <div className="err-ico">{unsupported ? "i" : "!"}</div>
      <h2>{unsupported ? "This case isn't supported in the demo yet" : "Something went wrong"}</h2>
      <p className="muted">{error.message}</p>
      {error.kind === "unsupported" && (
        <div className="read-box">
          <h3>What we could read from the closing slip</h3>
          <div className="kv-grid">
            <span className="muted">Insured</span><strong>{error.summary.insured ?? "-"}</strong>
            <span className="muted">GSTIN</span><strong>{error.summary.gstin ?? "-"}</strong>
            <span className="muted">Product</span><strong>{error.summary.product ?? "-"}</strong>
            <span className="muted">Period</span><strong>{error.summary.periodStart && error.summary.periodEnd ? `${error.summary.periodStart} to ${error.summary.periodEnd}` : "-"}</strong>
            <span className="muted">Intermediary</span><strong>{error.summary.intermediary ?? "-"}</strong>
            <span className="muted">Office</span><strong>{error.summary.office ?? "-"}</strong>
          </div>
        </div>
      )}
      <button className="btn btn-primary" onClick={onReset}>Try other files</button>
    </section>
  );
}
