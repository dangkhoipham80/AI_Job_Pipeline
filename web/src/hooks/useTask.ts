import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Task } from "@/types";

/** Slow enough to be a safety net, not a load generator. */
const POLL_MS = 1500;

export const isActive = (task: Task | null): boolean =>
  task?.status === "queued" || task?.status === "running";

/**
 * Follow one background task to completion.
 *
 * Updates arrive two ways, on purpose. The WebSocket bumps `version` on every
 * `task_updated`, which re-runs this effect immediately — that's the fast path
 * and where the progress line comes from. Underneath it, a slow poll runs while
 * the task is unfinished, so a dropped socket leaves the page a second or two
 * behind instead of waiting forever on a spinner.
 *
 * Pass `null` to stop following.
 */
export function useTask(taskId: string | null, version: number): Task | null {
  const [task, setTask] = useState<Task | null>(null);
  /** Which task id has already reached a terminal state — see below. */
  const settled = useRef<string | null>(null);

  useEffect(() => {
    if (!taskId) {
      setTask(null);
      settled.current = null;
      return;
    }
    // Once a task is finished nothing can change it, but `version` keeps
    // bumping on unrelated events (another task's progress, a job update).
    // Without this, a busy crawl would re-GET a done task on every frame.
    if (settled.current === taskId) return;

    let alive = true;
    let timer: ReturnType<typeof setTimeout>;

    const tick = async () => {
      try {
        const next = await api.task(taskId);
        if (!alive) return;
        setTask(next);
        if (isActive(next)) timer = setTimeout(tick, POLL_MS);
        else settled.current = taskId;
      } catch (e) {
        if (!alive) return;
        // A 404 is terminal: the queue only keeps the last 50 tasks, so ours is
        // gone and no amount of polling brings it back. Say so, rather than
        // leaving the caller's spinner up forever waiting on a ghost.
        if (e instanceof ApiError && e.status === 404) {
          settled.current = taskId;
          setTask((prev) =>
            prev && isActive(prev)
              ? { ...prev, status: "failed", error: "lost track of this task", error_kind: "Evicted" }
              : prev,
          );
          return;
        }
        // Anything else is transient — a blip while the API restarts, say. Keep
        // polling: giving up here is exactly when the poll is needed most, and
        // it would strand the page mid-task with the buttons disabled.
        timer = setTimeout(tick, POLL_MS);
      }
    };

    tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [taskId, version]);

  return task;
}
