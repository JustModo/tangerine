export interface ProblemExample {
  id: string;
  input: string;
  output: string;
  explanation?: string | null;
}

export interface ProblemDetail {
  id: string;
  title: string;
  language: string;
  difficulty: string;
  statement_md: string;
  user_code: string;
  constraints?: string | null;
  input_format?: string | null;
  output_format?: string | null;
  hints: string[];
  tags: string[];
  examples: ProblemExample[];
}

export interface LessonNoteStep {
  title: string;
  body_md: string;
}

export interface LessonNotes {
  steps: LessonNoteStep[];
}

export interface TestResult {
  id: string;
  status: "PENDING" | "PASSED" | "FAILED" | "ERROR" | "TIMEOUT";
  input: string;
  actual_output?: string | null;
  error?: string | null;
  execution_time_ms?: string | null;
  exit_code?: number | null;
  signal?: number | null;
  memory_kb?: number | null;
  status_description?: string | null;
  stdout_truncated?: boolean;
  stderr_truncated?: boolean;
}

export interface EvaluationResult {
  passed_tests: number;
  total_tests: number;
  /** How the solution compares to the reference on a large input. Null when the problem
   * has no stress input, or the submission didn't pass everything. */
  complexity_verdict?: "optimal" | "acceptable" | "slow" | null;
  results: TestResult[];
}

/** What the attempt cost. Only the browser knows any of it, so the client reports it. */
export interface AttemptMetrics {
  duration_ms: number;
  run_count: number;
  hints_used: number;
  helper_used: boolean;
}

export interface SkillProgress {
  skill_id: string;
  skill_name: string;
  mastery_score: number;
  streak: number;
  last_seen_at: string;
}

export interface RevisionCandidate {
  skill_id: string;
  skill_name: string;
  reason: "weak_skill" | "overdue_revision" | "review";
  priority: number;
  mastery_score: number;
  days_since_seen: number;
}

export interface ProblemSummary {
  id: string;
  title: string;
  language: string;
  difficulty: string;
  tags: string[];
  created_at: string;
  flagged: boolean;
}

export interface ProblemsPage {
  items: ProblemSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface FlaggedProblem {
  problem_session_id: string;
  problem_id: string;
  title: string;
  difficulty: string;
  updated_at: string;
}

export interface Progress {
  skills: SkillProgress[];
  best_streak: number;
  solved_total: number;
  solved_this_week: number;
  revision_queue: RevisionCandidate[];
  flagged: FlaggedProblem[];
}

export interface ProblemChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

/** What the helper chat sends alongside a question - read fresh at send time. */
export interface HelperContext {
  source_code: string;
  last_run: {
    kind: "run" | "submit";
    passed: number;
    total: number;
    results: TestResult[];
  } | null;
}
