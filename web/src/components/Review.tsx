import { useEffect, useMemo, useState } from "react";
import { fetchClauses } from "../api";
import type { AddonRow, AnalyzeResult, Edits, Field, FieldStatus, SectionRow, Terms } from "../types";
import AddonsTable, { stateOf } from "./AddonsTable";
import BlankModal from "./BlankModal";
import ConditionsEditor from "./ConditionsEditor";
import SectionsEditor, { sectionState } from "./SectionsEditor";

interface Props {
  data: AnalyzeResult;
  onBack: () => void;
  onGenerate: (values: Record<string, string>, allowBlanks: boolean, edits: Edits) => void;
}

type Filter = "all" | "missing" | "check";

function statusOf(f: Field, value: string): FieldStatus {
  if (!value.trim()) return "missing";
  return f.status === "check" && value === f.value ? "check" : "ok";
}

const BADGE: Record<FieldStatus, string> = { ok: "Captured", check: "Check", missing: "Missing" };

function Ring({ done, total }: { done: number; total: number }) {
  const r = 34;
  const c = 2 * Math.PI * r;
  const pct = total ? done / total : 1;
  return (
    <svg viewBox="0 0 84 84" className="ring-svg" aria-hidden>
      <circle cx="42" cy="42" r={r} className="ring-bg" />
      <circle cx="42" cy="42" r={r} className="ring-fg" style={{ strokeDasharray: c, strokeDashoffset: c * (1 - pct) }} transform="rotate(-90 42 42)" />
      <text x="42" y="47" textAnchor="middle" className="ring-txt">{done}/{total}</text>
    </svg>
  );
}

function Input({ f, value, onChange }: { f: Field; value: string; onChange: (v: string) => void }) {
  const common = { value, onChange: (e: { target: { value: string } }) => onChange(e.target.value), "aria-label": f.label };
  if (f.kind === "lines") return <textarea rows={Math.max(2, value.split("\n").length)} {...common} />;
  if (f.kind === "date") return <input type="date" {...common} />;
  if (f.kind === "money") return <input type="number" step="any" inputMode="decimal" {...common} />;
  return <input type="text" {...common} />;
}

