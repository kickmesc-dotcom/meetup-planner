import { useCallback, useEffect, useRef, useState } from "react";
import { runTaskAction } from "@/api/hr";
import { setIssueStatus } from "@/api/issues";
import {
  flushActions,
  pendingActionsCount,
  type FlushResult,
  type QueuedAction,
} from "./actionQueue";

/**
 * Отправка очереди по событию `online` и при открытии экрана.
 *
 * Таймера нет намеренно: опрос будил бы радио каждые N секунд, а связь
 * возвращается событием. Повторный вход в экран — второй повод: человек
 * вернулся в приложение, значит сеть, скорее всего, уже есть.
 *
 * `onFlushed` вызывается только когда что-то реально ушло или было отклонено:
 * иначе каждый монтаж дёргал бы инвалидацию кэша без причины.
 */
async function send(action: QueuedAction): Promise<unknown> {
  if (action.kind === "task") return runTaskAction(action.id, action.action);
  return setIssueStatus(action.id, action.status, action.comment);
}

export function useOfflineActions(onFlushed?: (result: FlushResult) => void) {
  const [pending, setPending] = useState(() => pendingActionsCount());
  const callback = useRef(onFlushed);
  callback.current = onFlushed;

  const flush = useCallback(async () => {
    if (!pendingActionsCount()) return;
    const result = await flushActions(send);
    setPending(result.left);
    if (result.sent > 0 || result.dropped > 0) callback.current?.(result);
  }, []);

  useEffect(() => {
    void flush();
    const onOnline = () => void flush();
    window.addEventListener("online", onOnline);
    return () => window.removeEventListener("online", onOnline);
  }, [flush]);

  return { pending, flush };
}
