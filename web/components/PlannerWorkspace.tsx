"use client";

import { useEffect, useRef, useState, useSyncExternalStore, type FormEvent } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Header } from "@/components/Header";
import { ApiErrorPanel } from "@/components/ApiErrorPanel";
import { PlannerOriginPanel } from "@/components/PlannerOriginPanel";
import { ResearchApiError } from "@/lib/api";
import { getSessionStore } from "@/lib/auth/client";
import { formatPlannerTimestamp, getPlannerMembers, validatePlannerDraft, type PlannerDraft, type PlannerMemberOption } from "@/lib/planner-api";
import { createPlannerDraft } from "@/lib/planner-draft";

type FieldErrors = Partial<Record<keyof PlannerDraft, string>>;
const writingFields = [
  ["hook", "Hook", 3],
  ["caption", "Caption", 8],
  ["creative_brief", "Creative brief", 6],
] as const;

function safeLink(value: string) {
  try {
    const url = new URL(value);
    return /^https?:\/\//i.test(value) && !!url.hostname && !url.username && !url.password && !/^https?:\/\/[^/?#]*@/i.test(value) && !/\s/.test(value);
  } catch { return false; }
}

export function PlannerWorkspace({ id: routeId }: { id?: string }) {
  const pathname = usePathname();
  // Capture identity per account mount; route promotion must retain newer edits.
  const [id] = useState(() => {
    const pathId = /^\/planner\/([^/]+)$/.exec(pathname)?.[1];
    return routeId ?? (pathId === "new" ? undefined : pathId);
  });
  const [store] = useState(() => {
    const session = getSessionStore();
    const binding = session.getSessionBinding();
    return createPlannerDraft({
      isCurrentSession: () => {
        const current = session.getSessionState();
        return current.status === "signedIn" && !current.denied && current.userId === binding.userId && current.epoch === binding.epoch;
      },
    });
  });
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
  const [members, setMembers] = useState<PlannerMemberOption[]>([]);
  const [membersLoading, setMembersLoading] = useState(true);
  const [membersError, setMembersError] = useState<ResearchApiError | null>(null);
  const [membersReload, setMembersReload] = useState(0);
  const [errors, setErrors] = useState<FieldErrors>({});
  const validation = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (id) void store.load(id);
    return () => store.dispose();
  }, [store, id]);

  useEffect(() => {
    if (!id && state.knownId) {
      window.history.replaceState(null, "", `/planner/${encodeURIComponent(state.knownId)}`);
    }
  }, [id, state.knownId]);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    getPlannerMembers({ signal: controller.signal })
      .then((options) => { if (active) { setMembers(options); setMembersError(null); } })
      .catch((error) => {
        if (active && error?.name !== "AbortError") {
          setMembersError(error instanceof ResearchApiError ? error : new ResearchApiError("unknown_error", "Assignment options could not be loaded."));
        }
      })
      .finally(() => { if (active) setMembersLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [membersReload]);

  useEffect(() => {
    function needsWarning() {
      const current = store.getSnapshot();
      return current.dirty || current.busy || !!current.pendingCreate || !!current.knownId && !current.acknowledged || current.requiresReconcile;
    }
    function beforeUnload(event: BeforeUnloadEvent) {
      if (!needsWarning()) return;
      event.preventDefault();
      event.returnValue = "";
    }
    function beforeNavigation(event: MouseEvent) {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey || !needsWarning()) return;
      const target = event.target instanceof Element ? event.target : null;
      const link = target?.closest<HTMLAnchorElement>("a[href]");
      const signingOut = target?.closest(".sign-out-button");
      if (!link && !signingOut) return;
      if (link) {
        if (link.target === "_blank" || link.hasAttribute("download")) return;
        const url = new URL(link.href);
        if (url.pathname === window.location.pathname && url.search === window.location.search) return;
      }
      const current = store.getSnapshot();
      if (link && current.pendingCreate && current.error?.code !== "planner_create_conflict") {
        event.preventDefault();
        event.stopPropagation();
        window.alert("Resolve this creation attempt before opening another post. The original request may have committed. Keep this tab open and retry the same creation.");
        return;
      }
      const message = current.pendingCreate || current.knownId && !current.acknowledged || current.requiresReconcile || current.busy
        ? "A request may already have been saved. Leaving loses this attempt's retry information and any unsaved text. Leave anyway?"
        : "Your unsaved edits will be discarded. Leave this post?";
      if (!window.confirm(message)) { event.preventDefault(); event.stopPropagation(); }
    }
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", beforeNavigation, true);
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", beforeNavigation, true);
    };
  }, [store]);

  const draft = state.draft;
  const saved = state.acknowledged;
  const archived = !!saved?.archived_at;
  const creating = !saved;
  const creationLocked = !!state.pendingCreate || !!state.knownId && !saved;
  const readOnly = archived || creationLocked;
  const unavailable = !!id && !saved;
  const historicalAssignee = saved?.assignee_id && !members.some((member) => member.user_id === saved.assignee_id)
    ? saved.assignee_id : null;

  function edit(patch: Partial<PlannerDraft>) {
    store.edit({ ...store.getSnapshot().draft, ...patch });
    setErrors({});
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (state.busy || state.requiresReconcile || archived) return;
    const nextErrors = validatePlannerDraft(store.getSnapshot().draft);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) {
      requestAnimationFrame(() => validation.current?.focus());
      return;
    }
    void (creating ? store.create() : store.save());
  }

  function archive() {
    const message = state.dirty
      ? "Archive this post and discard your unsaved edits? Only its last saved content will be archived."
      : "Archive this post? You can restore it from the archived view.";
    if (window.confirm(message)) void store.archive();
  }

  function loadServerSnapshot() {
    if (!state.dirty || window.confirm("Discard your local edits and load the latest server snapshot?")) store.recover("server");
  }

  const statusMessage = state.busy ? (state.phase === "loading" ? "Loading saved post…" : "Saving request…")
    : state.requiresReconcile ? "Save outcome needs checking. Local text is retained."
    : state.pendingCreate ? "Creation outcome is unconfirmed. Submitted text is retained."
    : !id && state.knownId && !saved ? "Post created. Its saved snapshot still needs loading."
    : state.phase === "conflict" ? "Changes need review. Local text is retained."
    : state.error ? "Request failed. Entered text is retained."
    : state.dirty ? "Unsaved changes"
    : saved ? "Saved" : "Not saved yet";

  function errorFor(field: keyof PlannerDraft) {
    return errors[field] ? <p className="planner-field-error" id={`${field}-error`}>{errors[field]}</p> : null;
  }

  return (
    <main className="workspace planner-workspace">
      <Header section={saved || id ? "Post workspace" : "New planner post"} actionLink={{ href: "/past-reports", label: "Past reports" }} />
      <Link className="secondary-button" href="/planner">Back to planner</Link>
      <section className="planner-heading">
        <div>
          <h1>{saved || id ? "Post workspace" : "New post"}</h1>
          <p>{archived ? "Archived posts are read-only. Restore this post to edit it." : "Write a post for the shared planner. Save explicitly when it is ready to keep."}</p>
        </div>
      </section>
      <p className="planner-status-line" role="status" aria-live="polite">
        {statusMessage}{saved && ` · Last acknowledged ${formatPlannerTimestamp(saved.updated_at)} Jakarta`}
      </p>

      {id && <PlannerOriginPanel postId={id} />}

      {state.error && <ApiErrorPanel title={state.error.code === "planner_version_conflict" ? "This post has changed" : state.error.code === "planner_create_conflict" ? "Creation key conflict" : state.error.code === "planner_post_archived" ? "This post was archived" : "Could not complete request"} error={state.error}>
        {(state.pendingCreate || state.knownId && !saved) && state.error.code !== "planner_create_conflict" && (
          <button className="secondary-button" type="button" disabled={state.busy} onClick={() => void store.create()}>
            {state.knownId ? id ? "Retry loading post" : "Retry loading created post" : "Retry same creation"}
          </button>
        )}
        {unavailable && !state.knownId && <button className="secondary-button" type="button" disabled={state.busy} onClick={() => void store.load(id!)}>Retry loading post</button>}
      </ApiErrorPanel>}

      {!id && (state.pendingCreate || state.knownId) && !saved && (
        <section className="planner-notice">
          <h2>{state.knownId ? "Post created, snapshot not yet loaded" : "Creation attempt retained"}</h2>
          <p>{state.knownId ? "The post ID is known. Retry loading it; creation will not be sent again." : "These fields are locked to the original submitted content. Retry uses the same request ID so an uncertain response cannot create a second post."}</p>
          {state.error?.code === "planner_create_conflict" && <p>This key conflicts with an existing record. Check the shared inbox before starting another post.</p>}
          {state.pendingCreate && <Link className="secondary-button" href="/planner" target="_blank" rel="noopener noreferrer">Inspect planner in a new tab</Link>}
        </section>
      )}

      {state.requiresReconcile && (
        <section className="planner-notice" aria-label="Server state recovery">
          <h2>Check the latest server state</h2>
          <p>The previous request may have committed. Your edits remain here. Read the server snapshot before deciding what to do next.</p>
          <button className="secondary-button" type="button" disabled={state.busy} onClick={() => void store.reconcile()}>Check latest server state</button>
          {state.recovery && (
            <>
              <details className="planner-snapshot">
                <summary>Latest server snapshot, version {state.recovery.version}{state.recovery.archived_at ? ", archived" : ""}</summary>
                <dl>
                  {Object.entries(state.recovery).filter(([field]) => ["title", "platform", "caption", "hook", "creative_brief", "asset_links", "notes", "planned_date", "assignee_id", "status"].includes(field)).map(([field, value]) => (
                    <div key={field}><dt>{field.replaceAll("_", " ")}</dt><dd>{Array.isArray(value) ? value.join("\n") : value ?? "Not set"}</dd></div>
                  ))}
                </dl>
              </details>
              <p>Keeping your edits selects this version for a future Save. It does not save or merge automatically.</p>
              <div className="planner-actions">
                <button className="secondary-button" type="button" onClick={() => store.recover("local")}>Keep my edits, use latest version</button>
                <button className="secondary-button" type="button" onClick={loadServerSnapshot}>Load server snapshot</button>
              </div>
            </>
          )}
        </section>
      )}

      {!unavailable && <form onSubmit={submit} noValidate>
        {Object.keys(errors).length > 0 && (
          <div className="planner-notice planner-validation" role="alert" tabIndex={-1} ref={validation}>
            <h2>Check these fields</h2>
            <ul>{Object.entries(errors).map(([field, message]) => <li key={field}><a href={`#planner-${field}`}>{message}</a></li>)}</ul>
          </div>
        )}
        <div className="planner-form">
          <section className="planner-writing" aria-labelledby="planner-content-title">
            <h2 id="planner-content-title">Post content</h2>
            <div className="planner-field">
              <label htmlFor="planner-title">Title</label>
              <input id="planner-title" value={draft.title} required readOnly={readOnly} aria-invalid={!!errors.title} aria-describedby={errors.title ? "title-error" : undefined} onChange={(event) => edit({ title: event.target.value })} />
              {errorFor("title")}
            </div>
            <div className="planner-field">
              <label htmlFor="planner-platform">Platform</label>
              <input id="planner-platform" value={draft.platform} readOnly={readOnly} aria-invalid={!!errors.platform} aria-describedby={`platform-help${errors.platform ? " platform-error" : ""}`} onChange={(event) => edit({ platform: event.target.value })} />
              <p className="planner-help" id="platform-help">Optional. Leave blank if you have not chosen a platform.</p>
              {errorFor("platform")}
            </div>
            {writingFields.map(([field, label, rows]) => (
              <div className="planner-field" key={field}>
                <label htmlFor={`planner-${field}`}>{label}</label>
                <textarea id={`planner-${field}`} value={draft[field]} rows={rows} readOnly={readOnly} aria-invalid={!!errors[field]} aria-describedby={errors[field] ? `${field}-error` : undefined} onChange={(event) => edit({ [field]: event.target.value })} />
                {errorFor(field)}
              </div>
            ))}
            <div className="planner-field">
              <label htmlFor="planner-asset_links">Asset links</label>
              <textarea id="planner-asset_links" value={draft.asset_links.join("\n")} rows={4} readOnly={readOnly} aria-invalid={!!errors.asset_links} aria-describedby={`asset-links-help${errors.asset_links ? " asset_links-error" : ""}`} onChange={(event) => edit({ asset_links: event.target.value === "" ? [] : event.target.value.split("\n") })} />
              <p className="planner-help" id="asset-links-help">One HTTP(S) URL per line, up to 20 links. No embedded credentials. Links are not previewed.</p>
              {errorFor("asset_links")}
              {draft.asset_links.some(safeLink) && <ul className="planner-links">{draft.asset_links.filter(safeLink).map((link, index) => <li key={index}><a href={link} target="_blank" rel="noopener noreferrer">{link}</a></li>)}</ul>}
            </div>
          </section>
          <fieldset className="planner-planning">
            <legend>Planning</legend>
            <div className="planner-field">
              <label htmlFor="planner-status">Draft status</label>
              <select id="planner-status" value={draft.status} disabled={readOnly || creating} aria-invalid={!!errors.status} aria-describedby={errors.status ? "status-error" : undefined} onChange={(event) => edit({ status: event.target.value as PlannerDraft["status"] })}>
                <option value="idea">Idea</option><option value="working">Working on it</option>
              </select>
              {creating && <p className="planner-help">New posts start as Idea. Change the status after creation.</p>}
              {errorFor("status")}
            </div>
            <div className="planner-field">
              <label htmlFor="planner-planned_date">Planned publishing date</label>
              <input id="planner-planned_date" type="date" value={draft.planned_date ?? ""} readOnly={readOnly} aria-invalid={!!errors.planned_date} aria-describedby={`planned-date-help${errors.planned_date ? " planned_date-error" : ""}`} onChange={(event) => edit({ planned_date: event.target.value || null })} />
              <p className="planner-help" id="planned-date-help">This is a planning date. Trendora will not publish automatically.</p>
              {errorFor("planned_date")}
            </div>
            <div className="planner-field">
              <label htmlFor="planner-assignee_id">Assignee</label>
              <select id="planner-assignee_id" value={draft.assignee_id ?? ""} disabled={readOnly || membersLoading || !!membersError} aria-invalid={!!errors.assignee_id} aria-describedby={errors.assignee_id ? "assignee_id-error" : undefined} onChange={(event) => edit({ assignee_id: event.target.value || null })}>
                <option value="">Unassigned</option>
                {historicalAssignee && <option value={historicalAssignee}>Existing assignee (not in active options)</option>}
                {members.map((member) => <option key={member.user_id} value={member.user_id}>{member.email}</option>)}
              </select>
              {membersLoading && <p className="planner-help" role="status">Loading active members…</p>}
              {historicalAssignee && <p className="planner-help">The existing assignment is retained until you choose another assignee.</p>}
              {membersError && <><p className="planner-field-error" role="alert">{membersError.message}</p><button className="secondary-button" type="button" onClick={() => { setMembersLoading(true); setMembersReload((value) => value + 1); }}>Retry assignment options</button></>}
              {errorFor("assignee_id")}
            </div>
            <div className="planner-field planner-notes">
              <label htmlFor="planner-notes">Notes</label>
              <textarea id="planner-notes" value={draft.notes} rows={5} readOnly={readOnly} aria-invalid={!!errors.notes} aria-describedby={errors.notes ? "notes-error" : undefined} onChange={(event) => edit({ notes: event.target.value })} />
              {errorFor("notes")}
            </div>
          </fieldset>
        </div>
        <div className="planner-actions">
          {!archived && <button className="primary-button" type="submit" disabled={state.busy || state.requiresReconcile || creationLocked || !creating && !state.dirty}>{creating ? "Create post" : "Save"}</button>}
          {saved && !archived && <button className="secondary-button" type="button" disabled={state.busy || state.requiresReconcile} onClick={archive}>Archive</button>}
          {saved && archived && <button className="primary-button" type="button" disabled={state.busy || state.requiresReconcile} onClick={() => void store.restore()}>Restore</button>}
        </div>
      </form>}
      <p className="planner-help">Unsaved edits and unresolved request details stay in this tab only. Browser Back/Forward may leave without warning. Reload and tab-close prompts depend on your browser.</p>
    </main>
  );
}
