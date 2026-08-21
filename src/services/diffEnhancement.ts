import { createHighlighterCore } from 'shiki/core';
import { createJavaScriptRegexEngine } from 'shiki/engine/javascript';
import githubDark from 'shiki/themes/github-dark.mjs';

const highlighter = createHighlighterCore({
  themes: [githubDark],
  langs: [],
  engine: createJavaScriptRegexEngine(),
});

/** Loaded only after a user opens a diff enhancement; metadata stays readable without it. */
export async function highlightDiffMetadata(summary: string): Promise<string> {
  return (await highlighter).codeToHtml(summary, { lang: 'text', theme: 'github-dark' });
}