export default function Review({ data, onBack, onGenerate }: Props) {
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(data.fields.map((f) => [f.key, f.value])));
  const [filter, setFilter] = useState<Filter>("all");
  const [confirm, setConfirm] = useState(false);
  const [addons, setAddons] = useState<AddonRow[]>(data.addons);
  const [sections, setSections] = useState<SectionRow[]>(data.sections);
  const [terms, setTerms] = useState<Terms>(data.terms);
  const [clauses, setClauses] = useState<string[]>([]);
  useEffect(() => { void fetchClauses().then(setClauses); }, []);

  const rows = useMemo(() => data.fields.map((f) => ({ f, value: values[f.key] ?? "", st: statusOf(f, values[f.key] ?? "") })), [data.fields, values]);
  const required = rows.filter((r) => r.f.required);
  const missing = required.filter((r) => r.st === "missing");
  const check = rows.filter((r) => r.st === "check");
  const addonMissing = addons.filter((a) => stateOf(a) === "missing");
  const addonCheck = addons.filter((a) => stateOf(a) === "check").length;
  const sectionCheck = sections.filter((x) => sectionState(x) === "check").length;
  const allMissing = missing.length + addonMissing.length;
  const captured = required.length - missing.length;
  const optionalMissing = rows.filter((r) => !r.f.required && r.st === "missing").length;

  const set = (k: string, v: string) => setValues((p) => ({ ...p, [k]: v }));
  const fillAll = () => setValues((p) => {
    const n = { ...p };
    for (const f of data.fields) if (f.suggestion && !(n[f.key] ?? "").trim()) n[f.key] = f.suggestion;
    return n;
  });
  const hasSuggestions = rows.some((r) => r.st === "missing" && r.f.suggestion);

  const edits: Edits = { addons, sections, terms };
  function generate() {
    if (allMissing) setConfirm(true);
    else onGenerate(values, false, edits);
  }

  return (
    <section className="review">
      <div className="card review-top fade-up">
        <Ring done={captured} total={required.length} />
        <div className="review-head">
          <h2>{allMissing ? "A few items need your attention" : "All mandatory fields are captured"}</h2>
          <p className="muted">
            Read from <strong>{data.summary.insured}</strong>. Edit any value, or leave a field blank if you don't have it.
          </p>
          <div className="counts">
            <span className="count c-ok"><i />{captured} fields captured</span>
            <span className="count c-check"><i />{check.length + addonCheck + sectionCheck} to check</span>
            <span className="count c-miss"><i />{allMissing} missing</span>
            {optionalMissing > 0 && <span className="count c-opt"><i />{optionalMissing} optional empty</span>}
          </div>
        </div>
        <div className="review-actions">
          {hasSuggestions && <button className="btn btn-ghost" onClick={fillAll}>Fill missing with sample values</button>}
          <button className="btn btn-primary" onClick={generate}>
            Generate front pack
            <svg viewBox="0 0 24 24" className="btn-ico"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
          </button>
        </div>
      </div>

      {data.warnings.map((w) => <div className="banner warn-banner fade-up" key={w}>{w}</div>)}

      {(data.crossChecks ?? []).length > 0 && (
        <div className="card xcheck fade-up">
          <h3>Closing slip vs quote</h3>
          <p className="muted">The printed values come from the closing slip. This is what the quote says about the same items.</p>
          {(data.crossChecks ?? []).map((x) => (
            <div className={`xrow ${x.agree ? "x-agree" : "x-differ"}`} key={x.label}>
              <span className="xl">{x.label}</span>
              <span className="xv"><em>Slip</em>{x.slip}</span>
              <span className="xv"><em>Quote</em>{x.quote}</span>
              <span className={`badge ${x.agree ? "b-ok" : "b-check"}`}>{x.agree ? "Match" : "Differs"}</span>
            </div>
          ))}
        </div>
      )}

      <div className="tabs fade-up" style={{ animationDelay: "80ms" }}>
        {([["all", "All fields", rows.length], ["missing", "Missing", missing.length], ["check", "To check", check.length]] as [Filter, string, number][]).map(([k, label, n]) => (
          <button key={k} className={`tab${filter === k ? " on" : ""}`} onClick={() => setFilter(k)}>{label}<span>{n}</span></button>
        ))}
      </div>

      {data.groups.map((g, gi) => {
        const list = rows.filter((r) => r.f.group === g && (filter === "all" || (filter === "missing" ? r.st === "missing" : r.st === "check")));
        if (!list.length) return null;
        return (
          <div className="card group fade-up" key={g} style={{ animationDelay: `${120 + gi * 60}ms` }}>
            <h3>{g}</h3>
            {list.map(({ f, value, st }) => (
              <div className={`frow st-${st}`} key={f.key}>
                <div className="fl">
                  <span className="flabel">{f.label}{!f.required && <em> (optional)</em>}</span>
                  <span className={`badge b-${st}`}>{st === "ok" ? <svg viewBox="0 0 20 20" className="tick"><path d="M4 10.5l4 4 8-9" /></svg> : st === "check" ? "!" : "×"}{BADGE[st]}</span>
                </div>
                <div className="fi">
                  <Input f={f} value={value} onChange={(v) => set(f.key, v)} />
                  <div className="fmeta">
                    <span className="muted">{value === f.value ? f.source : "Edited by you"}</span>
                    {f.note && st === "check" && <span className="note-amber">{f.note}</span>}
                    {st !== "ok" && (f.alternatives ?? []).filter((a) => a.value && a.value !== value).map((a) => (
                      <button key={a.label + a.value} className="link" type="button" onClick={() => set(f.key, a.value)}>Use {a.label}: {a.value.length > 30 ? a.value.slice(0, 30) + "…" : a.value}</button>
                    ))}
                    {st === "missing" && f.suggestion && (
                      <button className="link" type="button" onClick={() => set(f.key, f.suggestion ?? "")}>Use sample: {f.suggestion.length > 34 ? f.suggestion.slice(0, 34) + "…" : f.suggestion}</button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        );
      })}

      <SectionsEditor rows={sections} onChange={setSections} />
      <AddonsTable rows={addons} clauses={clauses} onChange={setAddons} />
      <ConditionsEditor terms={terms} onChange={setTerms} />

      <div className="review-foot">
        <button className="btn btn-ghost" onClick={onBack}>Upload different files</button>
        <button className="btn btn-primary" onClick={generate}>Generate front pack</button>
      </div>

      {confirm && (
        <BlankModal
          blanks={[...missing.map((m) => m.f.label), ...addonMissing.map((a) => `Add-on cover: ${a.name || "(unnamed)"}`)]}
          onCancel={() => { setConfirm(false); setFilter("missing"); }}
          onConfirm={() => { setConfirm(false); onGenerate(values, true, edits); }}
        />
      )}
    </section>
  );
}
