import assert from "node:assert/strict";

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export function cancellationRegressions(f) {
  return [
    ["Discover cancel restores the form and ignores a late result", async () => {
      await f.page.goto(f.origin + "/discover");
      const input = f.page.getByLabel("Search the public web", { exact: true });
      await input.fill("fictional discover cancellation");
      f.fault({ action: "discover", mode: "delay-before" });
      await f.page.getByRole("button", { name: "Search", exact: true }).click();
      await f.stalled();

      const cancel = f.page.getByRole("button", { name: "Cancel search", exact: true });
      assert.equal(await cancel.isVisible(), true);
      await cancel.click();

      assert.equal(await input.isEnabled(), true);
      assert.equal(await input.inputValue(), "fictional discover cancellation");
      await f.page.getByText("Stopped waiting. The search service may still finish", { exact: false }).waitFor();
      await f.page.waitForFunction(() => document.activeElement?.id === "discover-query");
      await f.release();
      await delay(100);
      assert.equal(await f.page.locator(".discover-result").count(), 0, "late result must not render");
      assert.match(await f.page.getByText("Stopped waiting. The search service may still finish", { exact: false }).innerText(), /may still finish/);
      await f.snapshot("discover-cancelled");

      await f.page.getByRole("button", { name: "Search", exact: true }).click();
      await f.page.locator(".discover-result").waitFor();
      assert.equal(await f.page.locator(".discover-result").count(), 1);
      assert.equal(f.calls.filter((call) => call.path === "/api/v1/discover").length, 2, "explicit retry only");
    }],
    ["Research cancel restores the form, preserves the turn, and allows one explicit rerun", async () => {
      await f.page.goto(f.origin + "/");
      await f.page.getByLabel("Topic", { exact: true }).fill("fictional research cancellation");
      await f.page.getByRole("button", { name: "Continue", exact: true }).click();
      const topic = f.page.getByLabel("Topic", { exact: true });
      await topic.fill("fictional research cancellation");
      f.fault({ action: "generate", mode: "delay-before" });
      await f.page.getByRole("button", { name: "Generate research report", exact: true }).click();
      await f.stalled();
      await f.page.getByRole("button", { name: "Cancel research", exact: true }).click();

      const restored = f.page.getByLabel("Topic", { exact: true });
      assert.equal(await restored.isEnabled(), true);
      assert.equal(await restored.inputValue(), "fictional research cancellation");
      await f.page.getByText("Stopped waiting. The run may continue", { exact: false }).waitFor();
      await f.page.waitForFunction(() => document.activeElement?.id === "topic");
      assert.equal(await f.page.locator(".report").count(), 0, "cancelled turn must not display a report");
      assert.equal(await f.page.locator(".turn").count(), 0, "the cancelled run is held out of the setup form");
      await f.snapshot("research-cancelled-setup");

      // Start the explicit rerun while the cancelled request is still held,
      // then release the old response last.
      await f.page.getByRole("button", { name: "Generate research report", exact: true }).click();
      await f.page.locator(".report").waitFor();
      await f.release();
      await delay(100);
      assert.equal(await f.page.locator(".report").count(), 1, "the late cancelled response cannot replace the newer report");
      assert.equal(await f.page.locator(".turn").count(), 2, "the cancelled attempt and the newer result remain distinct");
      assert.equal(f.calls.filter((call) => call.path === "/api/v1/research/report").length, 2);
    }],
    ["Cancellation controls fit a narrow viewport", async () => {
      await f.page.setViewportSize({ width: 390, height: 844 });
      await f.page.goto(f.origin + "/discover");
      await f.page.getByLabel("Search the public web", { exact: true }).fill("fictional mobile cancellation");
      f.fault({ action: "discover", mode: "delay-before" });
      await f.page.getByRole("button", { name: "Search", exact: true }).click();
      await f.stalled();
      const cancel = f.page.getByRole("button", { name: "Cancel search", exact: true });
      const box = await cancel.boundingBox();
      assert.ok(box);
      assert.ok(box.height >= 44, "cancel control should keep a 44px target");
      assert.equal(await f.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      await cancel.focus();
      await f.page.keyboard.press("Enter");
      await f.page.waitForFunction(() => document.activeElement?.id === "discover-query");
      await f.release();
    }],
  ];
}
