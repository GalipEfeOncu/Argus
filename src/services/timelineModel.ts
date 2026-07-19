import type { ArgusSessionEvent } from '@/types/events';
import type { SessionProjection } from './sessionProjection';

export type TimelineEntryKind =
  | 'human'
  | 'coordinator'
  | 'specialist'
  | 'system'
  | 'tool'
  | 'assignment'
  | 'handoff'
  | 'evidence'
  | 'gate'
  | 'limit'
  | 'decision'
  | 'usage'
  | 'diff'
  | 'error';

export interface TimelineEntry {
  id: string;
  event: ArgusSessionEvent;
  kind: TimelineEntryKind;
  title: string;
  summary: string;
  relatedEventIds: string[];
  isSpecialistDetail: boolean;
}

const messageContinuationTypes = new Set<ArgusSessionEvent['type']>(['message.delta', 'message.completed']);

/** Each persisted event has a visible, typed shared-room representation. */
export function createTimelineEntries(projection: SessionProjection): TimelineEntry[] {
  const identifiers = new Map<string, string[]>();
  for (const event of projection.events) {
    for (const identifier of eventIdentifiers(event)) {
      const matching = identifiers.get(identifier) ?? [];
      identifiers.set(identifier, [...matching, event.eventId]);
    }
  }

  const events = projection.snapshot === null ? projection.events : [projection.snapshot, ...projection.events];
  return events.map((event) => {
    const descriptor = describeEvent(event, projection);
    const related = new Set<string>();
    for (const identifier of eventIdentifiers(event)) {
      for (const eventId of identifiers.get(identifier) ?? []) {
        if (eventId !== event.eventId) related.add(eventId);
      }
    }
    return { id: event.eventId, event, ...descriptor, relatedEventIds: [...related] };
  });
}

export function isTimelineEntrySpecialist(entry: TimelineEntry): boolean {
  return entry.isSpecialistDetail;
}

function describeEvent(
  event: ArgusSessionEvent,
  projection: SessionProjection,
): Omit<TimelineEntry, 'id' | 'event' | 'relatedEventIds'> {
  switch (event.type) {
    case 'message.created': {
      const message = projection.messages[event.payload.messageId];
      const target = event.payload.authorKind === 'human'
        ? (event.payload.mentionIds?.length ? `Targets: ${event.payload.mentionIds.join(', ')}` : 'Targets: Coordinator')
        : '';
      return {
        kind: event.payload.authorKind === 'human' ? 'human' : event.payload.authorKind === 'coordinator' ? 'coordinator' : event.payload.authorKind === 'agent' ? 'specialist' : 'system',
        title: event.payload.authorKind === 'human' ? 'You' : event.payload.authorId,
        summary: [message?.content ?? event.payload.content, target].filter(Boolean).join('\n'),
        isSpecialistDetail: event.payload.authorKind === 'agent',
      };
    }
    case 'message.delta':
      return { kind: 'system', title: 'Streaming update', summary: projection.messages[event.payload.messageId]?.content ?? 'A message received more content.', isSpecialistDetail: false };
    case 'message.completed':
      return { kind: 'system', title: 'Message complete', summary: projection.messages[event.payload.messageId]?.content ?? 'A streaming message completed.', isSpecialistDetail: false };
    case 'participant.status_changed':
      return { kind: 'system', title: `${event.payload.participantId} status`, summary: event.payload.actionSummary ?? event.payload.status, isSpecialistDetail: event.payload.participantKind === 'agent' };
    case 'assignment.proposed':
      return { kind: 'assignment', title: `Assignment proposed for ${event.payload.assigneeAgentId}`, summary: event.payload.objective, isSpecialistDetail: false };
    case 'assignment.created':
      return { kind: 'assignment', title: `Assignment created for ${event.payload.assigneeAgentId}`, summary: event.payload.operationClass, isSpecialistDetail: false };
    case 'assignment.started':
      return { kind: 'assignment', title: `Assignment started by ${event.payload.assigneeAgentId}`, summary: event.payload.assignmentId, isSpecialistDetail: false };
    case 'assignment.completed':
      return {
        kind: 'evidence',
        title: 'Assignment completed',
        summary: [event.payload.outputSummary, ...(event.payload.evidence ?? []).map((evidence) => `Evidence (${evidence.kind}): ${evidence.summary}`)].join('\n'),
        isSpecialistDetail: false,
      };
    case 'assignment.failed':
      return { kind: 'error', title: `Assignment failed: ${event.payload.failureCode}`, summary: event.payload.failureSummary, isSpecialistDetail: false };
    case 'assignment.cancelled':
      return { kind: 'assignment', title: 'Assignment cancelled', summary: event.payload.reasonSummary, isSpecialistDetail: false };
    case 'handoff.created':
      return { kind: 'handoff', title: 'Handoff created', summary: event.payload.summary, isSpecialistDetail: false };
    case 'tool.requested':
      return { kind: 'tool', title: `Tool requested: ${event.payload.toolName}`, summary: event.payload.requestSummary, isSpecialistDetail: true };
    case 'tool.started':
      return { kind: 'tool', title: `Tool started: ${event.payload.toolName}`, summary: event.payload.assignmentId, isSpecialistDetail: true };
    case 'tool.completed':
      return { kind: 'tool', title: `Tool ${event.payload.status}`, summary: event.payload.resultSummary, isSpecialistDetail: true };
    case 'approval.requested':
      return { kind: 'gate', title: `Approval requested: ${event.payload.capability}`, summary: event.payload.scopeSummary, isSpecialistDetail: false };
    case 'approval.resolved':
      return { kind: 'gate', title: `Approval ${event.payload.resolution}`, summary: event.payload.reasonSummary ?? 'No reason supplied.', isSpecialistDetail: false };
    case 'limit.warning':
      return { kind: 'limit', title: `Limit warning: ${event.payload.counter}`, summary: `${event.payload.current} / ${event.payload.threshold}`, isSpecialistDetail: false };
    case 'limit.reached':
      return { kind: 'limit', title: `Limit reached: ${event.payload.counter}`, summary: `${event.payload.current} / ${event.payload.threshold}`, isSpecialistDetail: false };
    case 'decision.requested':
      return { kind: 'decision', title: 'Decision requested', summary: event.payload.reasonSummary, isSpecialistDetail: false };
    case 'decision.recorded':
      return { kind: 'decision', title: `Decision: ${event.payload.choice}`, summary: event.payload.reasonSummary, isSpecialistDetail: false };
    case 'gate.status_changed':
      return { kind: 'gate', title: `${event.payload.role} gate: ${event.payload.status}`, summary: event.payload.evidence?.map((evidence) => evidence.summary).join('; ') ?? 'No evidence recorded.', isSpecialistDetail: false };
    case 'artifact.diff_updated':
      return { kind: 'diff', title: `Diff updated: ${event.payload.filePath}`, summary: `+${event.payload.additions} −${event.payload.deletions} · ${event.payload.byteLength} bytes`, isSpecialistDetail: false };
    case 'usage.updated':
      return { kind: 'usage', title: 'Usage updated', summary: `${event.payload.inputTokens} input / ${event.payload.outputTokens} output tokens`, isSpecialistDetail: false };
    case 'error.created':
      return { kind: 'error', title: `${event.payload.code}${event.payload.recoverable ? ' (recoverable)' : ''}`, summary: event.payload.summary, isSpecialistDetail: false };
    case 'session.configuration_updated':
      return { kind: 'system', title: 'Session configuration updated', summary: event.payload.changedFields.join(', '), isSpecialistDetail: false };
    case 'session.status_changed':
      return { kind: 'system', title: `Session ${event.payload.status}`, summary: event.payload.reasonSummary ?? 'Session lifecycle changed.', isSpecialistDetail: false };
    case 'session.snapshot':
      return { kind: 'system', title: 'Session snapshot', summary: `Status: ${event.payload.status}`, isSpecialistDetail: false };
  }
}

