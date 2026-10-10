/**
 * GHG11(13): полноэкранный просмотр медиа из ленты.
 *
 * Раньше лайтбокс рисовался прямо внутри карточки ленты (`fixed inset-0`), но у
 * карточки есть `transform`/`overflow-hidden` — из-за этого «полный экран»
 * оказывался размером с карточку и картинку обрезало. Теперь:
 *
 *  1. лист рендерится через портал в `document.body`, поэтому никакой
 *     transformed-предок его не режет;
 *  2. картинка показывается ЦЕЛИКОМ (`object-contain`), а не «по размеру
 *     обрезки»;
 *  3. её можно таскать пальцем, зумить пинчем/колесом и двойным тапом.
 */
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

const MIN_SCALE = 1;
const MAX_SCALE = 5;

interface Props {
  src: string;
  alt?: string;
  onClose: () => void;
}

function clampScale(v: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, v));
}

export default function MediaLightbox({ src, alt = "", onClose }: Props) {
  const [scale, setScale] = useState(1);
  const [tx, setTx] = useState(0);
  const [ty, setTy] = useState(0);
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const lastTap = useRef(0);
  // Одиночный жест: стартовые координаты и базовый сдвиг.
  const drag = useRef<{ x: number; y: number; tx: number; ty: number } | null>(null);
  // Пинч: дистанция/точка старта и базовый масштаб.
  const pinch = useRef<{
    dist: number;
    scale: number;
    tx: number;
    ty: number;
  } | null>(null);
  const moved = useRef(false);

  // Пока открыт лайтбокс, страница под ним не скроллится.
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const reset = () => {
    setScale(1);
    setTx(0);
    setTy(0);
  };

  // Масштаб 1x — сдвиг всегда возвращаем на место: «зума нет, значит картинка
  // стоит по центру», иначе её можно случайно утащить за край.
  const applyScale = (next: number) => {
    const s = clampScale(next);
    setScale(s);
    if (s <= MIN_SCALE) {
      setTx(0);
      setTy(0);
    }
  };

  const onTouchStart = (e: React.TouchEvent) => {
    moved.current = false;
    if (e.touches.length >= 2) {
      const [a, b] = [e.touches[0], e.touches[1]];
      pinch.current = {
        dist: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY),
        scale,
        tx,
        ty,
      };
      drag.current = null;
      return;
    }
    const t = e.touches[0];
    drag.current = { x: t.clientX, y: t.clientY, tx, ty };
  };

  const onTouchMove = (e: React.TouchEvent) => {
    if (pinch.current && e.touches.length >= 2) {
      const [a, b] = [e.touches[0], e.touches[1]];
      const dist = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
      if (pinch.current.dist > 0) {
        moved.current = true;
        applyScale((pinch.current.scale * dist) / pinch.current.dist);
      }
      return;
    }
    const d = drag.current;
    if (!d) return;
    const t = e.touches[0];
    const dx = t.clientX - d.x;
    const dy = t.clientY - d.y;
    if (Math.abs(dx) > 4 || Math.abs(dy) > 4) moved.current = true;
    if (scale > MIN_SCALE) {
      setTx(d.tx + dx);
      setTy(d.ty + dy);
    }
  };

  const onTouchEnd = (e: React.TouchEvent) => {
    if (e.touches.length === 1) {
      // Перешли из пинча в перетаскивание одним пальцем.
      const t = e.touches[0];
      drag.current = { x: t.clientX, y: t.clientY, tx, ty };
      pinch.current = null;
      return;
    }
    if (e.touches.length === 0) {
      drag.current = null;
      pinch.current = null;
      maybeDoubleTap();
    }
  };

  const maybeDoubleTap = () => {
    if (moved.current) return;
    const now = Date.now();
    if (now - lastTap.current < 300) {
      // Двойной тап: 1x ↔ 2.5x.
      if (scale > MIN_SCALE) reset();
      else applyScale(2.5);
      lastTap.current = 0;
      return;
    }
    lastTap.current = now;
  };

  // Мышь/трекпад: перетаскивание и колесо (для десктопного превью).
  const onMouseDown = (e: React.MouseEvent) => {
    moved.current = false;
    drag.current = { x: e.clientX, y: e.clientY, tx, ty };
  };
  const onMouseMove = (e: React.MouseEvent) => {
    const d = drag.current;
    if (!d || e.buttons !== 1) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (Math.abs(dx) > 4 || Math.abs(dy) > 4) moved.current = true;
    if (scale > MIN_SCALE) {
      setTx(d.tx + dx);
      setTy(d.ty + dy);
    }
  };
  const onMouseUp = () => {
    drag.current = null;
  };

  return createPortal(
    <div
      data-testid="media-lightbox"
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseUp}
      onWheel={(e) => applyScale(scale - e.deltaY * 0.002)}
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
      onTouchCancel={onTouchEnd}
      onClick={() => {
        // Клик по фону (не по картинке и не после перетаскивания) закрывает.
        if (!moved.current) onClose();
      }}
      className="fixed inset-0 z-[100] flex items-center justify-center overflow-hidden bg-black/95"
      style={{ touchAction: "none" }}
    >
      <button
        type="button"
        aria-label="Закрыть просмотр"
        data-testid="media-lightbox-close"
        onClick={(e) => {
          e.stopPropagation();
          onClose();
        }}
        className="absolute right-3 top-3 z-10 grid h-10 w-10 place-items-center rounded-full bg-white/15 text-lg text-white active:scale-95"
      >
        ✕
      </button>

      {scale > MIN_SCALE && (
        <button
          type="button"
          aria-label="Сбросить масштаб"
          onClick={(e) => {
            e.stopPropagation();
            reset();
          }}
          className="absolute left-3 top-3 z-10 rounded-full bg-white/15 px-3 py-1.5 text-xs font-medium text-white active:scale-95"
        >
          {scale.toFixed(1)}× · сбросить
        </button>
      )}

      {failed ? (
        <div className="px-6 text-center text-sm text-white/80">
          Картинка не открылась — превью недоступно.
        </div>
      ) : (
        <img
          src={src}
          alt={alt}
          data-testid="media-lightbox-image"
          draggable={false}
          onLoad={() => setLoaded(true)}
          onError={() => setFailed(true)}
          onClick={(e) => e.stopPropagation()}
          onMouseDown={onMouseDown}
          style={{
            transform: `translate(${tx}px, ${ty}px) scale(${scale})`,
            transition: drag.current || pinch.current ? "none" : "transform 120ms ease-out",
          }}
          className={[
            "max-h-full max-w-full select-none object-contain",
            loaded ? "opacity-100" : "opacity-0",
          ].join(" ")}
        />
      )}

      <div className="pointer-events-none absolute inset-x-0 bottom-4 text-center text-[11px] text-white/60">
        Двойной тап или колесо — зум · тяни, чтобы сдвинуть · тап по фону — закрыть
      </div>
    </div>,
    document.body,
  );
}
