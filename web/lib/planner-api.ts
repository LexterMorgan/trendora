import { ResearchApiError, requestJson, type RequestOptions } from "./api.ts";

export type PlannerStatus = "idea" | "working";

export interface PlannerFields {
  title: string;
  platform: string;
  caption: string;
  hook: string;
  creative_brief: string;
  asset_links: string[];
  notes: string;
  planned_date: string | null;
  assignee_id: string | null;
}

export interface PlannerDraft extends PlannerFields {
  status: PlannerStatus;
}

export interface PlannerPost extends PlannerDraft {
  id: string;
  version: number;
  content_revision: number;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface PlannerSummary {
  id: string;
  title: string;
  platform: string;
  status: PlannerStatus;
  planned_date: string | null;
  assignee_id: string | null;
  version: number;
  updated_at: string;
  archived_at: string | null;
}

export interface PlannerMemberOption {
  user_id: string;
  email: string;
}

type Options = Pick<RequestOptions, "signal" | "runtime">;

export function plannerFields(value: PlannerFields): PlannerFields {
  return {
    title: value.title.trim(),
    platform: value.platform.trim(),
    caption: value.caption,
    hook: value.hook,
    creative_brief: value.creative_brief,
    asset_links: [...value.asset_links],
    notes: value.notes,
    planned_date: value.planned_date,
    assignee_id: value.assignee_id,
  };
}

function invalidResponse(): never {
  throw new ResearchApiError("invalid_response", "Trendora returned an unreadable planner response.");
}

function isSummary(value: unknown): value is PlannerSummary {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return ["id", "title", "platform", "updated_at"].every((key) => typeof item[key] === "string")
    && (item.status === "idea" || item.status === "working")
    && Number.isInteger(item.version) && (item.version as number) > 0
    && Number.isFinite(Date.parse(item.updated_at as string))
    && (item.archived_at === null || (typeof item.archived_at === "string" && Number.isFinite(Date.parse(item.archived_at))))
    && ["planned_date", "assignee_id", "archived_at"].every((key) => item[key] === null || typeof item[key] === "string");
}

function readPost(value: unknown): PlannerPost {
  if (!isSummary(value)) return invalidResponse();
  const item = value as unknown as Record<string, unknown>;
  if (!["caption", "hook", "creative_brief", "notes", "created_by", "updated_by", "created_at"].every((key) => typeof item[key] === "string")
    || !Array.isArray(item.asset_links) || !item.asset_links.every((link) => typeof link === "string")
    || !Number.isInteger(item.content_revision) || (item.content_revision as number) < 1
    || !Number.isFinite(Date.parse(item.created_at as string))) return invalidResponse();
  return value as PlannerPost;
}

const postPath = (id: string) => `/api/planner/posts/${encodeURIComponent(id)}`;

export async function listPlannerPosts(options: Options & { archived?: boolean; limit?: number; offset?: number } = {}): Promise<PlannerSummary[]> {
  const limit = options.limit ?? 25;
  const offset = options.offset ?? 0;
  if (!Number.isInteger(limit) || limit < 1 || limit > 100 || !Number.isInteger(offset) || offset < 0) {
    throw new ResearchApiError("invalid_request", "Choose a valid planner page.", "invalid_request", 422);
  }
  const query = new URLSearchParams({ archived: String(options.archived ?? false), limit: String(limit), offset: String(offset) });
  const payload = await requestJson<unknown>(`/api/planner/posts?${query}`, options);
  if (!Array.isArray(payload) || !payload.every(isSummary)) return invalidResponse();
  return payload;
}

export async function getPlannerMembers(options: Options = {}): Promise<PlannerMemberOption[]> {
  const payload = await requestJson<unknown>("/api/planner/members", options);
  if (!Array.isArray(payload) || !payload.every((item) => item && typeof item.user_id === "string" && typeof item.email === "string")) return invalidResponse();
  return payload;
}

export async function getPlannerPost(id: string, options: Options = {}): Promise<PlannerPost> {
  return readPost(await requestJson<unknown>(postPath(id), options));
}

export async function createPlannerPost(fields: PlannerFields, requestId: string, options: Options = {}): Promise<{ id: string }> {
  const payload = await requestJson<{ id?: unknown }>("/api/planner/posts", {
    ...options, method: "POST", body: { ...plannerFields(fields), request_id: requestId },
  });
  if (!payload || typeof payload.id !== "string" || !payload.id) return invalidResponse();
  return { id: payload.id };
}

export async function updatePlannerPost(id: string, draft: PlannerDraft, expectedVersion: number, options: Options = {}): Promise<PlannerPost> {
  return readPost(await requestJson<unknown>(postPath(id), {
    ...options, method: "PUT", body: { ...plannerFields(draft), status: draft.status, expected_version: expectedVersion },
  }));
}

export async function archivePlannerPost(id: string, expectedVersion: number, options: Options = {}): Promise<PlannerPost> {
  return readPost(await requestJson<unknown>(`${postPath(id)}/archive`, {
    ...options, method: "POST", body: { expected_version: expectedVersion },
  }));
}

export async function restorePlannerPost(id: string, expectedVersion: number, options: Options = {}): Promise<PlannerPost> {
  return readPost(await requestJson<unknown>(`${postPath(id)}/restore`, {
    ...options, method: "POST", body: { expected_version: expectedVersion },
  }));
}

export function blankPlannerDraft(): PlannerDraft {
  return { title: "", platform: "", caption: "", hook: "", creative_brief: "", asset_links: [], notes: "", planned_date: null, assignee_id: null, status: "idea" };
}

export function draftFromPost(post: PlannerDraft): PlannerDraft {
  return { ...plannerFields(post), status: post.status };
}

export function draftDirty(draft: PlannerDraft, acknowledged: PlannerDraft | null): boolean {
  return JSON.stringify(draftFromPost(draft)) !== JSON.stringify(draftFromPost(acknowledged ?? blankPlannerDraft()));
}

export function validatePlannerDraft(draft: PlannerDraft): Partial<Record<keyof PlannerDraft, string>> {
  const errors: Partial<Record<keyof PlannerDraft, string>> = {};
  const limits = { title: 200, platform: 80, caption: 20_000, hook: 1_000, creative_brief: 20_000, notes: 20_000 };
  for (const [key, limit] of Object.entries(limits)) {
    const field = key as keyof typeof limits;
    const value = field === "title" || field === "platform" ? draft[field].trim() : draft[field];
    if ([...value].length > limit) errors[field] = `Use ${limit.toLocaleString("en-US")} characters or fewer.`;
  }
  if (!draft.title.trim()) errors.title = "Enter a title.";
  if (draft.status !== "idea" && draft.status !== "working") errors.status = "Choose Idea or Working on it.";
  if (draft.asset_links.length > 20) errors.asset_links = "Use 20 asset links or fewer.";
  for (const link of draft.asset_links) {
    try {
      const url = new URL(link);
      if (!/^https?:\/\//i.test(link) || !url.hostname || url.username || url.password || /^https?:\/\/[^/?#]*@/i.test(link) || /\s/.test(link) || [...link].length > 2_048) throw new Error();
    } catch {
      errors.asset_links = "Use full HTTP(S) links without credentials, up to 2,048 characters each.";
    }
  }
  if (draft.planned_date !== null) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(draft.planned_date);
    if (!match) errors.planned_date = "Choose a valid date.";
    else {
      const year = Number(match[1]), month = Number(match[2]), day = Number(match[3]);
      const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
      const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
      if (year < 1 || month < 1 || month > 12 || day < 1 || day > days[month - 1]) errors.planned_date = "Choose a valid date.";
    }
  }
  if (draft.assignee_id !== null && !/^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i.test(draft.assignee_id)) errors.assignee_id = "Choose an active member or leave this post unassigned.";
  return errors;
}

export function formatPlannerTimestamp(value: string): string {
  return new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Jakarta", dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export interface PlannerOriginSource {
  source_code: string;
  content_external_id: string;
  state: "available" | "restricted" | "expired" | "unresolved";
  url: string | null;
}

export interface PlannerOrigin {
  report_id: string | null;
  item_kind: "idea" | "brief" | null;
  item_index: number | null;
  parent_idea_index: number | null;
  provenance: string;
  context: Record<string, unknown>;
  sources: PlannerOriginSource[];
}

function readOrigin(value: unknown): PlannerOrigin {
  if (!value || typeof value !== "object") return invalidResponse();
  const item = value as Record<string, unknown>;
  if (!Array.isArray(item.sources)) return invalidResponse();
  return value as PlannerOrigin;
}

export async function importPlannerPost(
  requestId: string,
  reportId: string,
  itemKind: "idea" | "brief",
  itemIndex: number,
  options: Options = {},
): Promise<{ id: string }> {
  const payload = await requestJson<{ id?: unknown }>("/api/planner/posts/import", {
    ...options,
    method: "POST",
    body: { request_id: requestId, report_id: reportId, item_kind: itemKind, item_index: itemIndex },
  });
  if (!payload || typeof payload.id !== "string" || !payload.id) return invalidResponse();
  return { id: payload.id };
}

export async function getPlannerOrigin(id: string, options: Options = {}): Promise<PlannerOrigin> {
  return readOrigin(await requestJson<unknown>(`${postPath(id)}/origin`, options));
}