function eventIdentifiers(event: ArgusSessionEvent): string[] {
  const identifiers = [event.eventId, event.correlationId].filter((value): value is string => typeof value === 'string');
  switch (event.type) {
    case 'message.created': case 'message.delta': case 'message.completed': identifiers.push(event.payload.messageId); break;
    case 'assignment.proposed': identifiers.push(event.payload.proposalId, ...(event.payload.parentId ? [event.payload.parentId] : [])); break;
    case 'assignment.created': identifiers.push(event.payload.assignmentId, event.payload.proposalId); break;
    case 'assignment.started': case 'assignment.failed': case 'assignment.cancelled': identifiers.push(event.payload.assignmentId); break;
    case 'assignment.completed': identifiers.push(event.payload.assignmentId, ...((event.payload.evidence ?? []).flatMap((evidence) => evidence.artifactIds ?? []))); break;
    case 'handoff.created': identifiers.push(event.payload.handoffId, event.payload.sourceAssignmentId, ...(event.payload.targetAgentId ? [event.payload.targetAgentId] : []), ...(event.payload.artifactIds ?? [])); break;
    case 'tool.requested': case 'tool.started': case 'tool.completed': identifiers.push(event.payload.toolExecutionId, event.payload.assignmentId, ...(('artifactIds' in event.payload ? event.payload.artifactIds : undefined) ?? [])); break;
    case 'approval.requested': identifiers.push(event.payload.approvalId, ...(event.payload.assignmentId ? [event.payload.assignmentId] : [])); break;
    case 'approval.resolved': identifiers.push(event.payload.approvalId, ...(event.payload.grantId ? [event.payload.grantId] : [])); break;
    case 'decision.requested': case 'decision.recorded': identifiers.push(event.payload.decisionId, ...('scopeId' in event.payload ? [event.payload.scopeId] : [])); break;
    case 'gate.status_changed': identifiers.push(event.payload.gateId, ...((event.payload.evidence ?? []).flatMap((evidence) => evidence.artifactIds ?? []))); break;
    case 'artifact.diff_updated': identifiers.push(event.payload.artifactId, ...(event.payload.assignmentId ? [event.payload.assignmentId] : [])); break;
    case 'usage.updated': identifiers.push(event.payload.scopeId); break;
    case 'error.created': identifiers.push(event.payload.errorId, ...(event.payload.relatedId ? [event.payload.relatedId] : [])); break;
    case 'limit.warning': case 'limit.reached': identifiers.push(event.payload.scopeId); break;
    default: break;
  }
  return identifiers;
}

export function isMessageContinuation(event: ArgusSessionEvent): boolean {
  return messageContinuationTypes.has(event.type);
}
