"use client";

import { useEffect, useState } from "react";

const LINES = [
  { words: ["What", "would", "you", "like", "to", "research?"], accent: 5 },
  { words: ["Explore", "a", "topic.", "Follow", "the", "sources."], accent: 3 },
  { words: ["Turn", "your", "research", "into", "a", "plan."], accent: 5 },
] as const;

export function ResearchHeadline({ active }: { active: boolean }) {
  const [index, setIndex] = useState(0);
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const onVisibility = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  useEffect(() => {
    if (!active || !visible) return;
    const timer = window.setInterval(() => {
      setIndex((current) => (current + 1) % LINES.length);
    }, 5600);
    return () => window.clearInterval(timer);
  }, [active, visible]);

  const displayIndex = active && visible ? index : 0;

  return (
    <h1 className="research-headline" id="headline">
      <span className="sr-only">What would you like to research?</span>
      <span
        className="research-headline-visual"
        aria-hidden="true"
        data-active={active && visible ? "true" : "false"}
        data-index={displayIndex}
      >
        {LINES.map((line, lineIndex) => (
          <span
            key={`${lineIndex}-${displayIndex}`}
            className={`research-headline-line ${lineIndex === displayIndex ? "is-on" : ""}`}
          >
            {lineIndex === displayIndex ? (
              line.words.map((word, wordIndex) => (
                <span key={wordIndex}>
                  <span className={`research-headline-word ${wordIndex === line.accent ? "research-headline-accent" : ""}`}>
                    {word}
                  </span>
                  {wordIndex < line.words.length - 1 ? " " : null}
                </span>
              ))
            ) : (
              <span className="research-headline-word">{line.words.join(" ")}</span>
            )}
          </span>
        ))}
      </span>
    </h1>
  );
}
