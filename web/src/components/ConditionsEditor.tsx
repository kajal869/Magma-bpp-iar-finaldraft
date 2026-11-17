import type { TermGroup, Terms } from "../types";

interface Props {
  terms: Terms;
  onChange: (t: Terms) => void;
}

const toLines = (s: string) => s.replace(/\r/g, "").split("\n");

function Group({ g, onChange }: { g: TermGroup; onChange: (g: TermGroup) => void }) {
  return (
    <label className="tgroup">
      <span className="flabel">{g.title}</span>
      <textarea rows={Math.max(2, g.lines.length + 1)} value={g.lines.join("\n")} onChange={(e) => onChange({ ...g, lines: toLines(e.target.value) })} />
    </label>
  );
}

export default function ConditionsEditor({ terms, onChange }: Props) {
  const setGroup = (kind: "sectionConditions" | "deductibles", i: number, g: TermGroup) =>
    onChange({ ...terms, [kind]: terms[kind].map((x, k) => (k === i ? g : x)) });
  return (
    <div className="card group fade-up">
      <h3>Conditions, warranties and deductibles</h3>
      <p className="muted small">One line per entry; add, delete or reorder lines freely. Blank lines are dropped.</p>

      <h4>Conditions and warranties by section</h4>
      {terms.sectionConditions.length === 0 && <p className="muted empty">None were read from the quote.</p>}
      {terms.sectionConditions.map((g, i) => <Group key={g.key + i} g={g} onChange={(x) => setGroup("sectionConditions", i, x)} />)}

      <h4>Deductibles / excess by section</h4>
      {terms.deductibles.length === 0 && <p className="muted empty">None were read from the quote.</p>}
      {terms.deductibles.map((g, i) => <Group key={g.key + i} g={g} onChange={(x) => setGroup("deductibles", i, x)} />)}

      <h4>Clauses and conditions applicable to all sections</h4>
      <label className="tgroup">
        <textarea rows={Math.max(3, terms.allLines.length + 1)} value={terms.allLines.join("\n")} aria-label="Conditions applicable to all sections"
          onChange={(e) => onChange({ ...terms, allLines: toLines(e.target.value) })} />
      </label>
      {terms.allLines.filter((l) => l.trim()).length === 0 && <div className="note-amber">Nothing was found for all sections on the quote; this block prints empty unless you add lines.</div>}
    </div>
  );
}
