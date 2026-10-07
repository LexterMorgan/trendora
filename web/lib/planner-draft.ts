import { ResearchApiError } from "./api.ts";
import { createSubmitGate } from "./submit-gate.ts";
import {
  archivePlannerPost, blankPlannerDraft, createPlannerPost, draftDirty, draftFromPost,
  getPlannerPost, plannerFields, restorePlannerPost, updatePlannerPost, validatePlannerDraft,
  type PlannerDraft, type PlannerFields, type PlannerPost,
} from "./planner-api.ts";

export interface PlannerDraftState {
  draft: PlannerDraft;
  acknowledged: PlannerPost | null;
  knownId: string | null;
  busy: boolean;
  phase: "idle" | "loading" | "saving" | "saved" | "failed" | "uncertain" | "conflict";
  error: ResearchApiError | null;
  recovery: PlannerPost | null;
  pendingCreate: { requestId: string; snapshot: PlannerFields } | null;
  requiresReconcile: boolean;
  dirty: boolean;
}

export interface PlannerDraftApi {
  get: typeof getPlannerPost;
  create: typeof createPlannerPost;
  update: typeof updatePlannerPost;
  archive: typeof archivePlannerPost;
  restore: typeof restorePlannerPost;
}

function asError(value: unknown): ResearchApiError {
  return value instanceof ResearchApiError ? value : new ResearchApiError("backend_unreachable", "The result is uncertain. Check the current server version before continuing.", "network");
}

function uncertain(error: ResearchApiError): boolean {
  return error.status === 0 || error.status >= 500 || error.code === "invalid_response";
}

