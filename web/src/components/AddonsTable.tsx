import { useMemo, useState } from "react";
import type { AddonRow } from "../types";

interface Props {
  rows: AddonRow[];
  clauses: string[];
  onChange: (rows: AddonRow[]) => void;
}

type Filter = "all" | "check" | "kept" | "dropped";

export type RowState = "ok" | "check" | "missing" | "dropped";

/** Status the user sees: dropped, unresolved (red), still to check (amber) or fine (green). A row the user has edited counts as checked. */
export function stateOf(r: AddonRow): RowState {
  if (!r.include) return r.decision === "pending" && !r.touched ? "check" : "dropped"; // a pending remark is undecided, not dropped
  if (!r.clause && !r.printAsQuoted) return "missing";
  if (r.touched) return "ok";
  return r.status === "ok" ? "ok" : "check";
}

const LABEL: Record<RowState, string> = { ok: "Captured", check: "Check", missing: "Needs clause", dropped: "Dropped" };
const REASON: Record<string, string> = {
  pending_remark: "Insurer remark is still pending",
  no_remark_to_classify: "No insurer remark to classify",
  no_library_clause: "No library clause found",
  fuzzy_match: "Only a fuzzy match",
  ambiguous_title: "Ambiguous title",
  near_identical_title: "Near-identical library titles",
  conditional_cover: "Cover is conditional",
  variant_not_chosen: "Policy variant not chosen",
  low_confidence: "Low confidence",
};

export default function AddonsTable({ rows, clauses, onChange }: Props) {
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");

  const counts = useMemo(() => {
    const c = { all: rows.length, check: 0, kept: 0, dropped: 0 };
    rows.forEach((r) => {
      const s = stateOf(r);
      if (s === "dropped") c.dropped++;
      else c.kept++;
      if (s === "check" || s === "missing") c.check++;
    });
    return c;
  }, [rows]);

  const shown = rows.map((r, i) => ({ r, i })).filter(({ r }) => {
    const s = stateOf(r);
    if (filter === "check" && !(s === "check" || s === "missing")) return false;
    if (filter === "kept" && s === "dropped") return false;
    if (filter === "dropped" && s !== "dropped") return false;
    return !q.trim() || (r.name + " " + (r.clause ?? "") + " " + r.remark).toLowerCase().includes(q.trim().toLowerCase());
  });

  const patch = (i: number, p: Partial<AddonRow>) => onChange(rows.map((r, k) => (k === i ? { ...r, ...p, touched: true } : r)));
  const add = () => onChange([...rows, { id: null, sheet: "Added by you", row: 0, serial: null, name: "", limit: "", remark: "", decision: "keep", decisionClass: "user", include: true, clause: null, wordingId: null, method: null, confidence: 0, status: "missing", needsReview: [], nearIdentical: [], candidates: [], printAsQuoted: false, touched: true }]);
  const remove = (i: number) => onChange(rows.filter((_, k) => k !== i));

  return (
    <div className="card group fade-up addons">
      <div className="sec-head">
        <h3>Add-on covers</h3>
        <button className="btn btn-ghost btn-sm" onClick={add}>+ Add a cover</button>
      </div>
      <p className="muted small">Each row is a cover from the quote. Keep or drop it, and pick the library clause it prints as. A kept row needs a clause, or "print as quoted".</p>
      <div className="tabs">
        {([["all", "All", counts.all], ["check", "To check", counts.check], ["kept", "Kept", counts.kept], ["dropped", "Dropped", counts.dropped]] as [Filter, string, number][]).map(([k, label, n]) => (
          <button key={k} className={`tab${filter === k ? " on" : ""}`} onClick={() => setFilter(k)}>{label}<span>{n}</span></button>
        ))}
        <input className="tab-search" placeholder="Search covers" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search add-on covers" />
      </div>
      <datalist id="clause-titles">{clauses.map((c) => <option key={c} value={c} />)}</datalist>

      {rows.length === 0 && <p className="muted empty">No add-on table was recognised in the quote. Add covers by hand if the policy needs them.</p>}
      <div className="addon-list">
        {shown.map(({ r, i }) => {
          const s = stateOf(r);
          return (
            <div className={`arow st-${s === "dropped" ? "dropped" : s}`} key={`${r.sheet}-${r.row}-${i}`}>
              <div className="a-top">
                <label className="keep">
                  <input type="checkbox" checked={r.include} onChange={(e) => patch(i, { include: e.target.checked })} />
                  {r.include ? "Keep" : r.decision === "pending" && !r.touched ? "Undecided" : "Drop"}
                </label>
                <span className={`badge b-${s === "dropped" ? "off" : s}`}>{!r.include && r.decision === "pending" && !r.touched ? "Undecided" : LABEL[s]}</span>
                <span className="muted small">{r.sheet}{r.row ? ` · row ${r.row}` : ""}{r.method ? ` · ${r.method}` : ""}</span>
                {r.id === null && <button className="link" onClick={() => remove(i)}>Remove</button>}
              </div>
              <div className="a-grid">
                <label>Name as printed<input value={r.name} onChange={(e) => patch(i, { name: e.target.value })} /></label>
                <label>Limit<input value={r.limit} onChange={(e) => patch(i, { limit: e.target.value })} /></label>
                <label className="a-clause">Library clause
                  <input list="clause-titles" value={r.clause ?? ""} disabled={r.printAsQuoted} placeholder={r.printAsQuoted ? "Printed as quoted" : "Search the library"}
                    onChange={(e) => patch(i, { clause: e.target.value || null })} />
                </label>
                <label className="pq"><input type="checkbox" checked={r.printAsQuoted} onChange={(e) => patch(i, { printAsQuoted: e.target.checked, clause: e.target.checked ? null : r.clause })} /> Print as quoted</label>
              </div>
              {(r.remark || r.needsReview.length > 0 || r.nearIdentical.length > 0 || (!r.clause && r.candidates.length > 0)) && (
                <div className="a-meta">
                  {r.remark && <span>Insurer: “{r.remark}”</span>}
                  {r.needsReview.map((n) => <span className="note-amber" key={n}>{REASON[n] ?? n}</span>)}
                  {r.nearIdentical.length > 0 && <span className="note-amber">Similar titles: {r.nearIdentical.join(" · ")}</span>}
                  {!r.clause && r.candidates.map((c) => <button key={c} className="link" onClick={() => patch(i, { clause: c })}>Use: {c.length > 46 ? c.slice(0, 46) + "…" : c}</button>)}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
