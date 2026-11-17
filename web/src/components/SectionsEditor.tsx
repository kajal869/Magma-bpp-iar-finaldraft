import type { SectionRow } from "../types";

interface Props {
  rows: SectionRow[];
  onChange: (rows: SectionRow[]) => void;
}

const num = (v: string): number | null => (v.trim() === "" ? null : Number.isFinite(Number(v)) ? Number(v) : null);
const fmt = (v: number | null) => (v === null ? "" : String(v));

/** A section is "captured" if the extractor was sure, or if the user has edited it; otherwise it needs a look. */
export function sectionState(s: SectionRow): "ok" | "check" | "off" {
  if (!s.opted) return "off";
  return s.touched || s.status === "ok" || s.status === "derived" ? "ok" : "check";
}

export default function SectionsEditor({ rows, onChange }: Props) {
  const patch = (no: number, p: Partial<SectionRow>) => onChange(rows.map((r) => (r.no === no ? { ...r, ...p, touched: true, opted: true } : r)));
  const opted = rows.filter((r) => r.opted);
  const others = rows.filter((r) => !r.opted);
  const total = opted.reduce((a, r) => a + (r.premium ?? 0) + r.subRows.reduce((b, x) => b + (x.premium ?? 0), 0), 0);

  const line = (r: SectionRow) => {
    const st = sectionState(r);
    return (
      <div className={`srow st-${st}`} key={r.no}>
        <div className="s-name">
          <strong>Section {r.no}</strong> <span>{r.label}</span>
          {st !== "off" && <span className={`badge b-${st}`}>{st === "ok" ? "Captured" : "Check"}</span>}
        </div>
        <label>Sum insured (₹)<input type="number" step="any" value={fmt(r.sumInsured)} onChange={(e) => patch(r.no, { sumInsured: num(e.target.value) })} /></label>
        <label>Premium (₹)<input type="number" step="any" value={fmt(r.premium)} onChange={(e) => patch(r.no, { premium: num(e.target.value) })} /></label>
        {r.note && st === "check" && <div className="note-amber s-note">{r.note}</div>}
        {r.subRows.map((x) => (
          <div className="s-sub muted small" key={x.label}>{x.label}: {x.sum_insured?.toLocaleString("en-IN") ?? "-"} · premium {x.premium?.toLocaleString("en-IN") ?? "-"}</div>
        ))}
      </div>
    );
  };

  return (
    <div className="card group fade-up">
      <h3>Coverages and sections</h3>
      <p className="muted small">Sum insured and premium for each opted section. Enter a value in a section below to opt it in. Section premiums total ₹ {total.toLocaleString("en-IN", { maximumFractionDigits: 2 })}.</p>
      {opted.length === 0 && <p className="muted empty">No section was read from the quote.</p>}
      {opted.map(line)}
      {others.length > 0 && (
        <details className="more-secs">
          <summary>Other sections ({others.length})</summary>
          {others.map(line)}
        </details>
      )}
    </div>
  );
}
