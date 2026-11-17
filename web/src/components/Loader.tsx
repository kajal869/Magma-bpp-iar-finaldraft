import { useEffect, useState } from "react";

export const READ_STEPS = [
  "Reading the closing slip",
  "Reading the broker quote",
  "Matching add-ons and clauses",
  "Checking mandatory fields",
  "Preparing your review",
];
export const BUILD_STEPS = [
  "Applying your values",
  "Checking totals and tax",
  "Building schedule and annexures",
  "Rendering the front pack PDF",
];
const TIPS = [
  "Numbers are checked: premium + GST must tie to the closing slip.",
  "Nothing is stored. Files are deleted as soon as the draft is built.",
  "The front pack covers schedule, premium summary, GST block and annexures.",
];
const STEP_MS = 850;

interface Props {
  title: string;
  steps: string[];
  /** true once the server has answered; the loader then finishes its steps and calls onDone */
  ready: boolean;
  onDone: () => void;
}

export default function Loader({ title, steps: STEPS, ready, onDone }: Props) {
  const [active, setActive] = useState(0);
  const [tip, setTip] = useState(0);

  // steps advance on a timer but wait on the last step until the server is ready
  useEffect(() => {
    const last = STEPS.length - 1;
    if (active < last) {
      const t = window.setTimeout(() => setActive((a) => a + 1), STEP_MS);
      return () => window.clearTimeout(t);
    }
    if (ready && active === last) {
      const t = window.setTimeout(() => setActive(STEPS.length), 500);
      return () => window.clearTimeout(t);
    }
    if (active === STEPS.length) {
      const t = window.setTimeout(onDone, 650);
      return () => window.clearTimeout(t);
    }
  }, [active, ready, onDone, STEPS.length]);

  useEffect(() => {
    const t = window.setInterval(() => setTip((x) => (x + 1) % TIPS.length), 2800);
    return () => window.clearInterval(t);
  }, []);

  const pct = Math.round((Math.min(active, STEPS.length) / STEPS.length) * 100);

  return (
    <div className="loader" role="status" aria-live="polite">
      <div className="loader-card">
        <div className="orbit">
          <span className="ring r1" />
          <span className="ring r2" />
          <span className="ring r3" />
          <img src="/magma-logo.png" alt="" />
        </div>
        <h2>{title}</h2>
        <ol className="steps">
          {STEPS.map((s, i) => (
            <li key={s} className={i < active ? "done" : i === active ? "now" : ""}>
              <span className="mark">
                {i < active ? <svg viewBox="0 0 20 20" className="tick"><path d="M4 10.5l4 4 8-9" /></svg> : i === active ? <span className="spin" /> : null}
              </span>
              {s}
            </li>
          ))}
        </ol>
        <div className="bar"><span style={{ width: `${pct}%` }} /></div>
        <p className="tip" key={tip}>{TIPS[tip]}</p>
      </div>
    </div>
  );
}
