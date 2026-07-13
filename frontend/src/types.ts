// Shared types for the chat UI. Shaped now to hold the agent's full response
// (sql, rows, summary) so streaming (step 9) and the SQL/table view (step 10)
// slot in without reshaping state.

export type Stage = "generating" | "validating" | "executing";

export interface AgentResult {
  sql: string | null;
  columns: string[];
  rows: unknown[][];
  summary: string | null;
  failure: boolean;
  attempts: number;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  text: string; // user question, or assistant summary/placeholder
  stage?: Stage; // in-flight progress (assistant, while streaming)
  pending?: boolean; // assistant response still arriving
  result?: AgentResult; // populated once the answer lands
}
