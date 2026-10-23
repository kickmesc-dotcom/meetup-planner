import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchPushConfig,
  fetchPushDevices,
  sendTestPush,
  subscribePush,
  unsubscribePush,
  urlBase64ToUint8Array,
} from "@/api/push";
import { humanizeApiError, isEndpointMissing } from "@/api/client";
import Icon from "@/components/Icon";
import { haptic, showAlert } from "@/tg/webapp";

/**
 * «Уведомления в браузере» — push без Telegram.
 *
 * Зачем в профиле, а не только в настройках телефона. Разрешение спрашивается
 * один раз и навсегда для сайта; человек должен понимать, зачем он его даёт.
 * Здесь же видно, сколько устройств получает уведомления: «включил, а не
 * приходит» чаще всего значит, что подписка осталась на старом телефоне.
 *
 * Карточка молчит, если push не настроен на сервере или браузер его не умеет:
 * кнопка, которая гарантированно падает, хуже её отсутствия.
 */
export default function PushCard() {
  const supported =
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window;

  const configQ = useQuery({
    queryKey: ["push-config"],
    queryFn: fetchPushConfig,
    retry: false,
    staleTime: 5 * 60_000,
    enabled: supported,
  });
  const devicesQ = useQuery({
    queryKey: ["push-devices"],
    queryFn: fetchPushDevices,
    retry: false,
    staleTime: 60_000,
    enabled: supported && Boolean(configQ.data?.enabled),
  });

  const [subscribed, setSubscribed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [denied, setDenied] = useState(
    typeof Notification !== "undefined" && Notification.permission === "denied",
  );

  useEffect(() => {
    if (!supported) return;
    let alive = true;
    void navigator.serviceWorker.ready
      .then((reg) => reg.pushManager.getSubscription())
      .then((sub) => {
        if (alive) setSubscribed(Boolean(sub));
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [supported]);

  if (!supported) return null;
  if (configQ.isError && isEndpointMissing(configQ.error)) return null;
  if (!configQ.data?.enabled) return null;
  const publicKey = configQ.data.public_key;

  const toggle = async () => {
    setBusy(true);
    try {
      const reg = await navigator.serviceWorker.ready;
      if (subscribed) {
        const sub = await reg.pushManager.getSubscription();
        if (sub) {
          await unsubscribePush(sub.endpoint).catch(() => undefined);
          await sub.unsubscribe();
        }
        setSubscribed(false);
        haptic("light");
        return;
      }
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setDenied(permission === "denied");
        await showAlert(
          "Браузер не разрешил уведомления. Это меняется в настройках сайта — тогда вернись и включи снова.",
        );
        return;
      }
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(publicKey),
      });
      const json = sub.toJSON();
      await subscribePush({
        endpoint: sub.endpoint,
        keys: {
          p256dh: json.keys?.p256dh ?? "",
          auth: json.keys?.auth ?? "",
        },
        user_agent: navigator.userAgent.slice(0, 500),
      });
      setSubscribed(true);
      haptic("success");
    } catch (e) {
      await showAlert(humanizeApiError(e));
    } finally {
      setBusy(false);
    }
  };

  const devices = devicesQ.data?.length ?? 0;

  return (
    <section
      data-testid="push-card"
      className="rounded-card bg-tg-secondary-bg/60 p-3"
    >
      <div className="flex items-start gap-2">
        <Icon name="bell" size={18} className="mt-0.5 text-tg-hint" />
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-tg-text">
            Уведомления в браузере
          </h3>
          <p className="mt-1 text-xs text-tg-hint">
            Напоминание о сроке придёт на телефон, даже если приложение закрыто.
            Telegram для этого не нужен.
          </p>
        </div>
      </div>

      <button
        type="button"
        disabled={busy}
        onClick={() => void toggle()}
        className="mt-2 min-h-11 w-full rounded-tile bg-tg-button px-3 text-xs font-medium text-tg-button-text disabled:opacity-60"
      >
        {busy
          ? "Подожди…"
          : subscribed
            ? "Выключить на этом устройстве"
            : "Включить уведомления"}
      </button>

      {denied && (
        <p className="mt-2 text-2xs text-tg-hint">
          Разрешение уже запрещено в браузере. Открой настройки сайта и разреши
          уведомления — кнопка выше сработает.
        </p>
      )}

      {subscribed && (
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className="text-2xs text-tg-hint">
            Устройств с уведомлениями: {devices || 1}
          </span>
          <button
            type="button"
            onClick={() => {
              void sendTestPush()
                .then((res) => {
                  haptic("success");
                  return showAlert(
                    res.sent > 0
                      ? "Проверочное уведомление отправлено."
                      : "Подписка сохранена, но push-сервис не принял отправку. Попробуй выключить и включить снова.",
                  );
                })
                .catch((e) => showAlert(humanizeApiError(e)));
            }}
            className="min-h-8 shrink-0 rounded-full px-2 text-2xs text-tg-link"
          >
            Проверить
          </button>
        </div>
      )}
    </section>
  );
}
