/**
 * Применяет бренд организации ко всему приложению (B2B_PLATFORM_PLAN, 4.4).
 *
 * Зачем отдельный компонент, а не хук в `App`. Бренд нужен до первого экрана
 * (заголовок вкладки и цвет ссылок), а `App` занят маршрутизацией и правами.
 * Здесь ровно одна обязанность: получить бренд и нанести его на документ.
 *
 * Почему запрос выключен без входа. До авторизации `/api/brand` отвечает 401,
 * и каждый старт приложения писал бы ошибку в консоль и в логи сервера. Бренд
 * показываем вошедшему — до этого человек видит нейтральную оболочку.
 *
 * Почему переопределяется `--tg-theme-link-color`. Акцент в приложении один:
 * кнопки, ссылки, полосы. Менять его точечно в каждом компоненте значило бы
 * забыть половину; переменная темы — единственная точка.
 */
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchBrand } from "@/api/brand";
import { getSessionToken } from "@/api/client";
import { getInitData } from "@/tg/webapp";

export default function BrandApplier() {
  const inTelegram = Boolean((getInitData() ?? "").length);
  const q = useQuery({
    queryKey: ["brand"],
    queryFn: fetchBrand,
    staleTime: 5 * 60_000,
    retry: false,
    enabled: inTelegram || Boolean(getSessionToken()),
  });

  const brand = q.data;

  useEffect(() => {
    if (!brand) return;
    const root = document.documentElement;
    if (brand.color) root.style.setProperty("--tg-theme-link-color", brand.color);
    document.title = `${brand.name} — смены и задачи`;
  }, [brand]);

  return null;
}
