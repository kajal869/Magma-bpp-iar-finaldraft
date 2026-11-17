import { useEffect } from "react";

interface Props {
  blanks: string[];
  onCancel: () => void;
  onConfirm: () => void;
}

export default function BlankModal({ blanks, onCancel, onConfirm }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCancel();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="modal-back" onClick={onCancel}>
      <div className="modal pop-in" role="dialog" aria-modal="true" aria-labelledby="blank-title" onClick={(e) => e.stopPropagation()}>
        <div className="warn-ico">!</div>
        <h2 id="blank-title">Generate with blank fields?</h2>
        <p className="muted">
          {blanks.length === 1 ? "This mandatory field is" : `These ${blanks.length} mandatory fields are`} empty. The places where {blanks.length === 1 ? "it" : "they"} belong in the PDF will be <strong>left blank</strong>.
        </p>
        <ul className="blank-list">
          {blanks.map((b) => <li key={b}>{b}</li>)}
        </ul>
        <div className="modal-actions">
          <button className="btn btn-ghost" onClick={onCancel}>Go back and fill</button>
          <button className="btn btn-primary" onClick={onConfirm}>Generate with blanks</button>
        </div>
      </div>
    </div>
  );
}
