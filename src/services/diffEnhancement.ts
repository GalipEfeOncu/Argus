import { codeToHtml } from 'shiki';

/** Loaded only after a user opens a diff enhancement; metadata stays readable without it. */
export async function highlightDiffMetadata(summary: string): Promise<string> {
  return codeToHtml(summary, { lang: 'text', theme: 'github-dark' });
}
