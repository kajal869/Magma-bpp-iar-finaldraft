export interface Summary {
  insured: string | null;
  gstin: string | null;
  address: string;
  periodStart: string;
  periodEnd: string;
  product: string | null;
  intermediary: string | null;
  office: string | null;
}

export type FieldKind = "text" | "date" | "money" | "lines";
export type FieldStatus = "ok" | "check" | "missing";

export interface Alternative {
  value: string;
  label: string;
}

export interface Field {
  key: string;
  label: string;
  group: string;
  kind: FieldKind;
  value: string;
  status: FieldStatus;
  source: string;
  note: string | null;
  suggestion: string | null;
  alternatives?: Alternative[];
  required: boolean;
}

export type AddonStatus = "ok" | "check" | "missing" | "dropped";

export interface AddonRow {
  id: number | null; // null = added by the user
  sheet: string;
  row: number;
  serial: string | null;
  name: string;
  limit: string;
  remark: string;
  decision: "keep" | "drop" | "pending";
  decisionClass: string;
  include: boolean;
  clause: string | null;
  wordingId: string | null;
  method: string | null;
  confidence: number;
  status: AddonStatus;
  needsReview: string[];
  nearIdentical: string[];
  candidates: string[];
  printAsQuoted: boolean;
  touched?: boolean; // the user has looked at / changed this row
}

export interface SectionRow {
  no: number;
  label: string;
  sumInsured: number | null;
  premium: number | null;
  status: string;
  note: string;
  opted: boolean;
  subRows: { label: string; sum_insured: number | null; premium: number | null }[];
  touched?: boolean;
}

export interface TermGroup {
  key: string;
  title: string;
  lines: string[];
}

export interface Terms {
  sectionConditions: TermGroup[];
  deductibles: TermGroup[];
  allLines: string[];
}

export interface Edits {
  addons: AddonRow[];
  sections: SectionRow[];
  terms: Terms;
}

export interface AnalyzeResult {
  sessionId: string;
  layout: string | null;
  addons: AddonRow[];
  sections: SectionRow[];
  terms: Terms;
  summary: Summary;
  fields: Field[];
  groups: string[];
  warnings: string[];
  notes: string[];
}

export interface Blank {
  key: string;
  label: string;
  group: string;
}

export interface DraftInfo {
  insured: string;
  policyNo: string;
  product: string;
  period: string;
  netPremium: string;
  finalPremium: string;
  tax: string;
  sections: string[];
}

export interface GenerateResult {
  token: string;
  case: string;
  fileName: string;
  pages: number;
  blanks: Blank[];
  notes: string[];
  draft: DraftInfo;
}

export interface UnsupportedError {
  kind: "unsupported";
  message: string;
  summary: Summary;
}

export interface PlainError {
  kind: "error";
  message: string;
}

export type AppError = UnsupportedError | PlainError;