export function createPlannerDraft(options: { post?: PlannerPost; api?: PlannerDraftApi; isCurrentSession?: () => boolean; requestId?: () => string } = {}) {
  const api = options.api ?? { get: getPlannerPost, create: createPlannerPost, update: updatePlannerPost, archive: archivePlannerPost, restore: restorePlannerPost };
  const current = options.isCurrentSession ?? (() => true);
  const listeners = new Set<() => void>();
  const gate = createSubmitGate();
  let revision = 0;
  let generation = 0;
  let disposed = false;
  let creationRevision: number | null = null;
  const initial = (): PlannerDraftState => ({ draft: blankPlannerDraft(), acknowledged: null, knownId: null, busy: false, phase: "idle", error: null, recovery: null, pendingCreate: null, requiresReconcile: false, dirty: false });
  let state = initial();
  if (options.post) state = { ...state, draft: draftFromPost(options.post), acknowledged: options.post, knownId: options.post.id, phase: "saved" };

  function commit(next: Partial<PlannerDraftState>) {
    state = { ...state, ...next };
    state.dirty = draftDirty(state.draft, state.acknowledged);
    for (const listener of listeners) listener();
  }

  function alive(ticket: number): boolean {
    return !disposed && current() && ticket === generation;
  }

  function accept(post: PlannerPost, submittedRevision: number, preserveDraft = false) {
    creationRevision = null;
    commit({ acknowledged: post, knownId: post.id, draft: !preserveDraft && revision === submittedRevision ? draftFromPost(post) : state.draft, phase: "saved", error: null, pendingCreate: null, recovery: null, requiresReconcile: false });
  }

  async function read(id: string, recovery: boolean) {
    if (disposed || !current() || !gate.acquire()) return;
    const ticket = ++generation, submittedRevision = creationRevision ?? revision;
    const preserveDraft = state.acknowledged !== null && state.dirty;
    commit({ busy: true, phase: "loading", error: null, knownId: id });
    try {
      const post = await api.get(id);
      if (!alive(ticket)) return;
      if (recovery) commit({ recovery: post, phase: "conflict" });
      else accept(post, submittedRevision, preserveDraft);
    } catch (value) {
      if (alive(ticket)) commit({ error: asError(value), phase: state.requiresReconcile ? "uncertain" : "failed" });
    } finally {
      if (alive(ticket)) { gate.release(); commit({ busy: false }); }
    }
  }

  async function create() {
    if (state.knownId) return read(state.knownId, false);
    if (disposed || !current() || !gate.acquire()) return;
    if (!state.pendingCreate && Object.keys(validatePlannerDraft(state.draft)).length) {
      gate.release();
      commit({ phase: "failed", error: new ResearchApiError("invalid_request", "Check the highlighted fields before saving.", "invalid_request", 422) });
      return;
    }
    if (!state.pendingCreate) {
      creationRevision = revision;
      const snapshot = plannerFields(state.draft);
      Object.freeze(snapshot.asset_links);
      Object.freeze(snapshot);
      commit({ pendingCreate: { requestId: (options.requestId ?? (() => crypto.randomUUID()))(), snapshot } });
    }
    const pending = state.pendingCreate!;
    const ticket = ++generation, submittedRevision = creationRevision ?? revision;
    commit({ busy: true, phase: "saving", error: null });
    try {
      const result = await api.create(pending.snapshot, pending.requestId);
      if (!alive(ticket)) return;
      commit({ knownId: result.id, pendingCreate: null });
      const post = await api.get(result.id);
      if (alive(ticket)) accept(post, submittedRevision);
    } catch (value) {
      if (!alive(ticket)) return;
      const error = asError(value);
      const unresolved = !state.knownId && (uncertain(error) || error.code === "planner_create_conflict");
      if (!unresolved && !state.knownId) creationRevision = null;
      commit({ error, phase: unresolved ? "uncertain" : "failed", pendingCreate: unresolved ? pending : null });
    } finally {
      if (alive(ticket)) { gate.release(); commit({ busy: false }); }
    }
  }

  async function mutate(action: "update" | "archive" | "restore") {
    if (disposed || !current() || state.requiresReconcile || !state.acknowledged || !gate.acquire()) return;
    if (action === "update" && Object.keys(validatePlannerDraft(state.draft)).length) {
      gate.release();
      commit({ phase: "failed", error: new ResearchApiError("invalid_request", "Check the highlighted fields before saving.", "invalid_request", 422) });
      return;
    }
    const post = state.acknowledged;
    const submitted = draftFromPost(state.draft);
    const ticket = ++generation, submittedRevision = revision;
    commit({ busy: true, phase: "saving", error: null, recovery: null });
    try {
      const result = action === "update" ? await api.update(post.id, submitted, post.version) : await api[action](post.id, post.version);
      if (alive(ticket)) accept(result, submittedRevision, action === "restore");
    } catch (value) {
      if (!alive(ticket)) return;
      const error = asError(value);
      const conflict = error.code === "planner_version_conflict" || error.code === "planner_post_archived";
      commit({ error, phase: conflict ? "conflict" : uncertain(error) ? "uncertain" : "failed", requiresReconcile: conflict || uncertain(error) });
    } finally {
      if (alive(ticket)) { gate.release(); commit({ busy: false }); }
    }
  }

  return {
    getSnapshot: () => state,
    subscribe(listener: () => void) {
      disposed = false;
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    edit(draft: PlannerDraft) {
      if (disposed || !current()) return;
      revision += 1;
      commit({ draft: { ...draft, asset_links: [...draft.asset_links] } });
    },
    load: (id: string) => read(id, state.requiresReconcile),
    create,
    save: () => state.acknowledged ? mutate("update") : create(),
    archive: () => mutate("archive"),
    restore: () => mutate("restore"),
    reconcile: () => state.knownId ? read(state.knownId, true) : Promise.resolve(),
    recover(choice: "server" | "local") {
      if (disposed || !current() || state.busy || !state.recovery) return;
      revision += 1;
      const post = state.recovery;
      commit({ acknowledged: post, knownId: post.id, draft: choice === "server" ? draftFromPost(post) : state.draft, requiresReconcile: false, recovery: null, error: null, phase: "saved" });
    },
    dispose() {
      disposed = true;
      generation += 1;
      revision += 1;
      gate.release();
      creationRevision = null;
      state = initial();
    },
  };
}
