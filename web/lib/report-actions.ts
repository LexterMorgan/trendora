/**
 * Report output actions: Markdown copy and exact JSON download. Uses returned
 * content only; no invented text.
 */

import type { ContentBriefJson, ContentIdeaJson, ResearchReportResponse } from "@/lib/report-api";

export function ideaMarkdown(idea: ContentIdeaJson): string {
  const lines = [
    `## ${idea.title}`,
    "",
    `**Angle:** ${idea.angle}`,
    "",
    `**Opportunity indexes:** ${idea.opportunity_indexes.join(", ") || "—"}`,
    "",
    `**Citations:** ${idea.citations.length}`,
  ];
  return lines.join("\n");
}

export function briefMarkdown(brief: ContentBriefJson): string {
  const lines = [
    "## Content Brief",
    "",
    `**Idea index:** ${brief.idea_index}`,
    "",
    `**Objective:** ${brief.objective}`,
    "",
    `**Format:** ${brief.format}`,
    "",
    `**Hook:** ${brief.hook}`,
    "",
    "**Outline:**",
    ...brief.outline.map((item) => `- ${item}`),
  ];
  return lines.join("\n");
}

export async function copyToClipboard(text: string): Promise<void> {
  if (!navigator.clipboard || !navigator.clipboard.writeText) {
    throw new Error("Clipboard is not available in this browser.");
  }
  await navigator.clipboard.writeText(text);
}

export function downloadReportJson(report: ResearchReportResponse): void {
  const blob = new Blob([JSON.stringify(report, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "trendora-report.json";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
