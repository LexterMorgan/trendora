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
  const expandSource = (card) => card.locator("details.reference-details").evaluate((element) => { element.open = true; });
  const scopeSummary = () => f.page.locator(".report summary").filter({ hasText: /^Scope and coverage details$/ });
  // Screenshots must show the settled page: the entrance animation fills
  // backwards, so an early capture is legitimately invisible.
  const settleAnimations = () => f.page.evaluate(() => Promise.all(
    document.getAnimations().map((animation) => animation.finished.catch(() => {})),
  ));
  async function openScopeDetails() {
    const summary = scopeSummary();
    await summary.waitFor();
    if (!await summary.evaluate((element) => element.parentElement.open)) await summary.click();
    await f.page.getByRole("heading", { name: "Source coverage", exact: true }).waitFor();
  }
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
    ["360px home link has a 44px target and visible keyboard focus", async () => {
      await f.page.setViewportSize({ width: 360, height: 800 });
      await f.newPost();
      const home = f.page.locator(".brand-link");
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
    ["planner reflows without clipped controls at 360, 768, 1440 and narrow-viewport widths", async () => {
      await create();
      for (const width of [360, 768, 1440, 720]) {
        await f.page.setViewportSize({ width, height: width === 720 ? 500 : 900 });
        await f.metrics(`workspace-${width}`);
        await f.snapshot(`workspace-${width}`);
      }
      const columns = await f.page.locator(".planner-form").evaluate((e) => getComputedStyle(e).gridTemplateColumns);
      assert.equal(columns.split(" ").length, 1, "the narrow 720px viewport must use one form column");
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
        assert.equal(await scopeSummary().isVisible(), true, "Scope essentials stay reachable while the details are closed");
        assert.equal(await scopeSummary().evaluate((element) => element.parentElement.open), false);
        await openScopeDetails();
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
    ["Report source library expands, keeps counts, and reflows at mobile width", async () => {
      await f.seedSavedReport({ manySources: 8 }); await f.openResearch();
      const cards = f.page.locator(".reference-card");
      const expand = button("Show all 8 sources");
      assert.equal(await f.page.locator(".reference-card:visible").count(), 6, "Only the first six sources show before expanding");
      assert.equal(await expand.getAttribute("aria-expanded"), "false");
      await expand.click();
      assert.equal(await f.page.locator(".reference-card:visible").count(), 8, "Expanding reveals every source");
      assert.equal(await cards.count(), 8);
      assert.equal(plannerMutations().length, 0);
      await f.page.setViewportSize({ width: 360, height: 800 });
      await f.metrics("source-library-360");
      await f.snapshot("source-library-expanded");
    }],
    ["Source filters intersect title, hostname platform and date, then reset honestly", async () => {
      await f.seedSavedReport({ mixedPlatforms: true, topic: "Fictional filter report" }); await f.openResearch();
      const search = f.page.getByLabel("Search source titles", { exact: true });
      const platform = f.page.locator(".reference-controls select").nth(0);
      const date = f.page.locator(".reference-controls select").nth(1);
      const visible = () => f.page.locator(".reference-card:visible").count();
      const count = f.page.locator(".reference-result-count");
      assert.equal(await visible(), 4);
      assert.equal(await count.innerText(), "4 sources.");
      await search.fill("reddit");
      assert.equal(await visible(), 2, "A suffix-spoofed host must not become Reddit");
      assert.equal(await count.innerText(), "2 of 4 sources match.");
      await platform.selectOption("Reddit");
      assert.equal(await visible(), 1);
      await date.selectOption("undated");
      assert.equal(await visible(), 1, "The real Reddit source has no valid publication day");
      await search.fill("spoof");
      assert.equal(await visible(), 0);
      assert.equal(await f.page.getByText(/No sources match these filters/).isVisible(), true);
      await platform.selectOption("Other / unknown");
      assert.equal(await visible(), 1);
      await date.selectOption("dated");
      assert.equal(await visible(), 0, "An impossible calendar date stays undated");
      await button("Reset filters").click();
      assert.equal(await visible(), 4);
      assert.equal(await count.innerText(), "4 sources.");
      assert.equal(await search.inputValue(), "");
      assert.equal(plannerMutations().length, 0);
      await f.page.setViewportSize({ width: 360, height: 900 });
      await search.focus();
      assert.notEqual(await search.evaluate((element) => getComputedStyle(element).outlineStyle), "none");
      const overflow = await f.page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      assert(overflow <= 1, `Source controls overflowed by ${overflow}px`);
      await f.metrics("source-filters-360");
      await f.snapshot("source-filters-360");
    }],
    ["Citation drawer shows exact evidence text and unavailable reasons without substitution", async () => {
      await f.seedSavedReport({ topic: "Fictional exact evidence", evidenceText: "Exact cited evidence value" });
      await f.openResearch();
      const citation = button("Trace 1 citation").first();
      await citation.click();
      let drawer = f.page.getByRole("dialog", { name: "Citation trace", exact: true });
      await drawer.waitFor();
      assert.equal(await drawer.locator(".citation-text-value").innerText(), "Exact cited evidence value");
      assert.match(await drawer.innerText(), /Cited description value/);
      assert.match(await drawer.innerText(), /does not independently verify/);
      assert.equal(await drawer.getByRole("link", { name: "View original", exact: true }).getAttribute("href"), "https://example.test/fictional");
      await f.page.keyboard.press("Escape");
      assert.equal(await drawer.count(), 0);
      assert.equal(await citation.evaluate((element) => document.activeElement === element), true, "Closing restores focus to the trigger");
      assert.equal(await f.page.getByText("Run diagnostics unavailable for this report. Measurements were not recorded when it was saved.", { exact: true }).isVisible(), true);
      assert.equal(await f.page.getByText(/Missing diagnostics do not imply zero/).isVisible(), true);

      await f.seedSavedReport({ topic: "Fictional missing evidence", evidenceText: null });
      await f.openResearch();
      await button("Trace 1 citation").first().click();
      drawer = f.page.getByRole("dialog", { name: "Citation trace", exact: true });
      await drawer.waitFor();
      assert.match(await drawer.innerText(), /Cited text unavailable: value is null/);
      assert.equal(await drawer.locator(".citation-text-value").count(), 0);
      await f.page.keyboard.press("Escape");
      assert.equal(plannerMutations().length, 0);
      await f.snapshot("citation-exact-evidence");
    }],
    ["Full report copy, clipboard failure and print keep every caveat and disclosure", async () => {
      await f.seedSavedReport({ topic: "Fictional export report", researchFirst: true });
      await f.openResearch();
      assert.equal(await f.page.locator(".report-print-only").first().evaluate((element) => getComputedStyle(element).display), "none");
      await f.page.context().grantPermissions(["clipboard-read", "clipboard-write"], { origin: f.origin });
      await button("Copy full report as Markdown").click();
      await f.page.getByText("Report copied", { exact: true }).waitFor();
      const copied = await f.page.evaluate(() => navigator.clipboard.readText());
      for (const text of ["# Research report", "## Research findings", "## Sources", "Event dates are unavailable", "Run diagnostics unavailable", "not the whole internet"]) {
        assert.ok(copied.includes(text), `Copied report is missing ${text}`);
      }
      assert.ok(!copied.includes("\u003cimg"), "Source markup must stay escaped text");

      await f.page.evaluate(() => {
        Object.defineProperty(navigator, "clipboard", {
          configurable: true,
          value: { writeText: async () => { throw new Error("denied by test"); } },
        });
      });
      await button("Copy full report as Markdown").click();
      assert.equal(await f.page.getByText(/Clipboard unavailable/).isVisible(), true);

      const search = f.page.getByLabel("Search source titles", { exact: true });
      await search.fill("outside-window");
      assert.equal(await f.page.locator(".reference-card:visible").count(), 1);
      await f.page.emulateMedia({ media: "print" });
      assert.equal(await f.page.locator(".reference-card:visible").count(), 3, "Print ignores screen filters");
      assert.equal(await f.page.locator(".report-print-only").first().isVisible(), true);
      assert.equal(await f.page.locator(".unified-header").isVisible(), false, "Print hides application chrome");
      await f.page.emulateMedia({ media: "screen" });

      await f.page.evaluate(() => {
        window.__printCalls = 0;
        window.print = () => {
          window.__printCalls += 1;
          window.__printAllOpen = [...document.querySelectorAll(".report details")].every((detail) => detail.open);
        };
      });
      const contentToolsOpenBefore = await contentTools().evaluate((element) => element.parentElement.open);
      await button("Print or save as PDF").click();
      assert.equal(await f.page.evaluate(() => window.__printCalls), 1);
      assert.equal(await f.page.evaluate(() => window.__printAllOpen), true);
      assert.equal(await contentTools().evaluate((element) => element.parentElement.open), contentToolsOpenBefore);
      assert.equal(plannerMutations().length, 0);
      await f.snapshot("report-print-layout");
    }],
    ["Saved history filters server-side, resets offset and distinguishes empty from no-match", async () => {
      const seeded = Array.from({ length: 50 }, (_, index) => ({ topic: `Fictional history ${index + 1}` }));
      seeded.push({ topic: "Zebra climate education" });
      seeded.push({ topic: "Fictional September report", dateFrom: "2026-09-01", dateTo: "2026-09-30" });
      seeded.push({ topic: "Fictional empty outcome", noEvidence: true });
      f.seedSavedReports(seeded);
      await f.page.goto(f.origin + "/past-reports");
      await f.page.locator(".history-row").first().waitFor();
      const rows = f.page.locator(".history-row");
      assert.equal(await rows.count(), 50);
      assert.equal(await f.page.locator(".history-page-label").innerText(), "Page 1");
      await button("Next").click();
      await f.waitFor(async () => (await rows.count()) === 3);

      const search = f.page.getByLabel("Topic search", { exact: true });
      await search.fill("zebra");
      await button("Apply filters").click();
      await f.waitFor(async () => (await rows.count()) === 1);
      assert.equal(await f.page.locator(".history-page-label").innerText(), "Page 1");
      assert.match(await rows.first().innerText(), /Zebra climate education/);

      await button("Reset").click();
      await f.waitFor(async () => (await rows.count()) === 50);
      await f.page.locator(".history-filter-field select").selectOption("no_evidence");
      await button("Apply filters").click();
      await f.waitFor(async () => (await rows.count()) === 1);
      assert.match(await rows.first().innerText(), /Fictional empty outcome/);

      await button("Reset").click();
      await f.waitFor(async () => (await rows.count()) === 50);
      await f.page.getByLabel("Requested from", { exact: true }).fill("2026-09-01");
      await button("Apply filters").click();
      await f.waitFor(async () => (await rows.count()) === 1);
      assert.match(await rows.first().innerText(), /Fictional September report/);

      await f.page.getByLabel("Requested to", { exact: true }).fill("2026-08-01");
      await button("Apply filters").click();
      assert.equal(await f.page.getByText("Start date must not be after end date.", { exact: true }).isVisible(), true);
      await f.page.getByLabel("Requested to", { exact: true }).fill("2026-09-30");
      await button("Apply filters").click();
      await f.waitFor(async () => (await rows.count()) === 1);

      await button("Reset").click();
      await f.waitFor(async () => (await rows.count()) === 50);
      await f.page.getByLabel("Requested from", { exact: true }).fill("2026-10-01");
      await f.page.getByLabel("Requested to", { exact: true }).fill("2026-10-02");
      await button("Apply filters").click();
      await f.page.getByRole("heading", { name: "No reports match these filters", exact: true }).waitFor();
      assert.equal(await rows.count(), 0);
      await f.page.setViewportSize({ width: 360, height: 900 });
      const overflow = await f.page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      assert(overflow <= 1, `History filters overflowed by ${overflow}px`);
      await f.metrics("history-filters-360");
      await f.snapshot("history-filters-360");
      assert.equal(plannerMutations().length, 0);
    }],
    ["Superseded history search is aborted and never replaces the newer result", async () => {
      f.seedSavedReports([{ topic: "Unique Alpha report" }, { topic: "Unique Beta report" }]);
      let release;
      const gate = new Promise((resolve) => { release = resolve; });
      await f.page.route("**/api/v1/research/reports?*q=Alpha*", async (route) => {
        await gate;
        await route.continue().catch(() => {});
      });
      await f.page.goto(f.origin + "/past-reports");
      await f.page.locator(".history-row").first().waitFor();
      const search = f.page.getByLabel("Topic search", { exact: true });
      await search.fill("Alpha");
      await button("Apply filters").click();
      await f.page.waitForTimeout(150);
      await search.fill("Beta");
      await button("Apply filters").click();
      await f.waitFor(async () => (await f.page.locator(".history-row").count()) === 1);
      release();
      await f.page.waitForTimeout(300);
      assert.match(await f.page.locator(".history-row").first().innerText(), /Unique Beta report/);
      assert.equal(await f.page.getByText("Unique Alpha report", { exact: false }).count(), 0);
      await f.page.unroute("**/api/v1/research/reports?*q=Alpha*");

      await f.switchAccount(f.B);
      await f.page.locator(".history-row").first().waitFor();
      assert.equal(await f.page.getByRole("heading", { name: "Saved research", exact: true }).isVisible(), true);
      assert.equal(await f.page.getByText("Could not load reports").count(), 0);
      assert.equal(plannerMutations().length, 0);
    }],
    ["Loading shows measured elapsed time and completed reports show real run details", async () => {
      await f.page.goto(f.origin + "/");
      await f.page.getByRole("button", { name: "Generate research report", exact: true }).waitFor();
      f.fault({ action: "generate", mode: "delay-before" });
      await f.page.getByLabel("Topic", { exact: true }).fill("Fictional delayed diagnostics");
      await f.page.getByRole("button", { name: "Generate research report", exact: true }).click();
      await f.page.locator(".elapsed-note").waitFor();
      await f.page.waitForTimeout(1200);
      assert.match(await f.page.locator(".elapsed-note").innerText(), /Elapsed: \d/);
      assert.equal(await f.page.getByText(/percentage|% complete/i).count(), 0, "No invented progress percentage");
      await f.release();
      await f.page.locator(".report").waitFor();
      assert.equal(await f.page.locator(".elapsed-note").count(), 0, "The timer stops when the response arrives");
      const runSummary = f.page.locator(".run-diagnostics summary");
      await runSummary.click();
      const diagnostics = f.page.locator(".run-diagnostics");
      assert.match(await diagnostics.innerText(), /Backend run/);
      assert.match(await diagnostics.innerText(), /Browser wait \(submit to response\)/);
      assert.match(await diagnostics.innerText(), /Source collection/);
      assert.match(await diagnostics.innerText(), /serialized request bytes/);
      assert.match(await diagnostics.innerText(), /Findings mode: AI interpretation/);
      assert.match(await diagnostics.innerText(), /prompt 100/);
      assert.match(await diagnostics.innerText(), /does not guarantee the router or provider stopped/);
      assert.equal(await f.page.getByText(/private provider message|authorization/i).count(), 0);
      assert.equal(plannerMutations().length, 0);
      await f.snapshot("run-diagnostics");
    }],
    ["Preview loads the highest-resolution image once and stops", async () => {
      const base = f.images.length;
      await f.seedSavedReport({ topic: "Fictional preview research" }); await f.openResearch();
      const card = f.page.locator(".reference-card").first();
      const image = card.locator(".reference-preview img");
      await card.scrollIntoViewIfNeeded();
      await f.waitFor(() => f.images.length >= base + 1);
      await f.waitFor(async () => (await image.evaluate((element) => element.naturalWidth)) > 0);
      assert.equal(await image.getAttribute("src"), "https://i.ytimg.com/vi/fictional-1/maxresdefault.jpg");
      assert.equal(await image.getAttribute("width"), "320");
      assert.equal(await image.getAttribute("height"), "180");
      assert.equal(await image.getAttribute("loading"), "lazy");
      assert.equal(await image.getAttribute("referrerpolicy"), "no-referrer");
      assert.equal(await image.getAttribute("alt"), "YouTube thumbnail for Fictional source");
      assert.equal(await image.evaluate((element) => element.naturalWidth), 1280);
      assert.deepEqual(f.images.slice(base).map((entry) => entry.file), ["maxresdefault.jpg"], "A successful high-resolution load must stop the fallback");
      await f.snapshot("source-preview");
      await f.page.setViewportSize({ width: 360, height: 800 });
      await f.metrics("source-preview-360");
      assert.equal(plannerMutations().length, 0);
    }],
    ["Missing high-resolution image falls back to the next candidate", async () => {
      f.setImageMode("missing-high");
      const base = f.images.length;
      await f.seedSavedReport({ topic: "Fictional missing-high preview" }); await f.openResearch();
      const card = f.page.locator(".reference-card").first();
      const image = card.locator(".reference-preview img");
      await card.scrollIntoViewIfNeeded();
      await f.waitFor(() => f.images.length >= base + 2);
      await f.waitFor(async () => (await image.evaluate((element) => element.naturalWidth)) === 480);
      assert.deepEqual(f.images.slice(base).map((entry) => entry.file), ["maxresdefault.jpg", "hqdefault.jpg"]);
      assert.equal(await image.getAttribute("src"), "https://i.ytimg.com/vi/fictional-1/hqdefault.jpg");
      assert.equal(await card.getByRole("heading", { name: "Fictional source", exact: true }).isVisible(), true);
      assert.equal(plannerMutations().length, 0);
    }],
    ["Undersized placeholder advances to the next candidate", async () => {
      f.setImageMode("placeholder");
      const base = f.images.length;
      await f.seedSavedReport({ topic: "Fictional placeholder preview" }); await f.openResearch();
      const card = f.page.locator(".reference-card").first();
      const image = card.locator(".reference-preview img");
      await card.scrollIntoViewIfNeeded();
      await f.waitFor(() => f.images.length >= base + 2);
      await f.waitFor(async () => (await image.evaluate((element) => element.naturalWidth)) === 480);
      assert.deepEqual(f.images.slice(base).map((entry) => entry.file), ["maxresdefault.jpg", "hqdefault.jpg"]);
      assert.equal(await image.evaluate((element) => element.naturalWidth), 480);
      assert.equal(plannerMutations().length, 0);
    }],
    ["Every preview candidate failing keeps the title and Open source usable", async () => {
      f.setImageMode("broken");
      const base = f.images.length;
      await f.seedSavedReport({ topic: "Fictional broken preview" }); await f.openResearch();
      const card = f.page.locator(".reference-card").first();
      await card.scrollIntoViewIfNeeded();
      await f.waitFor(() => f.images.length >= base + 3);
      await f.waitFor(() => card.locator(".reference-preview img").count().then((count) => count === 0));
      assert.deepEqual(f.images.slice(base).map((entry) => entry.file), ["maxresdefault.jpg", "hqdefault.jpg", "mqdefault.jpg"], "Each candidate is tried exactly once");
      assert.equal(await card.locator(".reference-preview").count(), 0);
      assert.equal(await card.getByRole("heading", { name: "Fictional source", exact: true }).isVisible(), true);
      assert.equal(await card.getByRole("link", { name: "Open source", exact: true }).isVisible(), true);
      await f.snapshot("source-preview-broken");
      assert.equal(plannerMutations().length, 0);
    }],
    ["Public-web and invalid ids request no thumbnail", async () => {
      const base = f.images.length;
      await f.seedSavedReport({ topic: "Fictional web research", publicWeb: true }); await f.openResearch();
      await f.page.locator(".reference-list").scrollIntoViewIfNeeded();
      assert.equal(await f.page.locator(".reference-card .reference-preview").count(), 0);
      assert.equal(f.images.length, base, "A public-web reference must make no image request");
      await f.seedSavedReport({ topic: "Fictional invalid id", invalidYoutubeId: true }); await f.openResearch();
      await f.page.locator(".reference-list").scrollIntoViewIfNeeded();
      assert.equal(await f.page.locator(".reference-card .reference-preview").count(), 0);
      assert.equal(f.images.length, base, "An invalid video id must make no image request");
      assert.equal(await f.page.locator(".reference-card").first().getByRole("link", { name: "Open source", exact: true }).isVisible(), true);
      assert.equal(plannerMutations().length, 0);
    }],
    ["A public-web result from a known platform is labelled by hostname", async () => {
      await f.seedSavedReport({ socialWeb: true }); await f.openResearch();
      const card = f.page.locator(".reference-card").first();
      assert.equal(await card.locator(".source-badge").innerText(), "Public web");
      assert.equal(await card.locator(".reference-channel").innerText(), "Reddit · via web search");
      assert.equal(await card.getByRole("heading", { name: "Fictional Reddit thread", exact: true }).isVisible(), true);
      // The original URL and citation identity are preserved for the trace.
      assert.equal(await card.getByRole("link", { name: "Open source", exact: true }).getAttribute("href"), "https://www.reddit.com/r/webdev/comments/1/fictional-topic/");
      assert.equal(plannerMutations().length, 0);
    }],
    ["P4 sourcing preserves citation URLs, distinct dates, sample counts and coverage gaps", async () => {
      await f.seedSavedReport({ researchFirst: true }); await f.openResearch();
      const source = (title) => f.page.locator(".reference-card").filter({ has: f.page.getByRole("heading", { name: title, exact: true }) });
      const inWindow = source("Fictional in-window source"), outside = source("Fictional outside-window source"), undated = source("Fictional undated web source");
      assert.equal(await inWindow.getByRole("link", { name: "Open source", exact: true }).getAttribute("href"), "https://example.test/fictional");
      assert.match(await inWindow.innerText(), /Published[^\n]*Aug 12, 2026/);
      assert.match(await outside.innerText(), /Published[^\n]*Jul 31, 2026/);
      for (const card of [inWindow, outside, undated]) { await expandSource(card); assert.match(await card.innerText(), /Collected[^\n]*Oct 1, 2026/); }
      assert.equal(await undated.getByText("Publication date unknown", { exact: true }).isVisible(), true);
      assert.equal(await f.page.getByText("Public web search did not enforce the requested timeframe. Publication dates are unverified; undated results are context.", { exact: true }).isVisible(), true);
      assert.equal(await f.page.getByText("Timeframe coverage is unverified.", { exact: false }).first().isVisible(), true);
      assert.equal(await inWindow.locator(".metric").filter({ hasText: "Views" }).locator("dd").innerText(), "0");
      assert.equal(await inWindow.locator(".metric").filter({ hasText: "Likes" }).locator("dd").innerText(), "Unknown");
      assert.match(await inWindow.innerText(), /Counts observed at collection, not a measure of growth/);
      await openScopeDetails();
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
        assert.equal(
          await f.page.getByText(/Execution details are unavailable in this report/i).isVisible(),
          true,
          "Missing legacy execution data stays visible while the details are closed",
        );
        await openScopeDetails();
        assert.match(await f.page.locator(".coverage-panel").innerText(), /unknown|unavailable/i);
        await f.page.getByText("Saved to history.", { exact: true }).waitFor();
        if (!noEvidence) {
          assert.equal(await f.page.getByText("Publication date unknown", { exact: true }).isVisible(), true);
          await expandSource(f.page.locator(".reference-card").first());
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
    ["P4 report disclosures work by keyboard and reflow at mobile and narrow-viewport widths", async () => {
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
      const optIn = f.page.getByRole("checkbox", { name: "Generate content ideas and briefs", exact: true });
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
        assert.equal(await f.page.getByText("Source-attributed excerpt", { exact: true }).count(), 1);
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
        assert.equal(await f.page.getByText("Source-attributed excerpt", { exact: true }).count(), 1);
        assert.equal(plannerMutations().length, 0);
        await f.snapshot(`synthesis-fallback-${reason}`);
      }
    }],
    ["Final insufficient and unavailable summaries retain evidence without fabricated findings", async () => {
      for (const options of [{ insufficient: true }, { researchUnavailable: true }]) {
        await f.seedSavedReport(options); await f.openResearch();
        const message = f.page.locator(".findings-empty");
        assert.equal(await message.count(), 1, "Empty findings show exactly one clear message");
        assert.match(await message.innerText(), options.insufficient ? /Insufficient source text/ : /Sourced summaries are unavailable/);
        assert.equal(await f.page.locator("[data-finding-scope]").count(), 0);
        assert.equal(await f.page.locator(".reference-card").count(), 1);
        assert.equal(await f.page.getByRole("heading", { name: /Sources and evidence/ }).isVisible(), true, "Sources stay accessible with no findings");
        assert.equal(await f.page.getByText("Saved to history.", { exact: true }).isVisible(), true);
        assert.equal(plannerMutations().length, 0);
      }
    }],
    ["Pattern-only findings render as secondary sample observations", async () => {
      await f.seedSavedReport({ observationOnly: true }); await f.openResearch();
      const findings = f.page.locator('section[aria-labelledby="findings-title"]');
      // No synthesis/excerpt label is shown when no finding rests on source text.
      assert.equal(await findings.getByText("AI interpretation", { exact: true }).count(), 0);
      assert.equal(await findings.getByText("Source-attributed excerpt", { exact: true }).count(), 0);
      const observations = findings.locator(".sample-observations");
      assert.equal(await observations.isVisible(), true);
      assert.equal(await observations.getByRole("heading", { name: "AI observations about the sample", exact: true }).isVisible(), true);
      assert.equal(await observations.getByText("Fictional sample observation", { exact: true }).isVisible(), true);
      await observations.getByRole("button", { name: "Trace 1 citation", exact: true }).click();
      const drawer = f.page.getByRole("dialog", { name: "Citation trace", exact: true });
      await drawer.waitFor();
      assert.match(await drawer.innerText(), /title_has_numeral/);
      assert.match(await drawer.innerText(), /Interpretation #0/);
      await f.page.keyboard.press("Escape");
      assert.equal(await drawer.count(), 0);
      assert.equal(plannerMutations().length, 0);
    }],
    ["Mixed reports keep indices and separate findings from observations", async () => {
      const id = await f.seedSavedReport({ mixedFindings: true });
      const snapshotBefore = JSON.stringify(f.reports.get(id).report);
      await f.openResearch();
      const findings = f.page.locator('section[aria-labelledby="findings-title"]');
      assert.equal(await findings.getByText("AI interpretation", { exact: true }).isVisible(), true);
      assert.equal(await findings.getByText("Fictional sourced finding", { exact: true }).isVisible(), true);
      assert.equal(await findings.locator(".sample-observations").getByText("Fictional sample observation", { exact: true }).isVisible(), true);
      // One trace per finding; original interpretation indices are preserved.
      const traces = findings.locator(".citation-toggle");
      assert.equal(await traces.count(), 2);
      await traces.nth(0).click();
      const first = f.page.getByRole("dialog", { name: "Citation trace", exact: true });
      await first.waitFor();
      assert.match(await first.innerText(), /Interpretation #0/);
      assert.match(await first.innerText(), /Fictional sourced finding/);
      await f.page.keyboard.press("Escape");
      await traces.nth(1).click();
      const second = f.page.getByRole("dialog", { name: "Citation trace", exact: true });
      await second.waitFor();
      assert.match(await second.innerText(), /Interpretation #1/);
      assert.match(await second.innerText(), /Fictional sample observation/);
      await f.page.keyboard.press("Escape");
      // Presentation must not mutate the saved snapshot it renders.
      assert.equal(JSON.stringify(f.reports.get(id).report), snapshotBefore);
      assert.equal(plannerMutations().length, 0);
    }],
    ["Unresolved legacy evidence stays visible and qualified", async () => {
      await f.seedSavedReport({ unresolvedFinding: true }); await f.openResearch();
      const findings = f.page.locator('section[aria-labelledby="findings-title"]');
      const limited = findings.locator(".limited-evidence");
      assert.equal(await limited.isVisible(), true);
      assert.equal(await limited.getByRole("heading", { name: "Interpretations with limited evidence", exact: true }).isVisible(), true);
      assert.equal(await findings.locator(".sample-observations").count(), 0, "An unresolved reference is not a sample observation");
      assert.equal(await findings.getByText("AI interpretation", { exact: true }).count(), 0);
      assert.equal(await findings.getByText("Source-attributed excerpt", { exact: true }).count(), 0);
      assert.equal(await findings.getByText("Fictional unresolved finding", { exact: true }).isVisible(), true);
      assert.equal(await limited.getByText(/Unresolved provenance/).first().isVisible(), true);
      assert.ok(await limited.locator(".citation-toggle").count() >= 1, "citation trace control present");
      await limited.locator(".citation-toggle").first().click();
      const drawer = f.page.getByRole("dialog", { name: "Citation trace", exact: true });
      await drawer.waitFor();
      assert.match(await drawer.innerText(), /Unresolved/);
      await f.page.keyboard.press("Escape");
      assert.equal(await drawer.count(), 0);
      assert.equal(plannerMutations().length, 0);
    }],
    ["Missing, null, or metadata-only evidence is limited evidence", async () => {
      const cases = [
        { blankTextFact: true, statement: "Fictional blank-text finding" },
        { nullMetricFact: true, statement: "Fictional null-metric finding" },
        { metadataOnlyFact: true, statement: "Fictional metadata-only finding" },
      ];
      for (const item of cases) {
        await f.seedSavedReport(item); await f.openResearch();
        const findings = f.page.locator('section[aria-labelledby="findings-title"]');
        const limited = findings.locator(".limited-evidence");
        assert.equal(await limited.isVisible(), true, item.statement);
        assert.equal(await limited.getByText(item.statement, { exact: true }).isVisible(), true);
        assert.equal(await findings.locator(".sample-observations").count(), 0, item.statement);
        assert.equal(await findings.getByText("AI interpretation", { exact: true }).count(), 0);
        assert.match(await limited.innerText(), /missing, incomplete, or insufficient/);
        await limited.getByRole("button", { name: "Trace 1 citation", exact: true }).click();
        const drawer = f.page.getByRole("dialog", { name: "Citation trace", exact: true });
        await drawer.waitFor();
        assert.match(await drawer.innerText(), /Interpretation #0/);
        await f.page.keyboard.press("Escape");
      }
      assert.equal(plannerMutations().length, 0);
    }],
    ["Final delayed generation cannot restore an old account’s research or optional selection", async () => {
      await f.openResearch();
      f.fault({ action: "generate", mode: "delay-after" });
      await f.page.getByLabel("Topic", { exact: true }).fill("A research");
      await f.page.getByRole("checkbox", { name: "Generate content ideas and briefs", exact: true }).check();
      await button("Generate research report").click(); await f.stalled();
      await f.switchAccount(f.B);
      await button("Generate research report").waitFor();
      await f.page.getByLabel("Topic", { exact: true }).fill("B unsaved research");
      assert.equal(await f.page.getByRole("checkbox", { name: "Generate content ideas and briefs", exact: true }).isChecked(), false);
      await f.release();
      await f.page.waitForTimeout(100);
      assert.equal(await f.page.locator(".report").count(), 0);
      assert.equal(await f.page.getByLabel("Topic", { exact: true }).inputValue(), "B unsaved research");
      assert.equal(plannerMutations().length, 0);
    }],
    ["Final research-only and opt-in controls remain keyboard accessible at mobile width", async () => {
      await f.openResearch(); await f.page.setViewportSize({ width: 360, height: 800 });
      const optIn = f.page.getByRole("checkbox", { name: "Generate content ideas and briefs", exact: true });
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
    ["Simplified form has no country/source/depth controls and submits global YouTube + public web", async () => {
      await f.page.goto(`${f.origin}/test-fixtures/SimpleForm`);
      const submitted = async () => JSON.parse(await f.page.locator("#submitted-json").innerText());
      // Removed controls are genuinely gone.
      assert.equal(await f.page.getByRole("button", { name: "Advanced options", exact: true }).count(), 0);
      assert.equal(await f.page.locator('input[name="source"]').count(), 0);
      assert.equal(await f.page.locator('input[name="markets"]').count(), 0);
      assert.equal(await f.page.locator("#simple-depth, #research-depth").count(), 0);
      assert.equal(await f.page.getByLabel("Facebook Page ID", { exact: true }).count(), 0);
      // Global coverage note is present; timeframe stays visible.
      assert.match(await f.page.locator(".source-coverage-note").innerText(), /no country restriction/);
      assert.equal(await f.page.getByLabel("From", { exact: true }).isVisible(), true);
      assert.equal(await f.page.getByLabel("To", { exact: true }).isVisible(), true);
      // Content tools are optional and unchecked by default.
      const optIn = f.page.getByRole("checkbox", { name: "Generate content ideas and briefs", exact: true });
      assert.equal(await optIn.isChecked(), false);
      // Submit: global request with both sources and no markets.
      await button("Generate research report").click();
      await f.waitFor(async () => (await f.page.locator("#submitted-json").innerText()).length > 0);
      const body = await submitted();
      assert.deepEqual(body.sources, ["youtube", "public_web"]);
      assert.deepEqual(body.markets, []);
      assert.equal(body.result_limit, 50);
      assert.equal(body.include_content_tools, false);
      // Keyboard: the optional-content checkbox is reachable and operable.
      await optIn.focus(); await f.page.keyboard.press("Space");
      assert.equal(await optIn.isChecked(), true);
      for (const width of [360, 768, 1440, 720]) {
        await f.page.setViewportSize({ width, height: 900 });
        await f.metrics(`simple-form-${width}`); await f.snapshot(`simple-form-${width}`);
      }
      assert.equal(plannerMutations().length, 0);
    }],
    ["History list, empty state, and status badges render without overflow", async () => {
      // Empty state first.
      await f.page.goto(f.origin + "/past-reports");
      await f.page.getByRole("heading", { name: "No reports yet", exact: true }).waitFor();
      const emptyLink = f.page.getByRole("link", { name: "Generate research report", exact: true });
      assert.equal(await emptyLink.isVisible(), true);
      // Anchor-styled primary buttons must reach the 44px target like the
      // <button> variant (display:inline would collapse min-height).
      const emptyRect = await emptyLink.boundingBox();
      assert(emptyRect.height >= 44, `primary link target ${emptyRect.width}×${emptyRect.height}`);
      await f.metrics("history-empty-1440");
      // Populated list: seed two saved reports, reload.
      await f.seedSavedReport({ topic: "Fictional history one", researchFirst: true });
      await f.seedSavedReport({ topic: "Fictional history two", noEvidence: true });
      await f.page.reload();
      await f.page.locator(".history-row").first().waitFor();
      assert.equal(await f.page.locator(".history-row").count(), 2);
      assert.equal(await f.page.locator(".status-badge").count(), 2);
      await f.page.locator(".history-row").first().click();
      await f.page.locator(".report").waitFor();
      assert.equal(await f.page.getByRole("heading", { name: "Research findings", exact: true }).isVisible(), true);
      await f.page.setViewportSize({ width: 360, height: 800 });
      await f.page.goto(f.origin + "/past-reports");
      await f.page.locator(".history-row").first().waitFor();
      await f.metrics("history-list-360");
      await f.snapshot("history-list-360");
    }],
    ["Auth screens render and reject an invalid callback link", async () => {
      // Sign out first so /login is not bounced by the active session.
      await f.page.goto(f.origin + "/");
      await f.page.getByRole("button", { name: "Sign out", exact: true }).click();
      await f.page.waitForURL(f.origin + "/login");
      await f.page.getByLabel("Email", { exact: true }).waitFor();
      await f.page.getByRole("button", { name: "Forgot your password?", exact: true }).click();
      await f.page.getByRole("button", { name: "Send recovery link", exact: true }).waitFor();
      await f.metrics("auth-login-1440");
      await f.page.setViewportSize({ width: 360, height: 800 });
      await f.metrics("auth-login-360");
      await f.snapshot("auth-login-360");
      // A callback page with no valid token lands on the invalid panel.
      await f.page.goto(f.origin + "/accept-invite");
      await f.page.getByText(/invalid, expired, or already used/, { exact: false }).waitFor({ timeout: 10000 });
      await f.metrics("auth-invite-invalid-360");
      await f.snapshot("auth-invite-invalid-360");
      await f.page.goto(f.origin + "/reset-password");
      await f.page.getByText(/invalid, expired, or already used/, { exact: false }).waitFor({ timeout: 10000 });
      await f.metrics("auth-reset-invalid-360");
    }],
    ["Viewport/device-density emulation (720 CSS px, DPR 2) keeps content readable with no page overflow", async () => {
      await f.seedSavedReport({ researchFirst: true }); await f.openResearch();
      // This is CDP viewport/device-density emulation, NOT the browser's actual
      // zoom setting. It halves the CSS viewport while doubling devicePixelRatio,
      // matching the layout a 1440px window produces at 200% zoom, but it does
      // not prove the browser zoom control was exercised. Actual 200% browser
      // zoom on report reading was performed separately by the independent
      // review (see /private/tmp/trendora-ui-review.RCUuTx/REPORT.md).
      const cdp = await f.page.context().newCDPSession(f.page);
      await cdp.send("Emulation.setDeviceMetricsOverride", { width: 720, height: 900, deviceScaleFactor: 2, mobile: false, screenWidth: 720, screenHeight: 900 });
      assert.equal(await f.page.evaluate(() => window.devicePixelRatio), 2);
      const data = await f.metrics("viewport-density-emulation");
      assert.equal(data.viewport, 720);
      // Content stays reachable and readable.
      assert.equal(await f.page.getByRole("heading", { name: "Research findings", exact: true }).isVisible(), true);
      assert.equal(await f.page.locator(".reference-card").first().isVisible(), true);
      await f.snapshot("viewport-density-emulation");
      await cdp.send("Emulation.clearDeviceMetricsOverride");
    }],
    ["Reduced motion removes entrance animation while content stays readable and interactive", async () => {
      await f.page.emulateMedia({ reducedMotion: "reduce" });
      await f.seedSavedReport({ researchFirst: true }); await f.openResearch();
      const report = f.page.locator(".report");
      await report.waitFor();
      // Content is present and fully opaque immediately; no reliance on motion.
      assert.equal(await report.isVisible(), true);
      const duration = await report.evaluate((element) => getComputedStyle(element).animationDuration);
      assert.match(duration, /^(0\.001ms|1e-06s)$/);
      // The single entrance animation is neutralized, not merely faster.
      assert.equal(await f.page.getByRole("heading", { name: "Research findings", exact: true }).isVisible(), true);
      assert.equal(await f.page.locator(".reference-card").first().isVisible(), true);
      await f.metrics("reduced-motion-1440");
      await f.page.setViewportSize({ width: 360, height: 800 });
      await f.metrics("reduced-motion-360");
      await f.snapshot("reduced-motion-360");
      await f.page.emulateMedia({ reducedMotion: "no-preference" });
    }],
    ["Header nav marks the current destination and the mobile menu is labelled and keyboard operable", async () => {
      // Desktop: primary destinations are visible with an aria-current marker.
      await f.page.setViewportSize({ width: 1440, height: 900 });
      await f.openResearch();
      const nav = f.page.getByRole("navigation", { name: "Primary", exact: true });
      await nav.waitFor();
      assert.equal(await nav.getByRole("link", { name: "Research", exact: true }).getAttribute("aria-current"), "page");
      assert.equal(await f.page.locator(".menu-toggle").isVisible(), false);
      await f.metrics("shell-desktop");

      // Narrow: the row collapses into a labelled Menu control, not a bare icon.
      await f.page.setViewportSize({ width: 360, height: 800 });
      assert.equal(await nav.isVisible(), false);
      const menu = f.page.locator(".menu-toggle");
      await menu.waitFor();
      assert.equal(await menu.getAttribute("aria-expanded"), "false");
      assert.match(await menu.innerText(), /Menu/);
      await menu.focus();
      await f.page.keyboard.press("Enter");
      assert.equal(await menu.getAttribute("aria-expanded"), "true");
      const mobileNav = f.page.getByRole("navigation", { name: "Primary mobile", exact: true });
      await mobileNav.waitFor();
      assert.equal(await mobileNav.getByRole("link", { name: "Reports", exact: true }).isVisible(), true);
      await f.metrics("shell-mobile");
      await mobileNav.getByRole("link", { name: "Reports", exact: true }).focus();
      await f.page.keyboard.press("Enter");
      await f.page.waitForURL(f.origin + "/past-reports");
      assert.equal(await f.page.locator(".menu-toggle").getAttribute("aria-expanded"), "false", "menu must close after navigation");
    }],
    ["Research control boundaries meet 3:1 in default and hover states", async () => {
      await f.page.setViewportSize({ width: 1440, height: 900 });
      await f.openResearch();
      // Contrast helper mirrors the WCAG 2.x relative-luminance formula.
      const result = await f.page.evaluate(() => {
        const parse = (value) => value.match(/\d+(\.\d+)?/g).slice(0, 3).map(Number);
        const luminance = ([r, g, b]) => {
          const lin = [r, g, b].map((c) => { const v = c / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
          return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
        };
        const ratio = (fg, bg) => { const a = luminance(fg), b = luminance(bg); const [hi, lo] = a > b ? [a, b] : [b, a]; return (hi + 0.05) / (lo + 0.05); };
        const boundary = (element) => { const style = getComputedStyle(element); return ratio(parse(style.borderTopColor), parse(style.backgroundColor)); };
        const topic = document.getElementById("topic");
        const sourceOption = document.querySelector(".research-form .source-option");
        const advance = (element) => { const s = getComputedStyle(element); return ratio(parse(s.borderTopColor), parse(s.backgroundColor)); };
        return {
          topicDefault: boundary(topic),
          sourceOptionDefault: advance(sourceOption),
          topicBorder: getComputedStyle(topic).borderTopColor,
        };
      });
      assert(result.topicDefault >= 3, `topic default boundary ${result.topicDefault.toFixed(2)}:1`);
      assert(result.sourceOptionDefault >= 3, `source option default boundary ${result.sourceOptionDefault.toFixed(2)}:1`);
      // Hover states must also meet 3:1.
      await f.page.locator("#topic").hover();
      const hoverRatio = await f.page.evaluate(() => {
        const parse = (value) => value.match(/\d+(\.\d+)?/g).slice(0, 3).map(Number);
        const luminance = ([r, g, b]) => { const lin = [r, g, b].map((c) => { const v = c / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]; };
        const ratio = (fg, bg) => { const a = luminance(fg), b = luminance(bg); const [hi, lo] = a > b ? [a, b] : [b, a]; return (hi + 0.05) / (lo + 0.05); };
        const style = getComputedStyle(document.getElementById("topic"));
        return ratio(parse(style.borderTopColor), parse(style.backgroundColor));
      });
      assert(hoverRatio >= 3, `topic hover boundary ${hoverRatio.toFixed(2)}:1`);
    }],
    ["An open mobile menu cannot disrupt the header across the desktop breakpoint", async () => {
      await f.page.setViewportSize({ width: 360, height: 800 });
      await f.openResearch();
      const menu = f.page.locator(".menu-toggle");
      await menu.click();
      assert.equal(await menu.getAttribute("aria-expanded"), "true");
      const mobileNav = f.page.getByRole("navigation", { name: "Primary mobile", exact: true });
      await mobileNav.waitFor();
      // Cross to desktop with the menu still open.
      await f.page.setViewportSize({ width: 1440, height: 900 });
      assert.equal(await mobileNav.isVisible(), false, "mobile menu must be hidden on desktop");
      assert.equal(await f.page.locator(".header-nav").isVisible(), true);
      assert.equal(await menu.isVisible(), false);
      // No overlapping controls: every visible control stays within the viewport
      // and the header controls do not intersect each other.
      for (const width of [1440, 1024, 769]) {
        await f.page.setViewportSize({ width, height: 900 });
        assert.equal(await mobileNav.isVisible(), false);
        assert.equal(await f.page.locator(".header-nav").isVisible(), true);
        await f.metrics(`menu-open-desktop-${width}`);
        const headerControls = await f.page.locator(".unified-header a, .unified-header button").evaluateAll((elements) =>
          elements.filter((e) => e.getClientRects().length).map((e) => { const r = e.getBoundingClientRect(); return { text: e.textContent, left: r.left, right: r.right, top: r.top, bottom: r.bottom }; }));
        for (let i = 0; i < headerControls.length; i += 1) {
          for (let j = i + 1; j < headerControls.length; j += 1) {
            const a = headerControls[i], b = headerControls[j];
            const overlap = a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
            assert.equal(overlap, false, `header controls overlap at ${width}px: ${a.text} / ${b.text}`);
          }
        }
      }
      // Return to mobile: the disclosure is still usable.
      await f.page.setViewportSize({ width: 360, height: 800 });
      assert.equal(await menu.isVisible(), true);
      assert.equal(await menu.getAttribute("aria-expanded"), "true");
      assert.equal(await mobileNav.isVisible(), true);
      await f.metrics("menu-open-mobile-again");
      await f.snapshot("menu-breakpoint-return");
    }],
    ["A saved report keeps Reports active in the navigation", async () => {
      const id = await f.seedSavedReport({ topic: "Fictional saved nav", researchFirst: true });
      await f.page.goto(`${f.origin}/report/${id}`);
      await f.page.locator(".report").waitFor();
      const desktopNav = f.page.getByRole("navigation", { name: "Primary", exact: true });
      const active = desktopNav.getByRole("link", { name: "Reports", exact: true });
      assert.equal(await active.getAttribute("aria-current"), "page");
      assert.equal(await desktopNav.getByRole("link", { name: "Research", exact: true }).getAttribute("aria-current"), null);
      assert.equal(await desktopNav.getByRole("link", { name: "Planner", exact: true }).getAttribute("aria-current"), null);
      // Mobile: the same destination is marked.
      await f.page.setViewportSize({ width: 360, height: 800 });
      await f.page.locator(".menu-toggle").click();
      const mobileNav = f.page.getByRole("navigation", { name: "Primary mobile", exact: true });
      await mobileNav.waitFor();
      assert.equal(await mobileNav.getByRole("link", { name: "Reports", exact: true }).getAttribute("aria-current"), "page");
      assert.equal(await mobileNav.locator('[aria-current="page"]').count(), 1);
      await f.snapshot("saved-report-nav-360");
    }],
    ["Citation drawer contains Tab and Shift+Tab, closes on Escape, and restores focus to the trigger", async () => {
      await f.seedSavedReport({ researchFirst: true }); await f.openResearch();
      const trigger = button("Trace 1 citation").first();
      await trigger.focus();
      await f.page.keyboard.press("Enter");
      const drawer = f.page.getByRole("dialog", { name: "Citation trace", exact: true });
      await drawer.waitFor();
      assert.equal(await drawer.evaluate((element) => element.contains(document.activeElement)), true);
      // Focus must stay inside across several forward and backward tabs.
      const inside = async () => drawer.evaluate((element) => element.contains(document.activeElement));
      for (let step = 0; step < 8; step += 1) {
        await f.page.keyboard.press("Tab");
        assert.equal(await inside(), true, `Tab #${step + 1} escaped the drawer`);
      }
      for (let step = 0; step < 8; step += 1) {
        await f.page.keyboard.press("Shift+Tab");
        assert.equal(await inside(), true, `Shift+Tab #${step + 1} escaped the drawer`);
      }
      // Background content is inert while the modal is open: a background
      // control cannot receive focus.
      const backgroundFocusable = await f.page.evaluate(() => {
        const button = [...document.querySelectorAll("button")].find((element) => element.textContent === "Download report JSON");
        button?.focus();
        return document.activeElement === button;
      });
      assert.equal(backgroundFocusable, false, "background control must be inert while the modal is open");
      // Backdrop click closes and restores focus. The dialog is right-anchored,
      // so click the scrim to its left.
      const box = await f.page.locator(".drawer-dialog").boundingBox();
      await f.page.mouse.click(Math.max(10, box.x - 40), box.y + box.height / 2);
      assert.equal(await drawer.count(), 0);
      assert.equal(await trigger.evaluate((element) => element === document.activeElement), true, "backdrop close restores focus");
      // Reopen and close with Escape.
      await trigger.focus();
      await f.page.keyboard.press("Enter");
      await f.page.getByRole("dialog", { name: "Citation trace", exact: true }).waitFor();
      await f.page.keyboard.press("Escape");
      assert.equal(await drawer.count(), 0);
      assert.equal(await trigger.evaluate((element) => element === document.activeElement), true, "Escape close restores focus");
    }],
    ["Global request retry, recovered save and planner import preserve the source set", async () => {
      await f.openResearch();
      await f.page.getByLabel("Topic", { exact: true }).fill("Fictional global topic");
      await f.page.getByLabel("From", { exact: true }).fill("2026-08-01");
      await f.page.getByLabel("To", { exact: true }).fill("2026-08-31");
      await f.page.getByRole("checkbox", { name: "Generate content ideas and briefs", exact: true }).check();
      f.fault({ action: "generate", mode: "reject", status: 503, code: "research_source_not_configured" });
      await button("Generate research report").click(); await button("Retry").waitFor();
      assert.equal(await f.page.getByText(/selected research source isn't configured/).isVisible(), true);
      await button("Retry").click(); await f.page.locator(".report").waitFor();
      const requests = f.calls.filter((c) => c.path === "/api/v1/research/report");
      assert.equal(requests.length, 2); assert.deepEqual(requests[0].body, requests[1].body);
      assert.deepEqual(requests[1].body.sources, ["youtube", "public_web"]);
      assert.deepEqual(requests[1].body.markets, []);
      assert.equal("facebook_page_id" in requests[1].body, false);
      f.fault({ action: "save", mode: "drop-after" });
      await button("Save report").click(); await button("Retry saving report").waitFor();
      await button("Retry saving report").click(); await f.page.getByText("Saved to history.", { exact: true }).waitFor();
      const saves = f.calls.filter((c) => c.path === "/api/v1/research/reports/save");
      assert.equal(saves.length, 2); assert.deepEqual(saves[0].body, saves[1].body);
      assert.deepEqual(saves[0].body.snapshot.research.query.sources, ["youtube", "public_web"]);
      assert.deepEqual(saves[0].body.snapshot.research.query.markets, []);
      const [reportId] = f.reports.keys();
      await f.page.goto(`${f.origin}/report/${reportId}`); await f.page.locator(".report").waitFor();
      assert.equal(plannerMutations().length, 0);
      await openContentTools(); await button("Save to Planner").first().click(); await button("Open post").waitFor();
      const imported = f.calls.find((c) => c.path === "/api/v1/planner/posts/import");
      assert.equal(imported.body.report_id, reportId); assert.equal(f.records.size, 1);
      await f.snapshot("global-recovered-import");
    }],
    ["Signed-out protected route redirects to sign in and shows no workspace", async () => {
      // Start authenticated, then sign out; a protected route must bounce to /login
      // and must not render workspace content from the prior session.
      await f.page.goto(f.origin + "/");
      await f.page.getByRole("button", { name: "Sign out", exact: true }).click();
      await f.page.waitForURL(f.origin + "/login");
      await f.page.getByLabel("Email", { exact: true }).waitFor();
      // Direct navigation to a protected route while signed out.
      await f.page.goto(f.origin + "/past-reports");
      await f.page.waitForURL(f.origin + "/login");
      assert.equal(await f.page.getByLabel("Email", { exact: true }).isVisible(), true);
      assert.equal(await f.page.locator(".history-row").count(), 0);
      assert.equal(await f.page.locator(".workspace").count(), 0);
      await f.page.goto(f.origin + "/planner");
      await f.page.waitForURL(f.origin + "/login");
      assert.equal(await f.page.locator(".planner-list").count(), 0);
    }],
    ["Planner archive hides from active list and restore returns it", async () => {
      const id = await create();
      // Back to the inbox: the post is active.
      await f.page.goto(f.origin + "/planner");
      await f.page.locator(".planner-row").first().waitFor();
      assert.equal(await f.page.locator(".planner-row").count(), 1);
      // Open it and archive.
      await f.page.goto(`${f.origin}/planner/${id}`);
      await saved();
      await button("Archive").click();
      await f.page.locator(".planner-status-line").filter({ hasText: "Saved" }).waitFor();
      assert.equal(f.records.get(id).archived_at !== null, true);
      // Active view is empty; archived view shows it.
      await f.page.goto(f.origin + "/planner");
      await f.page.getByRole("heading", { name: "No active posts yet", exact: true }).waitFor();
      await f.page.getByRole("button", { name: "Archived", exact: true }).click();
      await f.page.locator(".planner-row").first().waitFor();
      assert.equal(await f.page.locator(".planner-row").count(), 1);
      // Restore from the archived post.
      await f.page.goto(`${f.origin}/planner/${id}`);
      await button("Restore").waitFor();
      assert.equal(await title().getAttribute("readonly"), "");
      await button("Restore").click();
      await f.page.locator(".planner-status-line").filter({ hasText: "Saved" }).waitFor();
      assert.equal(f.records.get(id).archived_at, null);
      await f.page.goto(f.origin + "/planner");
      await f.page.locator(".planner-row").first().waitFor();
      assert.equal(await f.page.locator(".planner-row").count(), 1);
      await f.snapshot("planner-archive-restore");
    }],
    ["Scope essentials stay visible while detail is closed, including a partial search", async () => {
      await f.seedSavedReport({ researchFirst: true, partialSearch: true }); await f.openResearch();
      const summary = scopeSummary();
      assert.equal(await summary.isVisible(), true);
      assert.equal(await summary.evaluate((element) => element.parentElement.open), false, "detail starts closed");
      // Essentials derived from the report, not hardcoded.
      const report = f.page.locator(".report");
      assert.match(await report.innerText(), /Requested timeframe: 2026-08-01 to 2026-08-31/);
      assert.match(await report.innerText(), /Sources searched: YouTube, Public web/);
      assert.match(await report.innerText(), /References: 3/);
      // A partial search is reported by the source's own reason even though the
      // source appears in executed_sources, and it is visible while closed.
      const partial = f.page.locator(".scope-warning").filter({ hasText: /Public social discovery was partial/ });
      assert.equal(await partial.isVisible(), true, "the partial warning is visible while the details are closed");
      assert.equal(await f.page.getByText(/Requested but not searched: Facebook/).isVisible(), true);
      assert.equal(
        await f.page.getByText(/Timeframe coverage is unverified/).first().isVisible(),
        true,
        "the report-level timeframe caveat stays visible while the details are closed",
      );
      assert.equal(await f.page.getByText(/Public web search did not enforce the requested timeframe/).isVisible(), true);
      // Warnings must meet AA against the background actually painted behind
      // them, walking up through transparent ancestors.
      const warningContrast = await f.page.evaluate(() => {
        const channels = (value) => (value.match(/[\d.]+/g) ?? []).map(Number);
        const alpha = (value) => { const parts = channels(value); return parts.length >= 4 ? parts[3] : 1; };
        const luminance = ([r, g, b]) => {
          const lin = [r, g, b].map((c) => { const v = c / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
          return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
        };
        const ratio = (fg, bg) => { const a = luminance(fg), b = luminance(bg); const [hi, lo] = a > b ? [a, b] : [b, a]; return (hi + 0.05) / (lo + 0.05); };
        const paintedBackground = (element) => {
          for (let node = element; node; node = node.parentElement) {
            const value = getComputedStyle(node).backgroundColor;
            if (alpha(value) > 0) return channels(value).slice(0, 3);
          }
          return [255, 255, 255];
        };
        return [...document.querySelectorAll(".scope-warning")].map((element) => {
          const style = getComputedStyle(element);
          return {
            text: element.textContent.trim().slice(0, 40),
            ratio: ratio(channels(style.color).slice(0, 3), paintedBackground(element)),
            fontSize: parseFloat(style.fontSize),
          };
        });
      });
      assert(warningContrast.length >= 2, "both coverage warnings render");
      for (const entry of warningContrast) {
        const threshold = entry.fontSize >= 18 ? 3 : 4.5;
        assert(
          entry.ratio >= threshold,
          `warning contrast ${entry.ratio.toFixed(2)}:1 at ${entry.fontSize}px must be at least ${threshold}:1 for "${entry.text}"`,
        );
      }
      // Detail is reachable and keyboard operable.
      await summary.focus();
      assert.notEqual(await summary.evaluate((element) => getComputedStyle(element).outlineStyle), "none");
      await f.page.keyboard.press("Enter");
      assert.equal(await summary.evaluate((element) => element.parentElement.open), true);
      await f.page.keyboard.press("Space");
      assert.equal(await summary.evaluate((element) => element.parentElement.open), false);
      await settleAnimations();
      await f.snapshot("scope-essentials");
      assert.equal(plannerMutations().length, 0);
    }],
    ["Requested limit and returned count are labelled differently", async () => {
      await f.openResearch();
      await f.submitResearch("Fictional count labelling", { researchOnly: true, researchFirst: true });
      const meta = await f.page.locator(".turn-meta").first().innerText();
      assert.match(meta, /up to 50 references/, "the request limit is labelled as a limit");
      assert.match(await f.page.locator(".report").innerText(), /References: 3/, "the report shows the returned count");
      assert.equal(plannerMutations().length, 0);
    }],
    ["Edit and rerun fills the form, focuses it, and never resubmits", async () => {
      await f.openResearch();
      await f.submitResearch("Fictional edit topic", { researchOnly: true, researchFirst: true });
      const submissions = () => f.calls.filter((call) => call.path === "/api/v1/research/report").length;
      const before = submissions();
      await button("Edit and rerun").click();
      const topic = f.page.getByLabel("Topic", { exact: true });
      assert.equal(await topic.inputValue(), "Fictional edit topic");
      assert.equal(await topic.evaluate((element) => element === document.activeElement), true, "the topic field takes focus");
      assert.equal(submissions(), before, "editing must not submit on its own");
      assert.equal(plannerMutations().length, 0);
      await settleAnimations();
      await f.snapshot("research-edit-form");
    }],
    ["An in-flight generation cannot be submitted twice", async () => {
      await f.openResearch();
      f.fault({ action: "generate", mode: "delay-before" });
      const topic = f.page.getByLabel("Topic", { exact: true });
      await topic.fill("Fictional duplicate guard");
      await button("Generate research report").click();
      await f.stalled();
      assert.equal(await button("Generating report…").isDisabled(), true, "the action is disabled while busy");
      assert.equal(
        f.calls.filter((call) => call.path === "/api/v1/research/report").length,
        1,
        "only one generation request is in flight",
      );
      await f.release();
      await f.waitFor(() => f.calls.every((call) => call.completed !== false));
      assert.equal(f.calls.filter((call) => call.path === "/api/v1/research/report").length, 1);
      assert.equal(plannerMutations().length, 0);
    }],
    ["Composer sticks only where there is room and stays reachable", async () => {
      await f.openResearch();
      await f.page.setViewportSize({ width: 1440, height: 1000 });
      // Examples are available before the first run, not only after one.
      assert.equal(await f.page.locator('[aria-label="Example topics"]').isVisible(), true);
      await settleAnimations();
      await f.snapshot("home-empty-1440");
      await f.page.setViewportSize({ width: 360, height: 800 });
      await settleAnimations();
      await f.snapshot("home-empty-360");
      await f.page.setViewportSize({ width: 1440, height: 1000 });
      await f.submitResearch("Fictional composer reach", { researchOnly: true, researchFirst: true });
      // ...and they stay available while working in a session.
      assert.equal(await f.page.locator('[aria-label="Example topics"]').isVisible(), true);
      const panel = f.page.locator(".form-panel");
      assert.equal(await panel.evaluate((element) => getComputedStyle(element).position), "sticky");
      // The sidebar is narrow: its date fields must stack and stay usable.
      const dateTops = await panel.locator(".form-row").first().evaluate(
        (row) => [...row.children].map((child) => Math.round(child.getBoundingClientRect().top)),
      );
      assert.notEqual(dateTops[0], dateTops[1], "From and To stack in the narrow sidebar");
      const dateWidths = await panel.locator(".form-row input").evaluateAll(
        (elements) => elements.map((element) => Math.round(element.getBoundingClientRect().width)),
      );
      assert.ok(Math.min(...dateWidths) >= 200, `date fields must stay usable, got ${dateWidths.join("/")}`);
      // Short viewport: normal flow, so no control sits in a nested scroll area.
      await f.page.setViewportSize({ width: 1440, height: 560 });
      assert.equal(await panel.evaluate((element) => getComputedStyle(element).position), "static");
      const submit = f.page.getByRole("button", { name: "Generate research report", exact: true });
      await submit.scrollIntoViewIfNeeded();
      assert.equal(await submit.isVisible(), true, "the primary action stays reachable");
      assert.equal(await panel.evaluate((element) => getComputedStyle(element).overflowY), "visible");
      // Narrow viewport: stacked, still reachable.
      await f.page.setViewportSize({ width: 360, height: 800 });
      assert.equal(await panel.evaluate((element) => getComputedStyle(element).position), "static");
      await f.metrics("research-composer-360");
      assert.equal(plannerMutations().length, 0);
    }],
    ["Alpha brand assets load locally across workspace and authentication", async () => {
      await f.openResearch();
      const logo = f.page.locator(".brand-link .brand-art");
      await logo.waitFor();
      await f.waitFor(() => logo.evaluate((image) => image.complete && image.naturalWidth > 0));
      assert.equal(new URL(await logo.getAttribute("src"), f.origin).origin, f.origin);
      assert.equal(await f.page.getByRole("link", { name: "Trendora home", exact: true }).count(), 1);
      for (const width of [1440, 768, 360]) {
        await f.page.setViewportSize({ width, height: 1000 });
        await settleAnimations();
        await f.metrics(`alpha-home-${width}`);
        await f.snapshot(`alpha-home-${width}`);
      }
      await button("Sign out").click();
      await f.page.waitForURL(f.origin + "/login");
      const authLogo = f.page.locator(".auth-brand .brand-art");
      await f.waitFor(() => authLogo.evaluate((image) => image.complete && image.naturalWidth > 0));
      await f.page.setViewportSize({ width: 1440, height: 1000 });
      await f.snapshot("alpha-auth-1440");
      assert.equal(plannerMutations().length, 0);
    }],
    ["Default timeframe is clear without adding dates to the request; edited dates remain custom", async () => {
      await f.openResearch();
      assert.equal(await f.page.getByLabel("Preset", { exact: true }).inputValue(), "last_30d");
      assert.equal(await f.page.getByLabel("From", { exact: true }).inputValue(), "");
      assert.equal(await f.page.getByLabel("To", { exact: true }).inputValue(), "");
      await f.submitResearch("Fictional alpha default dates", { researchOnly: true });
      const request = f.calls.find((call) => call.path === "/api/v1/research/report");
      assert(request);
      assert.equal(Object.hasOwn(request.body, "date_from"), false);
      assert.equal(Object.hasOwn(request.body, "date_to"), false);
      assert.deepEqual(request.body.markets, []);
      assert.deepEqual(request.body.sources, ["youtube", "public_web"]);
      await f.page.goto(f.origin + "/test-fixtures/SimpleForm");
      assert.equal(await f.page.getByLabel("Preset", { exact: true }).inputValue(), "custom");
      assert.equal(await f.page.getByLabel("From", { exact: true }).inputValue(), "2026-08-01");
      assert.equal(await f.page.getByLabel("To", { exact: true }).inputValue(), "2026-08-31");
      assert.equal(plannerMutations().length, 0);
    }],
    ["Global saved research has readable status, scope, and a named report heading", async () => {
      await f.seedSavedReport({ topic: "Fictional global alpha report", requestMarkets: [], researchOnly: true, requestSources: ["youtube", "public_web"] });
      await f.page.goto(f.origin + "/past-reports");
      await f.page.locator(".history-row").waitFor();
      assert.equal(await f.page.locator(".history-markets").innerText(), "Global");
      assert.equal(await f.page.locator(".status-badge").innerText(), "Research complete");
      await f.snapshot("alpha-history-1440");
      await f.page.locator(".history-row").click();
      await f.page.getByRole("heading", { level: 1, name: "Fictional global alpha report", exact: true }).waitFor();
      await f.metrics("alpha-report-1440");
      await f.snapshot("alpha-report-1440");
      await f.page.setViewportSize({ width: 360, height: 900 });
      await f.metrics("alpha-report-360");
      await f.snapshot("alpha-report-360");
      await f.page.getByRole("link", { name: "All reports", exact: true }).click();
      await f.page.getByRole("heading", { name: "Saved research", exact: true }).waitFor();
      assert.equal(plannerMutations().length, 0);
    }],
    ["Research guide uses the real local font and keyboard-reachable shortcuts", async () => {
      await f.openResearch();
      await f.page.evaluate(() => document.fonts.ready.then(() => {}));
      const typography = await f.page.evaluate(() => ({
        family: getComputedStyle(document.body).fontFamily,
        faces: [...document.fonts].map((face) => ({ family: face.family, status: face.status })),
        fonts: performance.getEntriesByType("resource").filter((entry) => /\.(woff2?|ttf)(\?|$)/.test(entry.name)).map((entry) => new URL(entry.name).origin),
      }));
      assert.match(typography.family, /manrope/i);
      assert(typography.faces.some((face) => /manrope/i.test(face.family) && face.status === "loaded"), "the bundled font must actually load, not just appear in CSS");
      assert(typography.fonts.length > 0 && typography.fonts.every((origin) => origin === f.origin), "font requests stay on the app origin");
      const guide = f.page.getByRole("complementary", { name: "Start with the source.", exact: true });
      assert.equal(await guide.getByRole("heading", { name: "YouTube", exact: true }).isVisible(), true);
      assert.equal(await guide.getByRole("heading", { name: "Public web", exact: true }).isVisible(), true);
      assert.match(await guide.innerText(), /Publication dates can be unknown/);
      for (const width of [1440, 768, 360]) {
        await f.page.setViewportSize({ width, height: 1000 });
        await f.page.evaluate(() => window.scrollTo(0, 0));
        await settleAnimations();
        await f.metrics(`workbench-${width}`);
        await f.snapshot(`workbench-${width}`, { fullPage: false });
      }
      const shortcuts = guide.getByRole("navigation", { name: "Research shortcuts", exact: true });
      const history = shortcuts.getByRole("link", { name: /^Saved research/ });
      assert.equal(await history.getAttribute("href"), "/past-reports");
      await history.focus();
      assert.notEqual(await history.evaluate((element) => getComputedStyle(element).outlineStyle), "none");
      await f.snapshot("workbench-mobile-guide", { fullPage: false });
      await f.page.keyboard.press("Enter");
      await f.page.getByRole("heading", { level: 1, name: "Saved research", exact: true }).waitFor();
      await f.page.goto(f.origin + "/");
      await f.page.getByRole("navigation", { name: "Research shortcuts", exact: true }).getByRole("link", { name: /^Shared planner/ }).click();
      await f.page.getByRole("heading", { level: 1, name: "Shared planner", exact: true }).waitFor();
      assert.equal(f.calls.filter((call) => call.path === "/api/v1/research/report").length, 0, "shortcuts must never trigger generation");
      assert.equal(plannerMutations().length, 0);
    }],
  ];
}
