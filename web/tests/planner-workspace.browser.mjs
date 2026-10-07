import assert from "node:assert/strict";

// Run against an owned Next copy with fictional auth and a shared mock API.
// The fixture uses the real browser SDK/session, never a mocked React workspace.
export function plannerWorkspaceRegressions(f) {
  const title = () => f.page.getByLabel("Title", { exact: true });
  const notes = () => f.page.getByLabel("Notes", { exact: true });
  const button = (name) => f.page.getByRole("button", { name, exact: true });
  const writes = () => f.calls.filter((c) => c.method === "POST" && c.path.endsWith("/posts"));
  const plannerMutations = () => f.calls.filter((c) => c.path?.startsWith("/api/v1/planner/") && ["POST", "PUT"].includes(c.method));
  const contentTools = () => f.page.locator(".report summary").filter({ hasText: /^Content tools \(optional\)$/ });
  const saved = () => f.page.locator(".planner-status-line").filter({ hasText: "Saved" }).waitFor();
  async function openContentTools() {
    const summary = contentTools();
    await summary.waitFor();
    if (!await summary.evaluate((element) => element.parentElement.open)) await summary.click();
    await f.page.getByRole("heading", { name: "Content ideas", exact: true }).waitFor();
  }
  async function create() {
    await f.newPost();
    await title().fill("Fictional shared original");
    await notes().fill("Original saved notes");
    await button("Create post").click();
    await saved();
    await f.waitFor(() => writes().length === 1);
    const id = [...f.records.keys()][0];
    assert.equal(new URL(f.page.url()).pathname, `/planner/${id}`);
    return id;
  }
  async function loadedByB(id) {
    await f.waitFor(() => f.calls.some((c) => c.actor === f.B && c.method === "GET" && c.path.endsWith(`/posts/${id}`)));
    await saved();
    assert.equal(new URL(f.page.url()).pathname, `/planner/${id}`);
    assert.equal(await title().inputValue(), "Fictional shared original");
    assert.equal(await button("Create post").count(), 0);
    assert.equal(writes().length, 1);
  }
  async function bSave(id, value, version) {
    await notes().fill(value);
    await button("Save").click();
    await saved();
    const put = f.calls.filter((c) => c.actor === f.B && c.method === "PUT").at(-1);
    assert.equal(put.path, `/api/v1/planner/posts/${id}`);
    assert.equal(put.body.expected_version, version);
    assert.equal(f.records.get(id).notes, value);
    assert.equal(writes().length, 1);
  }
  return [
    ["created route survives account remount and B saves the original ID", async () => {
      const id = await create();
      await notes().fill("A private unsaved text");
      await f.switchAccount(f.B);
      await loadedByB(id);
      assert.equal(await notes().inputValue(), "Original saved notes");
      await bSave(id, "B saved original record", 1);
      await f.page.reload();
      await saved();
      assert.equal(await notes().inputValue(), "B saved original record");
      assert.equal(await title().inputValue(), "Fictional shared original");
      assert.equal(writes().length, 1);
      await f.snapshot("account-remount");
    }],
    ["failed B detail load stays a saved route with GET-only retry", async () => {
      const id = await create();
      f.fault({ action: "get", mode: "reject", status: 503, code: "data_unavailable" });
      await f.switchAccount(f.B);
      await button("Retry loading post").waitFor();
      assert.equal(new URL(f.page.url()).pathname, `/planner/${id}`);
      assert.equal(await button("Create post").count(), 0);
      assert.equal(await title().count(), 0);
      await f.snapshot("detail-error");
      await button("Retry loading post").click();
      await loadedByB(id);
      await bSave(id, "B recovered original record", 1);
    }],
    ["known creation ID promotes even when its detail GET fails", async () => {
      await f.newPost();
      await title().fill("Fictional known ID");
      f.fault({ action: "get", mode: "reject", status: 503, code: "data_unavailable" });
      await button("Create post").click();
      await button("Retry loading created post").waitFor();
      const id = [...f.records.keys()][0];
      assert.equal(new URL(f.page.url()).pathname, `/planner/${id}`);
      await button("Retry loading created post").click();
      await saved();
      assert.equal(writes().length, 1);
      assert.equal(await title().inputValue(), "Fictional known ID");
    }],
    ["creation promotion and delayed save retain newer same-account edits", async () => {
      await f.newPost();
      await title().fill("Fictional shared original");
      await f.page.evaluate(() => {
        const replace = history.replaceState.bind(history);
        let pending;
        history.replaceState = (...args) => {
          if (String(args[2]).match(/^\/planner\/(?!new$)/)) pending = args;
          else replace(...args);
        };
        window.flushPlannerPromotion = () => {
          history.replaceState = replace;
          replace(...pending);
        };
      });
      await button("Create post").click();
      await saved();
      await notes().fill("Typed before route promotion");
      await f.page.evaluate(() => window.flushPlannerPromotion());
      await button("Save").waitFor();
      await f.page.locator(".planner-status-line").filter({ hasText: "Unsaved changes" }).waitFor();
      const id = [...f.records.keys()][0];
      assert.equal(new URL(f.page.url()).pathname, `/planner/${id}`);
      assert.equal(await notes().inputValue(), "Typed before route promotion");
      f.fault({ action: "update", mode: "delay-after" });
      await button("Save").click();
      await f.stalled();
      await notes().fill("Newer edit during save");
      await f.release();
      await f.page.locator(".planner-status-line").filter({ hasText: "Unsaved changes" }).waitFor();
      assert.equal(await notes().inputValue(), "Newer edit during save");
      assert.equal(f.records.get(id).notes, "Typed before route promotion");
      assert.equal(f.calls.filter((c) => c.method === "PUT").length, 1);
      assert.equal(f.calls.filter((c) => c.method === "GET" && c.path.endsWith(`/posts/${id}`)).length, 1);
    }],
    ["late A response cannot restore unsaved text or recovery in B", async () => {
      const id = await create();
      await notes().fill("A submitted shared text");
      f.fault({ action: "update", mode: "delay-after" });
      await button("Save").click();
      await f.stalled();
      await notes().fill("A private newer text");
      await f.switchAccount(f.B);
      await loadedByB(id);
      assert.equal(await notes().inputValue(), "A submitted shared text");
      await notes().fill("B private newer text");
      await f.release();
      await f.page.waitForTimeout(200);
      assert.equal(await notes().inputValue(), "B private newer text");
      assert.equal(await button("Check latest server state").count(), 0);
      assert.equal(await button("Save").isEnabled(), true);
      await bSave(id, "B final shared text", 2);
    }],
    ["lost creation acknowledgement retries the frozen payload and key", async () => {
      await f.newPost();
      await title().fill("Fictional frozen creation");
      f.fault({ action: "create", mode: "drop-after" });
      await button("Create post").click();
      await button("Retry same creation").waitFor();
      assert.equal(await notes().getAttribute("readonly"), "");
      await button("Retry same creation").click();
      await button("Save").waitFor();
      assert.equal(writes().length, 2);
      assert.deepEqual(writes()[1].body, writes()[0].body);
      assert.equal(f.records.size, 1);
      assert.equal(await title().inputValue(), "Fictional frozen creation");
    }],
    ["version conflict retains text and requires an explicit recovery choice", async () => {
      const id = await create();
      f.records.set(id, { ...f.records.get(id), version: 2, notes: "Concurrent shared edit", updated_by: f.B });
      await notes().fill("A retained local conflict text");
      await button("Save").click();
      await f.page.getByRole("heading", { name: "This post has changed", exact: true }).waitFor();
      assert.equal(await button("Save").isDisabled(), true);
      await button("Check latest server state").click();
      await button("Keep my edits, use latest version").waitFor();
      const count = f.calls.filter((c) => c.method === "PUT").length;
      await button("Keep my edits, use latest version").click();
      assert.equal(f.calls.filter((c) => c.method === "PUT").length, count);
      assert.equal(await notes().inputValue(), "A retained local conflict text");
      await button("Save").click();
      await saved();
      assert.equal(f.calls.filter((c) => c.method === "PUT").at(-1).body.expected_version, 2);
    }],
    ["360px Home breadcrumb has a 44px target and visible keyboard focus", async () => {
      await f.page.setViewportSize({ width: 360, height: 800 });
      await f.newPost();
      const home = f.page.locator(".breadcrumb-home");
      await f.page.keyboard.press("Tab");
      await home.focus();
      await f.snapshot("home-360");
      const rect = await home.boundingBox();
      assert(rect.width >= 44 && rect.height >= 44, `Home target ${rect.width}×${rect.height}`);
      assert.notEqual(await home.evaluate((e) => getComputedStyle(e).outlineStyle), "none");
      await f.metrics("home-360");
      await f.page.keyboard.press("Enter");
      await f.page.waitForURL(f.origin + "/");
    }],
    ["360px validation targets are spaced, wrap and activate fields by keyboard", async () => {
      await f.page.setViewportSize({ width: 360, height: 800 });
      await f.newPost();
      await f.page.getByLabel("Asset links", { exact: true }).fill("invalid-link");
      await button("Create post").click();
      await f.page.waitForFunction(() => document.activeElement?.classList.contains("planner-validation"));
      await f.page.keyboard.press("Tab");
      const anchors = f.page.locator(".planner-validation a");
      assert.equal(await anchors.count(), 2);
      const rects = await anchors.evaluateAll((elements) => elements.map((e) => {
        const r = e.getBoundingClientRect();
        return { width: r.width, height: r.height, top: r.top, bottom: r.bottom, text: e.textContent };
      }));
      await f.snapshot("validation-360");
      for (const r of rects) assert(r.width >= 44 && r.height >= 44, `Validation target ${r.width}×${r.height}`);
      assert(rects[1].top - rects[0].bottom >= 8);
      assert.notEqual(await anchors.first().evaluate((e) => getComputedStyle(e).outlineStyle), "none");
      await f.page.keyboard.press("Enter");
      assert.equal(await f.page.evaluate(() => document.activeElement.id), "planner-title");
      await anchors.last().focus();
      await f.page.keyboard.press("Enter");
      assert.equal(await f.page.evaluate(() => document.activeElement.id), "planner-asset_links");
      await f.metrics("validation-360");
    }],
    ["planner reflows without clipped controls at 360, 768, 1440 and zoom equivalent", async () => {
      await create();
      for (const width of [360, 768, 1440, 720]) {
        await f.page.setViewportSize({ width, height: width === 720 ? 500 : 900 });
        await f.metrics(`workspace-${width}`);
        await f.snapshot(`workspace-${width}`);
      }
      const columns = await f.page.locator(".planner-form").evaluate((e) => getComputedStyle(e).gridTemplateColumns);
      assert.equal(columns.split(" ").length, 1, "1440px / 200% equivalent must use one form column");
    }],
    ["account remount clears A recovery snapshot and unsaved text", async () => {
      const id = await create();
      await notes().fill("A committed uncertain text");
      f.fault({ action: "update", mode: "drop-after" });
      await button("Save").click();
      await button("Check latest server state").waitFor();
      await button("Check latest server state").click();
      await button("Keep my edits, use latest version").waitFor();
      await notes().fill("A private recovery text");
      await f.switchAccount(f.B);
      await loadedByB(id);
      assert.equal(await notes().inputValue(), "A committed uncertain text");
      assert.equal(await button("Check latest server state").count(), 0);
      assert.equal(await button("Keep my edits, use latest version").count(), 0);
      await bSave(id, "B after A recovery reset", 2);
    }],
    ["P3 report save failure shows a retryable state and retry reuses one key", async () => {
      await f.openResearch();
      await f.submitResearch("Fictional research topic");
      await f.page.getByText("This report was not saved.", { exact: true }).waitFor();
      assert.equal(await button("Save to Planner").count(), 0);
      f.fault({ action: "save", mode: "drop-after" });
      await button("Save report").click();
      await button("Retry saving report").waitFor();
      await button("Retry saving report").click();
      await f.page.getByText("Saved to history.", { exact: true }).waitFor();
      const saves = f.calls.filter((c) => c.path === "/api/v1/research/reports/save");
      assert.equal(saves.length, 2);
      assert.deepEqual(saves[1].body, saves[0].body, "retry must reuse the frozen key and snapshot");
      assert.match(saves[0].body.recovery_receipt, /^fictional-opaque\./);
      assert.equal("recovery_receipt" in saves[0].body.snapshot, false);
      assert.equal(f.calls.filter((c) => c.path === "/api/v1/research/report").length, 1);
      await openContentTools();
      await button("Save to Planner").first().click();
      await button("Open post").waitFor();
      const imported = f.calls.find((c) => c.path === "/api/v1/planner/posts/import");
      assert.equal(imported.body.report_id, [...f.reports.keys()][0], "import must use the recovered canonical report ID");
      assert.equal(f.reports.size, 1);
      await button("Open post").click();
      await saved();
      assert.equal(new URL(f.page.url()).pathname, `/planner/${[...f.records.keys()][0]}`);
      assert.equal(await title().inputValue(), "Fictional import idea");
      await f.snapshot("recovery-import");
    }],
    ["P3 oversized report cannot be retried and stays visible", async () => {
      await f.openResearch();
      await f.submitResearch("Fictional oversized topic", { oversized: true });
      await button("Save report").click();
      await f.page.getByText(/too large to save/).waitFor();
      assert.equal(await button("Retry saving report").count(), 0);
      assert.equal(await f.page.getByRole("button", { name: "Save report", exact: true }).count(), 0);
      assert.equal(f.calls.filter((c) => c.path === "/api/v1/research/reports/save").length, 0);
      await openContentTools();
      assert.equal(await f.page.getByText("Fictional import idea", { exact: true }).isVisible(), true);
    }],
    ["P3 save to planner opens the canonical post and never duplicates on retry", async () => {
      const reportId = await f.seedSavedReport();
      await f.openResearch();
      await openContentTools();
      await button("Save to Planner").first().click();
      await button("Open post").waitFor();
      await f.page.getByRole("button", { name: "Open post", exact: true }).click();
      await saved();
      const imports = f.calls.filter((c) => c.path === "/api/v1/planner/posts/import");
      assert.equal(imports.length, 1);
      assert.equal(imports[0].body.report_id, reportId);
      assert.equal(f.records.size, 1);
      assert.equal(new URL(f.page.url()).pathname, `/planner/${[...f.records.keys()][0]}`);
    }],
    ["P3 account switch drops a delayed save response", async () => {
      await f.openResearch();
      await f.submitResearch("Fictional topic");
      f.fault({ action: "save", mode: "delay-after" });
      await button("Save report").click();
      await f.stalled();
      await f.switchAccount(f.B);
      await f.page.getByRole("button", { name: "Generate research report", exact: true }).waitFor();
      await f.page.getByLabel("Topic", { exact: true }).fill("B private text");
      await f.release();
      await f.page.waitForTimeout(200);
      assert.equal(await f.page.getByText("Saved to history.").count(), 0);
      assert.equal(await button("Open post").count(), 0);
      assert.equal(await f.page.getByLabel("Topic", { exact: true }).inputValue(), "B private text");
    }],
    ["P3 import is refused when the report is outside history access", async () => {
      await f.seedSavedReport({ outOfHistory: true });
      await f.openResearch();
      await openContentTools();
      await button("Save to Planner").first().click();
      await f.page.getByText(/no longer available to import/).waitFor();
      assert.equal(await button("Retry").count(), 0);
      assert.equal(await button("Save to Planner").first().isDisabled(), true);
      assert.equal(f.calls.filter((c) => c.path === "/api/v1/planner/posts/import").length, 1);
      assert.equal(f.records.size, 0);
    }],
    ["P3 terminal report errors leave content visible and offer no retry", async () => {
      for (const [code, status] of [["report_request_too_large", 413], ["invalid_report_snapshot", 422], ["report_save_conflict", 409], ["report_expired", 410]]) {
        await f.openResearch(); await f.submitResearch(`Fictional ${code}`);
        f.fault({ action: "save", mode: "reject", code, status });
        await button("Save report").click();
        await f.page.locator(".persistence-too-large").waitFor();
        assert.equal(await button("Save report").count(), 0);
        assert.equal(await button("Retry saving report").count(), 0);
        await openContentTools();
        assert.equal(await f.page.getByText("Fictional import idea", { exact: true }).isVisible(), true);
      }
      assert.equal(f.calls.filter((c) => c.path === "/api/v1/research/reports/save").length, 4);
    }],
    ["P3 secure fallback gives independent imports distinct keys and retries one frozen key", async () => {
      await f.seedSavedReport(); await f.openResearch(); await f.randomness("fallback");
      await openContentTools();
      f.fault({ action: "import", mode: "drop-after" });
      await button("Save to Planner").first().click(); await button("Retry").waitFor();
      await button("Retry").click(); await button("Open post").waitFor();
      await button("Save to Planner").click(); await f.waitFor(async () => await button("Open post").count() === 2);
      const imports = f.calls.filter((c) => c.path === "/api/v1/planner/posts/import");
      assert.equal(imports.length, 3);
      assert.deepEqual(imports[1].body, imports[0].body);
      assert.notEqual(imports[2].body.request_id, imports[0].body.request_id);
      for (const call of imports) assert.match(call.body.request_id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
      assert.equal(f.records.size, 2);
    }],
    ["P3 unavailable secure randomness blocks recovery and import with clear errors", async () => {
      await f.openResearch(); await f.submitResearch("Fictional missing randomness", { missingKey: true });
      await f.randomness("none"); await button("Save report").click();
      await f.page.getByText(/Secure randomness is unavailable/).waitFor();
      assert.equal(f.calls.filter((c) => c.path === "/api/v1/research/reports/save").length, 0);
      assert.equal(await button("Save report").isEnabled(), true);
      await button("Save report").click();
      assert.equal(f.calls.filter((c) => c.path === "/api/v1/research/reports/save").length, 0);
      await f.seedSavedReport(); await f.openResearch();
      await f.page.getByText("Saved to history.", { exact: true }).waitFor();
      await openContentTools();
      await button("Save to Planner").first().click();
      await f.page.getByText(/Secure randomness is unavailable/).waitFor();
      assert.equal(f.calls.filter((c) => c.path === "/api/v1/planner/posts/import").length, 0);
      assert.equal(await button("Save to Planner").first().isEnabled(), true);
      await f.snapshot("secure-randomness-refusal");
    }],
    ["P3 account switch discards a delayed import without restoring A state", async () => {
      const reportId = await f.seedSavedReport(); await f.openResearch();
      await openContentTools();
      f.fault({ action: "import", mode: "delay-after" });
      await button("Save to Planner").first().click(); await f.stalled();
      await f.switchAccount(f.B);
      await openContentTools();
      await button("Save to Planner").first().waitFor();
      await f.release(); await f.page.waitForTimeout(200);
      assert.equal(await button("Open post").count(), 0);
      assert.equal(await button("Saved").count(), 0);
      await button("Save to Planner").first().click(); await button("Open post").waitFor();
      const imports = f.calls.filter((c) => c.path === "/api/v1/planner/posts/import");
      assert.equal(imports.length, 2); assert.equal(imports[1].actor, f.B);
      assert.equal(imports[1].body.report_id, reportId);
      assert.notEqual(imports[1].body.request_id, imports[0].body.request_id);
    }],
    ["P4 fresh and saved reports lead with research and disclosure never mutates the planner", async () => {
      for (const kind of ["fresh", "saved"]) {
        if (kind === "saved") await f.seedSavedReport({ researchFirst: true, topic: "Fictional saved research" });
        await f.openResearch();
        if (kind === "fresh") await f.submitResearch("Fictional fresh research", { researchFirst: true });
        const findings = f.page.getByRole("heading", { name: "Research findings", exact: true });
        assert.equal(await findings.isVisible(), true);
        assert.equal(await f.page.getByText(kind === "fresh" ? "Fictional sourced synthesis fictional-1: context from collected source material." : "Fictional interpretation", { exact: true }).first().isVisible(), true);
        assert.equal(await f.page.getByText("AI interpretation", { exact: true }).first().isVisible(), true);
        assert.equal(await f.page.locator(".reference-card").first().isVisible(), true);
        assert.equal(await f.page.getByRole("heading", { name: "Source coverage", exact: true }).isVisible(), true);
        assert.match(await f.page.locator(".report").innerText(), /Requested timeframe: 2026-08-01 to 2026-08-31/);
        assert.match(await f.page.locator(".report").innerText(), /References: 3/);
        assert.equal(await contentTools().evaluate((element) => element.parentElement.open), false);
        assert.equal(await f.page.getByText("Fictional import idea", { exact: true }).isVisible(), false);
        const order = await f.page.locator(".report").evaluate((report) => {
          const summary = [...report.querySelectorAll("summary")].find((element) => element.textContent === "Content tools (optional)");
          const findings = [...report.querySelectorAll("h2,h3,h4")].find((element) => element.textContent === "Research findings");
          const source = report.querySelector(".reference-card");
          const coverage = report.querySelector(".coverage-panel");
          return [findings, source, coverage].every((element) => element && summary && Boolean(element.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING));
        });
        assert.equal(order, true, "Findings, sources and coverage must precede optional tools in document order");
        await f.page.getByText(kind === "saved" ? "Saved to history." : "This report was not saved.", { exact: true }).waitFor();
        assert.equal(plannerMutations().length, 0);
        await openContentTools();
        assert.equal(await f.page.getByText("Fictional import idea", { exact: true }).isVisible(), true);
        assert.equal(plannerMutations().length, 0, "Opening content tools is a read, not a planner action");
        await f.snapshot(`research-first-${kind}`);
      }
    }],
    ["P4 sourcing preserves citation URLs, distinct dates, sample counts and coverage gaps", async () => {
      await f.seedSavedReport({ researchFirst: true }); await f.openResearch();
      const source = (title) => f.page.locator(".reference-card").filter({ has: f.page.getByRole("heading", { name: title, exact: true }) });
      const inWindow = source("Fictional in-window source"), outside = source("Fictional outside-window source"), undated = source("Fictional undated web source");
      assert.equal(await inWindow.getByRole("link", { name: "View original", exact: true }).getAttribute("href"), "https://example.test/fictional");
      assert.match(await inWindow.innerText(), /Published[^\n]*Aug 12, 2026/);
      assert.match(await outside.innerText(), /Published[^\n]*Jul 31, 2026/);
      for (const card of [inWindow, outside, undated]) assert.match(await card.innerText(), /Collected[^\n]*Oct 1, 2026/);
      assert.equal(await undated.getByText("Publication date unknown", { exact: true }).isVisible(), true);
      assert.equal(await f.page.getByText("Public-web results were not verified against the requested timeframe.", { exact: true }).isVisible(), true);
      assert.equal(await f.page.getByText("Timeframe coverage is unverified.", { exact: false }).first().isVisible(), true);
      assert.equal(await inWindow.locator(".metric").filter({ hasText: "Views" }).locator("dd").innerText(), "0");
      assert.equal(await inWindow.locator(".metric").filter({ hasText: "Likes" }).locator("dd").innerText(), "Unknown");
      assert.match(await inWindow.innerText(), /Counts observed at collection, not a measure of growth/);
      const coverage = f.page.locator(".coverage-panel");
      assert.equal(await coverage.getByText(/Fictional Page access unavailable/).isVisible(), true);
      assert.equal(await coverage.locator('[data-searched="true"]').count(), 2);
      assert.equal(await coverage.locator('[data-searched="false"]').count(), 1);
      const patterns = f.page.locator(".report summary").filter({ hasText: /^Evidence patterns/ });
      if (!await patterns.evaluate((element) => element.parentElement.open)) await patterns.click();
      assert.equal(await f.page.locator(".pattern-counts").innerText(), "1/3 matching");
      assert.match(await f.page.locator(".report").innerText(), /prevalence/i);
      assert.equal(await f.page.getByText("No measured trend evidence is available in this report.", { exact: false }).isVisible(), true);
      const citation = button("Trace 1 citation").first();
      await citation.focus(); await f.page.keyboard.press("Enter");
      const drawer = f.page.getByRole("dialog", { name: "Citation trace", exact: true });
      await drawer.waitFor();
      assert.match(await drawer.innerText(), /youtube:fictional-1/);
      assert.equal(await drawer.getByRole("link", { name: "View original", exact: true }).getAttribute("href"), "https://example.test/fictional");
      await f.page.keyboard.press("Escape");
      assert.equal(await drawer.count(), 0);
      assert.equal(plannerMutations().length, 0);
      await f.snapshot("research-dates-coverage");
    }],
    ["P4 legacy and no-evidence reports show missing data without inventing findings", async () => {
      for (const noEvidence of [false, true]) {
        await f.seedSavedReport({ legacy: true, noEvidence }); await f.openResearch();
        assert.equal(await f.page.getByText("No research findings are available in this report.", { exact: true }).isVisible(), true);
        assert.equal(await f.page.getByText("Fictional interpretation", { exact: true }).count(), 0);
        assert.match(await f.page.locator(".coverage-panel").innerText(), /unknown|unavailable/i);
        await f.page.getByText("Saved to history.", { exact: true }).waitFor();
        if (!noEvidence) {
          assert.equal(await f.page.getByText("Publication date unknown", { exact: true }).isVisible(), true);
          assert.equal(await f.page.getByText("Collection date unknown", { exact: true }).isVisible(), true);
          assert.equal(await contentTools().evaluate((element) => element.parentElement.open), false);
          await openContentTools();
          assert.equal(await f.page.getByText("Fictional import idea", { exact: true }).isVisible(), true);
          assert.equal(await f.page.getByText("No research findings are available in this report.", { exact: true }).isVisible(), true);
        } else {
          assert.equal(await f.page.locator(".reference-card").count(), 0);
          assert.equal(await button("Save to Planner").count(), 0);
        }
        assert.equal(plannerMutations().length, 0);
        await f.snapshot(noEvidence ? "research-no-evidence" : "research-legacy");
      }
    }],
    ["P4 report disclosures work by keyboard and reflow at mobile and zoom-equivalent widths", async () => {
      await f.seedSavedReport({ researchFirst: true }); await f.openResearch();
      await f.page.setViewportSize({ width: 360, height: 800 });
      const summary = contentTools();
      await f.page.keyboard.press("Tab"); await summary.focus();
      assert.equal(await summary.evaluate((element) => element === document.activeElement), true);
      assert.notEqual(await summary.evaluate((element) => getComputedStyle(element).outlineStyle), "none");
      await f.page.keyboard.press("Enter");
      assert.equal(await summary.evaluate((element) => element.parentElement.open), true);
      assert.equal(await f.page.getByText("Fictional import idea", { exact: true }).isVisible(), true);
      await f.page.keyboard.press("Space");
      assert.equal(await summary.evaluate((element) => element.parentElement.open), false);
      assert.equal(plannerMutations().length, 0);
      for (const width of [360, 768, 1440, 720]) {
        await f.page.setViewportSize({ width, height: width === 720 ? 500 : 900 });
        await f.metrics(`research-${width}`); await f.snapshot(`research-${width}`);
      }
      await openContentTools();
      await f.page.setViewportSize({ width: 360, height: 800 });
      await f.metrics("research-tools-360"); await f.snapshot("research-tools-360");
      assert.equal(plannerMutations().length, 0);
    }],
    ["Final research-only default preserves sourced findings and invokes no optional stages", async () => {
      await f.openResearch();
      const optIn = f.page.getByRole("checkbox", { name: "Include content ideas and briefs", exact: true });
      assert.equal(await optIn.isChecked(), false);
      await f.submitResearch("Fictional independent research", { researchOnly: true, researchFirst: true });
      const generated = f.calls.find((call) => call.path === "/api/v1/research/report");
      assert.equal(generated.body.include_content_tools, false);
      assert.deepEqual(f.optionalCalls, []);
      assert.deepEqual(f.interpretationCalls, ["interpretation"]);
      assert.equal(await f.page.getByText("Fictional sourced synthesis fictional-1: context from collected source material.", { exact: true }).isVisible(), true);
      assert.equal(await f.page.getByText("Source-attributed excerpt", { exact: true }).count(), 0);
      assert.equal(await f.page.locator('[data-finding-scope="in_window"]').count(), 1);
      assert.equal(await f.page.locator('[data-finding-scope="outside_window"]').count(), 1);
      assert.equal(await f.page.locator('[data-finding-scope="undated"]').count(), 1);
      assert.match(await f.page.locator(".report").innerText(), /Event dates are unavailable/);
      await button("Trace 1 citation").first().click();
      const drawer = f.page.getByRole("dialog", { name: "Citation trace", exact: true });
      assert.equal(await drawer.getByRole("link", { name: "View original", exact: true }).getAttribute("href"), "https://example.test/fictional");
      await f.page.keyboard.press("Escape");
      await openContentTools();
      assert.equal(await f.page.getByText("Content tools were not generated for this report.", { exact: true }).isVisible(), true);
      assert.equal(await button("Save to Planner").count(), 0);
      assert.equal(plannerMutations().length, 0);
      await button("Save report").click();
      await f.page.getByText("Saved to history.", { exact: true }).waitFor();
      const [id] = f.reports.keys();
      await f.page.goto(f.origin + `/report/${id}`);
      await f.page.locator('[data-finding-scope="in_window"]').waitFor();
      assert.equal(await f.page.locator('[data-finding-scope="outside_window"]').count(), 1);
      assert.equal(plannerMutations().length, 0);
      await f.snapshot("research-only-reopened");
    }],
    ["Final optional content failure preserves research and stable save recovery", async () => {
      await f.openResearch();
      await f.submitResearch("Fictional optional outage", { contentUnavailable: true });
      assert.equal(f.calls.find((call) => call.path === "/api/v1/research/report").body.include_content_tools, true);
      assert.deepEqual(f.optionalCalls, ["strategy"]);
      assert.equal(await f.page.getByText("Fictional sourced synthesis fictional-1: context from collected source material.", { exact: true }).isVisible(), true);
      await openContentTools();
      await f.page.getByText("Content generation is unavailable. Your research is preserved and can be saved.", { exact: true }).waitFor();
      assert.equal(plannerMutations().length, 0);
      f.fault({ action: "save", mode: "drop-after" });
      await button("Save report").click(); await button("Retry saving report").waitFor();
      await button("Retry saving report").click(); await f.page.getByText("Saved to history.", { exact: true }).waitFor();
      const saves = f.calls.filter((call) => call.path === "/api/v1/research/reports/save");
      assert.equal(saves.length, 2); assert.deepEqual(saves[0].body, saves[1].body);
      assert.equal(saves[0].body.snapshot.status, "content_unavailable");
      assert.equal(saves[0].body.snapshot.ideation, null);
      assert.equal(f.reports.size, 1);
      await f.snapshot("optional-content-failure");
    }],
    ["Corrected synthesis failures retain labelled excerpts, date context and stable save recovery", async () => {
      for (const reason of ["unavailable", "malformed", "grounding"]) {
        const interpretationCount = f.interpretationCalls.length;
        const saveCount = f.calls.filter((call) => call.path === "/api/v1/research/reports/save").length;
        await f.openResearch();
        await f.submitResearch(`Fictional ${reason} synthesis`, { researchOnly: true, researchFirst: true, interpretationFailure: reason });
        assert.deepEqual(f.optionalCalls, []);
        assert.equal(f.interpretationCalls.length - interpretationCount, reason === "malformed" ? 2 : 1);
        assert.equal(await f.page.getByText("Source-attributed excerpt", { exact: true }).count(), 3);
        assert.equal(await f.page.getByText("“Fictional evidence”", { exact: true }).first().isVisible(), true);
        assert.equal(await f.page.getByText(/These are source-attributed excerpts, not synthesized findings/).isVisible(), true);
        assert.equal(await f.page.getByText(/Fictional sourced synthesis fictional-1:/).count(), 0);
        for (const scope of ["in_window", "outside_window", "undated"]) {
          const finding = f.page.locator(`[data-finding-scope="${scope}"]`);
          assert.equal(await finding.count(), 1);
          assert.equal(await finding.isVisible(), true);
        }
        await button("Trace 1 citation").first().click();
        const drawer = f.page.getByRole("dialog", { name: "Citation trace", exact: true });
        assert.equal(await drawer.getByRole("link", { name: "View original", exact: true }).getAttribute("href"), "https://example.test/fictional");
        await f.page.keyboard.press("Escape");
        f.fault({ action: "save", mode: "drop-after" });
        await button("Save report").click(); await button("Retry saving report").waitFor();
        await button("Retry saving report").click(); await f.page.getByText("Saved to history.", { exact: true }).waitFor();
        const saves = f.calls.filter((call) => call.path === "/api/v1/research/reports/save").slice(saveCount);
        assert.equal(saves.length, 2); assert.deepEqual(saves[0].body, saves[1].body);
        assert.match(saves[0].body.recovery_receipt, /^fictional-opaque\./);
        assert.equal("recovery_receipt" in saves[0].body.snapshot, false);
        assert.equal(saves[0].body.snapshot.interpretation.model_provenance.provider, "source_evidence");
        assert.equal(saves[0].body.snapshot.strategy, null); assert.equal(saves[0].body.snapshot.ideation, null);
        const savedId = [...f.reports.keys()].at(-1);
        await f.page.goto(f.origin + `/report/${savedId}`);
        await f.page.getByText("Saved to history.", { exact: true }).waitFor();
        assert.equal(await f.page.getByText("Source-attributed excerpt", { exact: true }).count(), 3);
        assert.equal(plannerMutations().length, 0);
        await f.snapshot(`synthesis-fallback-${reason}`);
      }
    }],
    ["Final insufficient and unavailable summaries retain evidence without fabricated findings", async () => {
      for (const options of [{ insufficient: true }, { researchUnavailable: true }]) {
        await f.seedSavedReport(options); await f.openResearch();
        assert.equal(await f.page.getByText("No research findings are available in this report.", { exact: true }).isVisible(), true);
        assert.equal(await f.page.locator("[data-finding-scope]").count(), 0);
        assert.equal(await f.page.locator(".reference-card").count(), 1);
        assert.equal(await f.page.getByText("Saved to history.", { exact: true }).isVisible(), true);
        assert.match(await f.page.locator(".report").innerText(), options.insufficient ? /Insufficient source text/ : /Sourced summaries are unavailable/);
        assert.equal(plannerMutations().length, 0);
      }
    }],
    ["Final delayed generation cannot restore an old account’s research or optional selection", async () => {
      await f.openResearch();
      f.fault({ action: "generate", mode: "delay-after" });
      await f.page.getByLabel("Topic", { exact: true }).fill("A research");
      await f.page.getByRole("checkbox", { name: "Include content ideas and briefs", exact: true }).check();
      await button("Generate research report").click(); await f.stalled();
      await f.switchAccount(f.B);
      await button("Generate research report").waitFor();
      await f.page.getByLabel("Topic", { exact: true }).fill("B unsaved research");
      assert.equal(await f.page.getByRole("checkbox", { name: "Include content ideas and briefs", exact: true }).isChecked(), false);
      await f.release();
      await f.page.waitForTimeout(100);
      assert.equal(await f.page.locator(".report").count(), 0);
      assert.equal(await f.page.getByLabel("Topic", { exact: true }).inputValue(), "B unsaved research");
      assert.equal(plannerMutations().length, 0);
    }],
    ["Final research-only and opt-in controls remain keyboard accessible at mobile width", async () => {
      await f.openResearch(); await f.page.setViewportSize({ width: 360, height: 800 });
      const optIn = f.page.getByRole("checkbox", { name: "Include content ideas and briefs", exact: true });
      await optIn.focus(); await f.page.keyboard.press("Space"); assert.equal(await optIn.isChecked(), true);
      await f.page.keyboard.press("Space"); assert.equal(await optIn.isChecked(), false);
      await f.metrics("research-request-360");
      await f.submitResearch("Fictional mobile research", { researchOnly: true, researchFirst: true });
      await f.metrics("research-only-360");
      await contentTools().focus(); await f.page.keyboard.press("Enter");
      assert.equal(await contentTools().evaluate((element) => element.parentElement.open), true);
      assert.equal(plannerMutations().length, 0);
      await f.snapshot("final-research-360");
    }],
  ];
}
