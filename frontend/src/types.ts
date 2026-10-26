export interface User {
  id: string;
  username: string;
  role: string;
  active?: boolean;
}
export interface Evidence {
  quote: string;
  page?: number | null;
  start?: number | null;
  source_id?: string | null;
}
export interface Profile {
  name: string | null;
  phone: string | null;
  email: string | null;
  location: string | null;
  education: {
    school: string | null;
    degree: string | null;
    major: string | null;
  }[];
  experiences: {
    company: string | null;
    title: string | null;
    start: string | null;
    end: string | null;
    description: string;
    skills: string[];
  }[];
  projects: { name: string; description: string; skills: string[] }[];
  skills: string[];
  certificates: string[];
  intentions: string[];
  evidence: Record<string, Evidence[]>;
  summary: string;
  tags: string[];
  anomalies: string[];
  experience_months: number;
  completeness: number;
}
export interface Talent {
  id: string;
  name: string | null;
  profile: Profile;
  revision: number;
  indexed_revision: number;
  active: boolean;
  created_at: string;
  documents?: { id: string; filename: string; status: string }[];
  revisions?: { revision: number; profile: Profile; reason: string }[];
  merges?: { id: string; after_revision: number; undone: boolean }[];
}
export interface Requirements {
  required_skills: string[];
  preferred_skills: string[];
  min_experience_months: number | null;
  min_education: string | null;
  required_certificates: string[];
  location: string | null;
  responsibilities: string[];
  evidence: Record<string, Evidence[]>;
}
export interface Job {
  id: string;
  title: string;
  description: string;
  requirements: Requirements;
  revision: number;
  status: string;
}
export interface Score {
  eligible: boolean;
  total: number;
  dimensions: {
    key: string;
    label: string;
    score: number;
    weight: number;
    evidence: string[];
  }[];
  conditions: {
    label: string;
    status: "pass" | "fail" | "unknown";
    evidence: string;
  }[];
  strengths: string[];
  gaps: string[];
  unknowns: string[];
}
export interface Candidate {
  talent_id: string;
  name: string;
  profile: Profile;
  revision: number;
  score: Score;
}
export interface ModelVersion {
  name: string;
  digest: string;
}
export interface MatchRun {
  id: string;
  job_id: string;
  status: string;
  job_snapshot: Record<string, unknown>;
  results: Candidate[] | null;
  diagnostics: unknown;
  model_versions: Record<
    string,
    string | ModelVersion | Record<string, number>
  > | null;
  duration_ms: number | null;
  created_at: string;
}
export interface Task {
  id: string;
  kind: string;
  status: string;
  attempts: number;
  error?: string;
  created_at: string;
}
export interface BatchItem {
  id: string;
  filename: string;
  status: string;
  error?: string;
  talent_id?: string;
  reused?: boolean;
}
export interface Batch {
  id: string;
  created_at: string;
  items: BatchItem[];
}
export interface Issue {
  id: string;
  talent_id: string;
  other_id?: string;
  kind: string;
  detail: unknown;
  resolved: boolean;
}
export interface System {
  services: Record<string, { ok: boolean; detail: string }>;
  models: { chat: string; embedding: string };
  limits: { batch_files: number; file_mb: number };
  mode: string;
}
export interface Dashboard {
  talents: number;
  indexed: number;
  jobs: number;
  documents: number;
  queued: number;
  failed: number;
  issues: number;
}
