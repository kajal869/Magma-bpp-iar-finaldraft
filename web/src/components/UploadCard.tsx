import { useRef, useState, type DragEvent } from "react";

interface Props {
  step: number;
  title: string;
  hint: string;
  file: File | null;
  onFile: (f: File | null) => void;
  disabled?: boolean;
}

const OK = /\.(xlsx|xlsm|xls)$/i;

function size(n: number): string {
  return n > 1_048_576 ? `${(n / 1_048_576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
}

/** Long workbook names are shortened in the middle so the extension stays visible; the full name is in the tooltip. */
function shortName(name: string, max = 40): string {
  if (name.length <= max) return name;
  const dot = name.lastIndexOf(".");
  const ext = dot > 0 ? name.slice(dot) : "";
  const base = dot > 0 ? name.slice(0, dot) : name;
  const keepEnd = 8;
  return `${base.slice(0, max - ext.length - keepEnd - 1)}…${base.slice(-keepEnd)}${ext}`;
}

export default function UploadCard({ step, title, hint, file, onFile, disabled }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [bad, setBad] = useState(false);

  function take(f: File | undefined) {
    if (!f) return;
    if (!OK.test(f.name)) {
      setBad(true);
      window.setTimeout(() => setBad(false), 700);
      return;
    }
    onFile(f);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDrag(false);
    if (!disabled) take(e.dataTransfer.files?.[0]);
  }

  return (
    <div
      className={`card upload${drag ? " is-drag" : ""}${file ? " has-file" : ""}${bad ? " is-bad" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={onDrop}
    >
      <div className="upload-head">
        <span className="step-dot">{file ? <svg viewBox="0 0 20 20" className="tick"><path d="M4 10.5l4 4 8-9" /></svg> : step}</span>
        <div>
          <h3>{title}</h3>
          <p className="muted">{hint}</p>
        </div>
      </div>

      {file ? (
        <div className="file-chip">
          <svg viewBox="0 0 24 24" className="xls"><path d="M6 2h8l6 6v14H6z" /><path d="M14 2v6h6" /><path d="M9 13l5 6M14 13l-5 6" /></svg>
          <div className="file-meta">
            <strong title={file.name}>{shortName(file.name)}</strong>
            <span className="muted">{size(file.size)}</span>
          </div>
          <button type="button" className="icon-btn" onClick={() => onFile(null)} disabled={disabled} aria-label={`Remove ${title}`}>
            ×
          </button>
        </div>
      ) : (
        <button type="button" className="dropzone" onClick={() => input.current?.click()} disabled={disabled}>
          <svg viewBox="0 0 24 24" className="up-ico"><path d="M12 16V4M7 9l5-5 5 5" /><path d="M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3" /></svg>
          <span><b>Drop the Excel file here</b> or click to browse</span>
          <span className="muted small">.xlsx or .xls</span>
        </button>
      )}
      <input ref={input} type="file" accept=".xlsx,.xlsm,.xls" hidden onChange={(e) => { take(e.target.files?.[0]); e.target.value = ""; }} />
    </div>
  );
}
