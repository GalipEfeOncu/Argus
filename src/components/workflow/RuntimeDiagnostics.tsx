import { useEffect, useState } from 'react';
import { api } from '@/services/api';
import { tauriCommands } from '@/services/tauri';
import type { components } from '@/types/generated/rest';

type RuntimeHealth = components['schemas']['RuntimeHealthResponse'];

interface RuntimeDiagnosticsProps {
  sessionId: string;
}

const actionForUnavailableSidecar = 'Restart the Argus desktop app. Active sessions recover safely; do not retry a mutating action until the timeline confirms its outcome.';

export function RuntimeDiagnostics({ sessionId }: RuntimeDiagnosticsProps) {
  const [health, setHealth] = useState<RuntimeHealth | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [credentialStoreUnavailable, setCredentialStoreUnavailable] = useState(false);

  const refresh = () => {
    setError(null);
    void api.runtime.health().then(setHealth).catch(() => {
      setHealth(null);
      setError('The local sidecar is unavailable.');
    });
  };

  useEffect(() => {
    refresh();
    if ('__TAURI_INTERNALS__' in window) {
      void tauriCommands.credentialStoreAvailable().then((available) => setCredentialStoreUnavailable(!available)).catch(() => setCredentialStoreUnavailable(true));
    }
  }, []);

  const exportBundle = async () => {
    setExporting(true);
    try {
      const bundle = await api.runtime.supportBundle([sessionId]);
      const url = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' }));
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `argus-support-${new Date(bundle.createdAtMs).toISOString().slice(0, 10)}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch {
      setError('The support bundle could not be exported.');
    } finally {
      setExporting(false);
    }
  };

  const degradedChecks = [
    ...(health?.checks.filter((check) => check.status === 'degraded') ?? []),
    ...(credentialStoreUnavailable ? [{ code: 'credential_store_unavailable', status: 'degraded' as const, summary: 'The operating-system credential store is unavailable.', action: 'Restore access to the credential store, then refresh provider credentials before retrying provider work.' }] : []),
  ];
  const newestEventAgeMs = health?.eventLag.newestEventAgeMs;
  return <section className="runtime-diagnostics" aria-label="Runtime diagnostics">
    <div className="runtime-diagnostics__heading"><h3>Local diagnostics</h3><button type="button" onClick={refresh}>Refresh</button></div>
    {error !== null
      ? <div className="runtime-diagnostics__alert" role="alert"><strong>Sidecar unavailable</strong><p>{error} {actionForUnavailableSidecar}</p></div>
      : health === null
        ? <p>Checking local runtime health…</p>
        : <>
          <p role="status">{health.status === 'healthy' ? 'Healthy — local runtime checks are passing.' : 'Degraded — review the recovery guidance before continuing.'}</p>
          {degradedChecks.length > 0 && <div className="runtime-diagnostics__alert" role="alert"><strong>Action needed</strong><ul>{degradedChecks.map((check) => <li key={check.code}><span>{check.summary}</span>{check.action !== null && <small>{check.action}</small>}</li>)}</ul></div>}
          <details><summary>Queues, leases, latency, and usage</summary><ul>
            <li>Running assignments: {health.queues.runnableAssignments}; active tools: {health.queues.activeToolExecutions}; provider operations: {health.queues.activeProviderOperations}.</li>
            <li>Writer leases: {health.writerLeases.active} active, {health.writerLeases.expiredUnreleased} expired but unreleased.</li>
            <li>Newest event age: {newestEventAgeMs === null || newestEventAgeMs === undefined ? 'no events yet' : `${Math.round(newestEventAgeMs / 1000)}s`}; invalid events: {health.eventLag.invalidPayloads}.</li>
            <li>Usage: {health.usage.inputTokens + health.usage.outputTokens} tokens across {health.usage.samples} updates; cost: {health.usage.normalizedCost ?? 'unavailable'}.</li>
          </ul>{health.providerLatency.length > 0 && <ul>{health.providerLatency.map((provider) => <li key={provider.operationKind}>{provider.operationKind}: {provider.completed} completed, average latency {provider.averageLatencyMs ?? 'unavailable'}ms, failures {provider.failed}.</li>)}</ul>}</details>
        </>}
    <button type="button" onClick={() => void exportBundle()} disabled={exporting}>{exporting ? 'Preparing support bundle…' : 'Export redacted support bundle'}</button>
    <p className="runtime-diagnostics__note">The bundle includes configuration shapes, event counts, and redacted local diagnostics. It never includes credentials, raw prompts, private reasoning, project paths, or project file contents.</p>
  </section>;
}
