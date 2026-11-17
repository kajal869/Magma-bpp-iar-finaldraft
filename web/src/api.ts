import type { AnalyzeResult, AppError, Edits, GenerateResult, Summary } from "./types";

export class ApiError extends Error {
  constructor(public detail: AppError) {
    super(detail.message);
  }
}

interface ErrBody {
  error?: string;
  message?: string;
  detail?: string;
  summary?: Summary;
}

async function fail(res: Response): Promise<never> {
  let body: ErrBody = {};
  try {
    body = await res.json();
  } catch {
    /* non-JSON error body */
  }
  if (res.status === 422 && body.error === "unsupported" && body.summary) {
    throw new ApiError({ kind: "unsupported", message: body.message ?? "This case is not supported yet.", summary: body.summary });
  }
  throw new ApiError({ kind: "error", message: body.detail ?? body.message ?? `The server returned an error (${res.status}).` });
}

async function call(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch {
    throw new ApiError({ kind: "error", message: "Could not reach the local server. Is it running on port 8000?" });
  }
}

/** Step 1: read both files and get the list of mandatory fields with their status. */
export async function analyze(slip: File, quote: File): Promise<AnalyzeResult> {
  const form = new FormData();
  form.append("closing_slip", slip);
  form.append("quote", quote);
  const res = await call("/api/analyze", { method: "POST", body: form });
  if (!res.ok) await fail(res);
  return (await res.json()) as AnalyzeResult;
}

/** Clause titles for the add-on dropdown. */
export async function fetchClauses(): Promise<string[]> {
  try {
    const res = await fetch("/api/clauses");
    return res.ok ? ((await res.json()) as { clauses: string[] }).clauses : [];
  } catch {
    return [];
  }
}

/** Step 2: render the front pack with the user's values and edits. */
export async function renderDraft(sessionId: string, values: Record<string, string>, allowBlanks: boolean, edits: Edits): Promise<GenerateResult> {
  const body = {
    sessionId,
    values,
    allowBlanks,
    addons: edits.addons.map((a) => ({ id: a.id, include: a.include, clause: a.clause, name: a.name, limit: a.limit, printAsQuoted: a.printAsQuoted })),
    sections: edits.sections.map((s) => ({ no: s.no, sumInsured: s.sumInsured, premium: s.premium })),
    terms: edits.terms,
  };
  const res = await call("/api/render", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) await fail(res);
  return (await res.json()) as GenerateResult;
}

export const pdfUrl = (token: string, download = false) => `/api/pdf/${token}${download ? "?download=1" : ""}`;
export const pageUrl = (token: string, n: number) => `/api/page/${token}/${n}`;

export function discard(token: string): void {
  void fetch(`/api/pdf/${token}`, { method: "DELETE" }).catch(() => undefined);
}
