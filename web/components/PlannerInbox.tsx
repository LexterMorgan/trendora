"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { Header } from "@/components/Header";
import { ApiErrorPanel, type ApiErrorState } from "@/components/ApiErrorPanel";
import { ResearchApiError } from "@/lib/api";
import { listPlannerPosts, type PlannerSummary } from "@/lib/planner-api";

const PAGE_SIZE = 20;
const timestamp = new Intl.DateTimeFormat("en-GB", {
  dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Jakarta",
});

export function PlannerInbox() {
  const [posts, setPosts] = useState<PlannerSummary[]>([]);
  const [archived, setArchived] = useState(false);
  const [offset, setOffset] = useState(0);
  const [reload, setReload] = useState(0);
  const [loading, setLoading] = useState(true);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState<ApiErrorState | null>(null);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    listPlannerPosts({ archived, limit: PAGE_SIZE + 1, offset, signal: controller.signal })
      .then((data) => {
        if (!active) return;
        setPosts(data.slice(0, PAGE_SIZE));
        setHasMore(data.length > PAGE_SIZE);
        setError(null);
      })
      .catch((failure) => {
        if (!active || failure?.name === "AbortError") return;
        setPosts([]);
        setError(failure instanceof ResearchApiError
          ? { code: failure.code, kind: failure.kind, message: failure.message }
          : { code: "unknown_error", message: "Could not load planner posts. Please retry." });
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [archived, offset, reload]);

  function changeView(value: boolean) {
    setLoading(true);
    setError(null);
    setOffset(0);
    setArchived(value);
    setReload((value) => value + 1);
  }

  function changePage(value: number) {
    setLoading(true);
    setError(null);
    setOffset(value);
  }

  function retry() {
    setLoading(true);
    setError(null);
    setReload((value) => value + 1);
  }

  return (
    <main className="workspace planner-workspace">
      <Header section="Shared planner" actionLink={{ href: "/past-reports", label: "Past reports" }} />
      <section className="planner-heading">
        <div>
          <h1>Shared planner</h1>
          <p>Plan posts together. Every active member can read and edit saved posts.</p>
        </div>
        <Link className="primary-button" href="/planner/new">New post</Link>
      </section>

      <div className="planner-toolbar" role="group" aria-label="Planner view">
        <button type="button" className="secondary-button" aria-pressed={!archived} onClick={() => changeView(false)}>Active</button>
        <button type="button" className="secondary-button" aria-pressed={archived} onClick={() => changeView(true)}>Archived</button>
      </div>

      {loading && <p className="loading-note" role="status">Loading {archived ? "archived" : "active"} posts…</p>}
      {!loading && error && (
        <ApiErrorPanel title="Could not load planner" error={error} onRetry={retry}>
          {error.kind !== "network" && error.kind !== "unavailable" && error.kind !== "unauthenticated" && error.kind !== "forbidden" && (
            <button type="button" className="secondary-button" onClick={retry}>Retry</button>
          )}
        </ApiErrorPanel>
      )}
      {!loading && !error && posts.length === 0 && (
        <section className="empty-state">
          <h2>{archived ? "No archived posts" : "No active posts yet"}</h2>
          <p>{archived ? "Archived posts stay available here. Open one to restore it." : "Create a post to add a title, draft copy, and a planning date."}</p>
          {!archived && <Link className="primary-button" href="/planner/new">Create a post</Link>}
        </section>
      )}
      {!loading && !error && posts.length > 0 && (
        <ul className="planner-list" aria-label={archived ? "Archived posts" : "Active posts"}>
          {posts.map((post) => (
            <li key={post.id}>
              <Link className="planner-row" href={`/planner/${encodeURIComponent(post.id)}`}>
                <div className="planner-row-title">
                  <strong>{post.title}</strong>
                  <span>{post.platform || "Platform not set"}</span>
                </div>
                <span className="planner-status">{post.status === "working" ? "Working on it" : "Idea"}</span>
                <span className="planner-row-date">{post.planned_date ? `Planned ${post.planned_date}` : "Not planned"}</span>
                <span className="planner-row-updated">Updated {timestamp.format(new Date(post.updated_at))} Jakarta</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {!loading && !error && (posts.length > 0 || offset > 0) && (
        <nav className="planner-pagination" aria-label="Planner pagination">
          <button type="button" className="secondary-button" disabled={offset === 0} onClick={() => changePage(Math.max(0, offset - PAGE_SIZE))}>Previous</button>
          <span>Page {Math.floor(offset / PAGE_SIZE) + 1}</span>
          <button type="button" className="secondary-button" disabled={!hasMore} onClick={() => changePage(offset + PAGE_SIZE)}>Next</button>
        </nav>
      )}
    </main>
  );
}
