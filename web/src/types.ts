export interface Standard { code: string; subject: string; grade: number; title: string; description: string }

export interface RubricRow { criterion: string; max_points: number; descriptors: string }

export interface Item {
  id: string; standard_code: string; standard_title: string; item_type: 'MULTIPLE_CHOICE' | 'CONSTRUCTED_RESPONSE' | 'CODE';
  difficulty: string; stem: string; choices: string[] | null; answer_key?: string; rubric: RubricRow[];
  tests: { args: unknown[]; expected: unknown }[] | null; status: 'DRAFT' | 'APPROVED' | 'REJECTED'; source: string;
  review_notes?: { agent_review?: { overall_quality: number; issues: string[] }; rationale?: string; served_by?: string; teacher_note?: string } | null;
  created_at: string; decided_by?: string | null;
}

export interface Criterion { criterion: string; points_awarded: number; max_points?: number; evidence: string; reasoning: string }

export interface ResponseRow {
  id: string; student_id: string; student_name: string; item_id: string; stem: string; item_type: string; response_text: string;
  ai_score: string | null; max_score: string | null; ai_confidence: string | null;
  ai_result: { criteria: Criterion[]; feedback_for_student?: string; misconception?: string; served_by?: string; method?: string;
               tests?: { test: number; passed: boolean; expected?: unknown; actual?: unknown; error?: string }[] } | null;
  safety: { flags: string[]; detail?: string } | null; needs_human_review: boolean; review_reasons: string[];
  human_score: string | null; human_note: string | null; reviewed_by: string | null; status: string; created_at: string;
}

export interface AgentRun {
  id: string; status: 'RUNNING' | 'SUCCEEDED' | 'FAILED'; input: Record<string, string>;
  steps: { step: string; detail: unknown }[]; output: { item_id: string } | null; error: string | null; started_at: string;
}

export const TYPE_LABEL: Record<string, string> = { MULTIPLE_CHOICE: 'Multiple choice', CONSTRUCTED_RESPONSE: 'Written response', CODE: 'Coding' };
