import React, { useCallback, useEffect, useState } from 'react';
import { api } from '@/services/api';
import type { components } from '@/types/generated/rest';
import './AcceptanceReview.css';

type Review = components['schemas']['AcceptanceReviewResponse'];
type Disposition = 'retain' | 'cleanup';

function commandId(action: string): string {
  return `acceptance-${action}-${crypto.randomUUID()}`;
}

export const AcceptanceReview: React.FC<{ sessionId: string; status: string | null }> = ({ sessionId, status }) => {
  const [review, setReview] = useState<Review | null>(null);
  const [disposition, setDisposition] = useState<Disposition>('retain');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [followUpGoal, setFollowUpGoal] = useState('');
  const terminal = status === 'completed' || status === 'completed_partial';

  const refresh = useCallback(async () => {
    setError(null);
    try {
      setReview(await api.sessions.acceptance(sessionId));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Review details could not be loaded.');
    }
  }, [sessionId]);

  useEffect(() => {
    if (terminal) void refresh();
    else setReview(null);
  }, [terminal, refresh]);

  if (!terminal) return null;

  const act = async (action: 'apply' | 'reject' | 'export' | 'follow_up') => {
    if (action === 'follow_up' && !followUpGoal.trim()) {
      setError('Describe the follow-up goal first.');
      return;
    }
    setPending(true);
    setError(null);
    try {
      const result = await api.sessions.acceptanceAction(sessionId, {
        commandId: commandId(action), action, disposition,
        ...(action === 'apply' && review?.originalChecksum ? { expectedOriginalChecksum: review.originalChecksum } : {}),
        ...(action === 'follow_up' ? { followUpGoal: followUpGoal.trim() } : {}),
      });
      if (action === 'export' && result.state === 'exported') {
        const exported = await api.sessions.acceptancePatch(sessionId);
        const url = URL.createObjectURL(new Blob([exported.patch], { type: 'text/x-diff' }));
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = `${sessionId}-argus-review.patch`;
        anchor.click();
        URL.revokeObjectURL(url);
      }
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The acceptance action could not be completed.');
    } finally {
      setPending(false);
    }
  };

  return <section className="acceptance-review" aria-label="Review and accept isolated changes">
    <div className="acceptance-review__heading"><h3>Review isolated changes</h3><button type="button" onClick={() => void refresh()} disabled={pending}>Refresh</button></div>
    {error !== null && <p className="acceptance-review__error" role="alert">{error}</p>}
    {review === null ? <p>Loading review evidence…</p> : <>
      {review.drifted && <p className="acceptance-review__warning" role="status">The original project changed after this session began. Applying is blocked; export the patch or retain this workspace to resolve the conflict safely.</p>}
      <p>{review.files.length} changed file(s), {review.artifacts.length} artifact(s), {review.unmetGates.length} unmet gate(s).</p>
      <ul className="acceptance-review__files" aria-label="Changed files">{review.files.slice(0, 20).map((file) => <li key={file.path}><code>{file.path}</code> — {file.change} (+{file.additions}/-{file.deletions})</li>)}</ul>{review.files.length > 20 && <p>{review.files.length - 20} more changed files are available in the full review.</p>}
      {review.coordinatorSummary !== null && <p><strong>Coordinator:</strong> {review.coordinatorSummary}</p>}
      {review.unmetGates.length > 0 && <p><strong>Unmet:</strong> {review.unmetGates.join(', ')}</p>}
      <details><summary>Evidence and gates</summary><ul>{review.artifacts.map((artifact) => <li key={artifact.id}>{artifact.kind}: {artifact.relativePath ?? artifact.checksum}</li>)}{review.gates.map((gate) => <li key={gate.id}>{gate.role}: {gate.status} ({gate.evidenceCount} evidence)</li>)}</ul></details>
      <details><summary>Limits and usage</summary><ul>{review.limits.length === 0 ? <li>No limit events.</li> : review.limits.map((limit, index) => <li key={`${String(limit.counter)}-${index}`}>{String(limit.counter)}: {String(limit.current)}/{String(limit.threshold)} ({limit.hard === true ? 'hard' : 'warning'})</li>)}</ul><p>Tokens: {review.usage.inputTokens + review.usage.outputTokens}; cost: {review.usage.normalizedCost ?? 'unavailable'}; duration: {Math.round(review.usage.durationMs / 1000)}s.</p></details>
      <fieldset disabled={pending}><legend>After this action</legend><label><input type="radio" name={`disposition-${sessionId}`} checked={disposition === 'retain'} onChange={() => setDisposition('retain')} /> Keep isolated workspace</label><label><input type="radio" name={`disposition-${sessionId}`} checked={disposition === 'cleanup'} onChange={() => setDisposition('cleanup')} /> Clean up isolated workspace</label></fieldset>
      <div className="acceptance-review__actions"><button type="button" onClick={() => void act('apply')} disabled={!review.canApply || pending}>Apply to original project</button><button type="button" onClick={() => void act('reject')} disabled={pending}>Reject changes</button><button type="button" onClick={() => void act('export')} disabled={!review.patchAvailable || pending || disposition !== 'retain'}>Export patch</button></div>
      <label className="acceptance-review__followup">Follow-up goal <input value={followUpGoal} onChange={(event) => setFollowUpGoal(event.target.value)} disabled={pending} /></label><button type="button" onClick={() => void act('follow_up')} disabled={pending}>Start follow-up</button>
      {review.latestAction !== undefined && review.latestAction !== null && <p className="acceptance-review__status" role="status">{review.latestAction.summary}</p>}
    </>}
  </section>;
};
