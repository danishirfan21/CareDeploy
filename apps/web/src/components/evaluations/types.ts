/** Data shapes for evaluation results. M4 will populate these from real runs. */
export interface EvaluationResultData {
  id: string;
  name: string;
  status: "pass" | "fail";
  durationMs?: number;
  critical?: boolean;
  expected?: string;
  observed?: string;
  technical?: string;
}

export interface EvaluationGroupData {
  id: string;
  name: string;
  results: EvaluationResultData[];
}

export interface EvaluationSummaryData {
  passed: number;
  total: number;
  runTimeSeconds?: number;
}
