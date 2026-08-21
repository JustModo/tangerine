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
  results: TestResult[];
}

export interface ProblemChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

/** What the helper chat sends alongside a question — read fresh at send time. */
export interface HelperContext {
  source_code: string;
  last_run: {
    kind: "run" | "submit";
    passed: number;
    total: number;
    results: TestResult[];
  } | null;
}
