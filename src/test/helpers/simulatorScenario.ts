import { EventSimulator, type SimulatorClock } from '@/services/eventSimulator';

type SimulatorTimer = ReturnType<typeof setTimeout>;

interface ScheduledTask {
  id: number;
  dueAt: number;
  callback: () => void;
  cancelled: boolean;
}

/** A deterministic timer implementation for simulator scenarios. */
export class FakeClock implements SimulatorClock {
  private currentTime: number;
  private nextTimerId = 1;
  private readonly tasks = new Map<number, ScheduledTask>();

  constructor(startTime = 1_700_000_000_000) {
    this.currentTime = startTime;
  }

  now(): number {
    return this.currentTime;
  }

  setTimeout(callback: () => void, delayMs: number): SimulatorTimer {
    const id = this.nextTimerId++;
    this.tasks.set(id, {
      id,
      dueAt: this.currentTime + delayMs,
      callback,
      cancelled: false,
    });
    return id as unknown as SimulatorTimer;
  }

  clearTimeout(timer: SimulatorTimer): void {
    const task = this.tasks.get(Number(timer));
    if (task) task.cancelled = true;
  }

  advanceBy(delayMs: number): void {
    const deadline = this.currentTime + delayMs;
    while (true) {
      const nextTask = [...this.tasks.values()]
        .filter((task) => !task.cancelled && task.dueAt <= deadline)
        .sort((left, right) => left.dueAt - right.dueAt || left.id - right.id)[0];
      if (!nextTask) break;

      this.tasks.delete(nextTask.id);
      this.currentTime = nextTask.dueAt;
      nextTask.callback();
    }
    this.currentTime = deadline;
  }
}

/** Predictable opaque IDs for assertions that must not depend on crypto globals. */
export class SequentialIdGenerator {
  private sequence = 0;

  next(): string {
    this.sequence += 1;
    return `sim_${this.sequence}`;
  }
}

export interface SimulatorScenario {
  clock: FakeClock;
  ids: SequentialIdGenerator;
  simulator: EventSimulator;
}

export function createSimulatorScenario(startTime?: number): SimulatorScenario {
  const clock = new FakeClock(startTime);
  const ids = new SequentialIdGenerator();
  return {
    clock,
    ids,
    simulator: new EventSimulator({
      clock,
      createId: () => ids.next(),
    }),
  };
}
