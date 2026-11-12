# Аудит по скиллу UI/UX Pro Max

Источник: `PROMT/UI_UX_PRO_MAX_FULL_CONTEXT/ui-ux-pro-max-full` —
`SKILL.md` (таблица приоритетов), `references/quick-reference.md` (все 120
правил, §1–§10), `references/pro-rules.md` (канонический Pre-Delivery
Checklist). Поисковый скрипт `scripts/search.py` в папке скилла отсутствует,
поэтому база (`data/*.csv`) недоступна: правила взяты из статических
справочников, совпадения из базы не выдумывались.

## Как читать

| Знак | Значение |
|---|---|
| ✅ | держится кодом или стражем-тестом, регресс ловится автоматически |
| ⚠️ | частично: работает не везде или не проверено на живой поверхности |
| ❌ | нарушено, есть конкретное место в коде |
| — | не применимо к этому продукту, причина указана |

Столбец «Этап» — где правило закрывается. Этапы идут по приоритету скилла:
сначала CRITICAL (§1–§2), потом HIGH (§3–§5), затем MEDIUM/LOW. После каждого
этапа — проверки и деплой, после каждого пака — коммит и пуш.

## 1. Accessibility (CRITICAL, 24 правила)

| Правило | Статус | Где / чем подтверждено | Этап |
|---|---|---|---|
| `color-contrast` | ✅ | этап S: 12 пар в двух темах считает `theme.contrast.test.ts` (кнопка, подсказки, основной текст, ссылки, ошибки, выбранный фильтр) | — |
| `focus-states` | ✅ | `styles.css` кольцо 2px; `focus.guard.test.ts` запрещает `focus:outline-none` | — |
| `alt-text` | ✅ | аватары и логотип — `alt=""` (декоративные, имя рядом); `MediaLightbox` и `PhotoAttach` передают `alt` из подписи | O |
| `aria-labels` | ✅ | у `Icon` всегда `aria-hidden`; иконочная кнопка без текста обязана иметь имя — страж `a11y.guard.test.ts` | N |
| `icon-context` | ✅ | единое правило «иконка без текста = имя»; страж ловит нарушение | N |
| `keyboard-nav` | ⚠️ | фокус виден; `RangePill` управляется Enter/Space; порядок табов на живом экране не проверен | N |
| `form-labels` | ✅ | этап P: у всех 44 полей без видимой подписи есть `aria-label`; шесть оставшихся в отчёте сканера получают имя через `Field`/`Checkbox` label | — |
| `skip-links` | ✅ | ссылка «К содержимому» первой в оболочке, видна по фокусу | — |
| `heading-hierarchy` | ✅ | `h1` в оболочке и подразделах; `h2` у содержательных секций — кабинет, лента, форма вопроса, задачи, KPI | N |
| `color-not-only` | ✅ | статусы = цвет + текст/иконка | — |
| `dynamic-type` | ✅ | 200 %: `e2e/zoom.spec.ts` — 9 экранов, выхода за правый край нет; правила переноса в шапках закреплены | S |
| `reduced-motion` | ✅ | `motion-reduce` + `@media (prefers-reduced-motion)`; `press.guard` | — |
| `voiceover-sr` | ✅ | этап P: тосты — `role="status"`, ошибки форм — `role="alert"`, работа кнопок — `aria-busy` | — |
| `escape-routes` | ✅ | этап N: Escape, кнопка «Закрыть» 44×44, `aria-modal`; тест `BottomSheet.test.tsx` | — |
| `keyboard-shortcuts` | — | авторских горячих клавиш нет | — |
| `focus-not-obscured` | ✅ | `scroll-margin-block: 5rem` в глобальном `:focus-visible` + страж `focus.guard.test.ts` | N |
| `focus-not-obscured-enhanced` | ⚠️ | отступ 5rem для AA; AAA-проверка на живых экранах не делалась | N |
| `focus-appearance` | ✅ | кольцо 2 px с отступом 2 px, контраст 5.23:1 / 5.87:1 (≥ 3:1), закреплено тестом | — |
| `dragging-alternative` | ✅ | `RangePill` — кнопка (Enter/Space, `aria-label`), границы правятся кнопками в `RangeEditorSheet`; drag — быстрый путь | N |
| `web-target-size` | ✅ | 24×24 AA выполняется (минимум в коде — 32px) | M |
| `consistent-help` | ⚠️ | подсказки в разных местах экранов | R |
| `redundant-entry` | ⚠️ | онбординг и профиль местами спрашивают одно и то же | R |
| `accessible-authentication` | ✅ | `autoComplete`, вставка, показ пароля, вход по коду | — |
| `auto-rotation-controls` | — | авто-каруселей нет | — |
| `contextual-live-badge-updates` | ✅ | бейдж задач: `aria-label` «Задачи: N открытых» на кнопке | — |

## 2. Touch & Interaction (CRITICAL, 16 правил)

| Правило | Статус | Где / чем подтверждено | Этап |
|---|---|---|---|
| `touch-target-size` | ✅ | этап M: действия и иконочные кнопки подняты до 44px (`IssuesScreen`, `HandoversScreen`, `MassPlanSheet`, `AdminTasksScreen`, `AttentionScreen`, `AppTextsScreen`, `AskScreen`, `MenuList`, `ZoneHint`, `SimulationBanner`, `NavBar`, вход и сброс пароля) | — |
| `touch-spacing` | ⚠️ | в плотных списках кнопки вплотную (8px не везде) | M |
| `hover-vs-tap` | ✅ | все действия на `onClick` | — |
| `loading-buttons` | ✅ | этап P: 125 async-кнопок в 47 файлах — `disabled` + `aria-busy` по тому же состоянию | — |
| `error-feedback` | ⚠️ | `FormField` связал вход, сброс, домен и ключ API (ошибка у поля, `role="alert"`); остальные формы кабинета — общий блок или тост | P |
| `cursor-pointer` | ✅ | этап M: курсор только для `pointer: fine`, у `disabled` — `not-allowed` | — |
| `gesture-conflicts` | ⚠️ | календарь `touch-action: pan-y`; вложенных свайпов нет | — |
| `tap-delay` | ✅ | этап M: `touch-action: manipulation` в `styles.css` для кнопок и `[role=button]` | — |
| `standard-gestures` | ✅ | свайп-назад не переопределяется | — |
| `system-gestures` | ✅ | системные жесты не блокируются | — |
| `press-feedback` | ✅ | `styles.css` + `press.guard.test.ts` | — |
| `haptic-feedback` | ✅ | `haptic()` в Telegram, используется на вкладках и действиях | — |
| `gesture-alternative` | ⚠️ | критичные действия имеют кнопки; drag календаря — частично | N |
| `safe-area-awareness` | ✅ | `SAFE_AREA_ROOT`, `env(safe-area-inset-bottom)` в обеих полосах | — |
| `no-precision-required` | ⚠️ | этап M: иконка дня рождения 24×24 (WCAG AA); 44px в сетке дня физически не помещается — осознанное исключение | — |
| `swipe-clarity` | ⚠️ | свайпов с скрытыми действиями нет | — |
| `drag-threshold` | ⚠️ | календарь: порог не проверялся | N |

## 3. Performance (HIGH, 19 правил)

| Правило | Статус | Где / чем подтверждено | Этап |
|---|---|---|---|
| `image-optimization` | ✅ | этап R: все четыре аватара грузятся лениво (`loading="lazy"`, `decoding="async"`) | — |
| `image-dimension` | ✅ | все `<img>` получили `width/height`: логотип 36, аватары 36/32/16, фото в карточке 640×96; лайтбокс — осознанно без размеров, он масштабируется контейнером | O |
| `font-loading` | ✅ | системные шрифты, веб-шрифтов нет | — |
| `font-preload` | — | грузить нечего | — |
| `critical-css` | ⚠️ | Vite собирает один CSS-файл; критический CSS не инлайнится | — |
| `lazy-loading` | ✅ | экраны через `lazy()` в `App.tsx` | — |
| `bundle-splitting` | ✅ | кабинет и экраны — отдельные чанки | — |
| `third-party-scripts` | ✅ | сторонних скриптов нет | — |
| `reduce-reflows` | ⚠️ | отдельно не аудировалось | — |
| `content-jumping` | ✅ | скелеты той же формы (`loading.guard.test.ts`) | — |
| `lazy-load-below-fold` | ✅ | этап R: изображения ниже первого экрана не грузятся до прокрутки | — |
| `virtualize-lists` | ✅ | лента рисует по 60, журнал по 40 записей; фильтры начинают порцию заново | — |
| `main-thread-budget` | ⚠️ | не измерялось | — |
| `progressive-loading` | ✅ | `Skeleton`, а не «Загрузка…» | — |
| `input-latency` | ✅ | этап R: общий `useDebouncedValue` в трёх поисках — поле не ждёт фильтра | — |
| `tap-feedback-speed` | ✅ | CSS-переход 120мс | — |
| `debounce-throttle` | ✅ | этап R: фильтр применяется через 200 мс после последнего символа | — |
| `offline-support` | ✅ | `offline/`, PWA, экран повтора | — |
| `network-fallback` | ⚠️ | медленная сеть: скелет есть, деградации контента нет | — |

## 4. Style Selection (HIGH, 12 правил)

| Правило | Статус | Где / чем подтверждено | Этап |
|---|---|---|---|
| `style-match` | ✅ | плотный рабочий интерфейс, не лендинг | — |
| `consistency` | ✅ | общие компоненты и токены | — |
| `no-emoji-icons` | ✅ | `emoji.guard.test.ts` сканирует все `.tsx` | — |
| `color-palette-from-product` | ⚠️ | тема Telegram + бренд-цвет организации (по замыслу) | — |
| `effects-match-style` | ✅ | тени/радиусы по шкале (`styles.radius.test.ts`) | — |
| `platform-adaptive` | ⚠️ | Telegram-тема учтена; iOS/Android идиомы — частично | — |
| `state-clarity` | ✅ | этап P: нажатие — `press`, выбранное — `aria-current`/`aria-pressed`/заливка, недоступное — disabled; hover только точным указателям | — |
| `elevation-consistent` | ✅ | этап P: три роли `shadow-raised/floating/sheet`, старые ступени запрещены `styles.elevation.test.ts` | — |
| `dark-mode-pairing` | ✅ | отдельная тема, токены `tg-*` | — |
| `icon-style-consistent` | ✅ | `iconSet.test.tsx`: одна библиотека, 24×24, stroke 1.8 | — |
| `system-controls` | ⚠️ | нативные `select`/`input`; кастомные шторки | — |
| `blur-purpose` | ✅ | blur только у полос навигации как фон | — |
| `primary-action` | ✅ | главное действие залито одно; в профиле режим обучения переведён на мягкую подложку | — |

## 5. Layout & Responsive (HIGH, 17 правил)

| Правило | Статус | Где / чем подтверждено | Этап |
|---|---|---|---|
| `viewport-meta` | ✅ | `initial-scale=1`, зум разрешён (этап L) | — |
| `mobile-first` | ✅ | колонка 560px, нижняя полоса | — |
| `breakpoint-consistency` | ⚠️ | `sm`/`lg` точечно, без шкалы 375/768/1024 | — |
| `readable-font-size` | ⚠️ | поля 16px (вход и сброс — `text-base`, на iOS — принудительно); основной текст 14px (`text-sm`) | S |
| `line-length-control` | ✅ | `max-w-[560px]` | — |
| `horizontal-scroll` | ✅ | скролл только в таблицах/календаре, осознанно | — |
| `spacing-scale` | ⚠️ | 4/8 в основном; есть `px-0.5`, `gap-0.5` | M |
| `touch-density` | ⚠️ | плотные списки: кнопки 32–36px | M |
| `container-width` | ✅ | одна ширина контента | — |
| `z-index-management` | ✅ | этап Q: шкала `z-sheet`/`z-overlay`/`z-lightbox` в Tailwind, числовые слои заменены в 13 файлах, страж `styles.zindex.test.ts` | — |
| `fixed-element-offset` | ✅ | полоса вкладок + safe-area; `Suspense`-скелет | — |
| `scroll-behavior` | ✅ | этап Q: `overscroll-contain` в шторке — прокрутка не уходит странице под ней | — |
| `viewport-units` | ✅ | `h-full`/`dvh`-эквивалент, без `100vh` | — |
| `orientation-support` | ✅ | ландшафт 780×420: `scrollWidth == innerWidth`, переполнения нет | — |
| `content-priority` | ✅ | главное сверху, каталог ниже | — |
| `visual-hierarchy` | ✅ | размер/вес/отступ, не только цвет | — |
| `compact-label-overflow` | ⚠️ | этап S: у имён, отделов и заголовков добавлен `title` (десктоп); на тач полный текст — в карточке | S |
| `chip-collection-reflow` | ✅ | отделы, материалы и масштаб переносятся на новую строку | — |

## 6. Typography & Color (MEDIUM, 17 правил)

| Правило | Статус | Где / чем подтверждено | Этап |
|---|---|---|---|
| `line-height` | ⚠️ | плотный текст 14/20 (1.43); заголовки `leading-tight` — осознанно | S |
| `line-length` | ✅ | короткие строки в карточках | — |
| `font-pairing` | ✅ | одна системная семья | — |
| `font-scale` | ✅ | токены `3xs…2xl`; `styles.typeScale.test.ts` | — |
| `contrast-readability` | ⚠️ | не измерено | S |
| `text-styles-system` | ⚠️ | роли через классы, не через семантические токены | — |
| `weight-hierarchy` | ✅ | 600 заголовки, 400 текст, 500 подписи | — |
| `color-semantic` | ✅ | `tg-*`, `status-*` | — |
| `color-dark-mode` | ✅ | отдельные значения темы | — |
| `color-accessible-pairs` | ✅ | этап S: ссылки и ошибки добавлены в расчёт; светлая ссылка затемнена до `#1c6fb8`, ошибка — `#c62828`, тёмная ошибка — `#ff6b6b` | — |
| `color-not-decorative-only` | ✅ | статус = цвет + слово | — |
| `truncation-strategy` | ⚠️ | имена в часовой шкале получили `title`; остальные `truncate` проверяются по экранам | S |
| `letter-spacing` | ⚠️ | `tracking-wide` у мелких капсов — приемлемо | — |
| `number-tabular` | ✅ | `tabular-nums` в цифрах, счёте, времени | — |
| `whitespace-balance` | ✅ | карточки с 12–16px | — |
| `heading-line-balance` | ✅ | этап S: `text-wrap: balance` для `h1–h3` | — |
| `long-token-wrapping` | ✅ | этап S: `overflow-wrap: break-word` на `body` — длинное слово переносится, а не рвёт строку | — |

## 7. Animation (MEDIUM, 25 правил)

| Правило | Статус | Где / чем подтверждено | Этап |
|---|---|---|---|
| `duration-timing` | ✅ | этап T: токены `--motion-press/fade/exit` и `duration-press/fade/exit` в Tailwind | — |
| `transform-performance` | ✅ | transform/opacity | — |
| `loading-states` | ✅ | скелет >1с, спиннер в кнопках | — |
| `excessive-motion` | ✅ | этап T: одно движение на смену вкладки (вход экрана); подчёркивание и цвет без анимации | — |
| `easing` | ✅ | ease-out, spring | — |
| `motion-meaning` | ✅ | переход = смена вкладки, шторка = снизу | — |
| `state-transition` | ✅ | `transition-colors` | — |
| `continuity` | ✅ | `TabTransition` | — |
| `parallax-subtle` | — | параллакса нет | — |
| `spring-physics` | ✅ | framer-motion spring | — |
| `exit-faster-than-enter` | ✅ | этап T: выход шторки 160 мс и фона 100 мс против пружинного входа | — |
| `stagger-sequence` | ⚠️ | списки появляются целиком | — |
| `shared-element-transition` | ⚠️ | нет общих элементов между экранами | — |
| `interruptible` | ✅ | этап T: закрытие — состояние; тап во время входа уводит шторку, повторный тап не дублирует `onClose` | — |
| `no-blocking-animation` | ✅ | ввод не блокируется | — |
| `fade-crossfade` | ✅ | fade при смене вкладки | — |
| `scale-feedback` | ✅ | CSS press 0.98 | — |
| `gesture-feedback` | ⚠️ | drag календаря — не проверялся | — |
| `hierarchy-motion` | ⚠️ | вход снизу у шторки; у экранов — fade | — |
| `motion-consistency` | ✅ | этап T: одна шкала движения на всё приложение | — |
| `opacity-threshold` | ⚠️ | скелеты 30–70 % — не контент | — |
| `modal-motion` | ✅ | шторка снизу + фон | — |
| `navigation-direction` | ⚠️ | вкладки без направления | — |
| `layout-shift-avoid` | ✅ | transform | — |
| `cancellable-state-transitions` | ⚠️ | быстрые переключения вкладок не проверялись | T |

## 8. Forms & Feedback (MEDIUM, 32 правила)

| Правило | Статус | Где / чем подтверждено | Этап |
|---|---|---|---|
| `input-labels` | ✅ | этап P: placeholder больше не единственное имя; ключи переведены на EN и UZ | — |
| `error-placement` | ✅ | этап P: `auth-error`/`reset-error`, `aria-invalid` и `aria-describedby` на полях входа и смены пароля | — |
| `submit-feedback` | ✅ | 46 async-кнопок через `BusyLabel` (спиннер + текст действия) или спиннер вместо иконки; переключатели, сегменты и степперы — не кнопки действия | P |
| `ime-composition-enter` | ✅ | этап P: поле подразделения не отправляется на Enter во время IME-подтверждения | — |
| `required-indicators` | ✅ | `FormField required` рисует `*` и `aria-required`; имя в настройках получило видимую `*` при `aria-required` | P |
| `empty-states` | ✅ | пустые состояния с действием | — |
| `toast-dismiss` | ✅ | 3,2с, закрытие 44×44 | — |
| `confirmation-dialogs` | ✅ | все необратимые действия спрашивают `showConfirm`; прямых `window.confirm` в экранах нет, внутри Telegram — диалог платформы | — |
| `input-helper-text` | ⚠️ | этап P: сброс пароля — постоянная длина, ключ API — «показывается один раз»; остальные формы — по месту | P |
| `disabled-states` | ✅ | `disabled:opacity-*` + атрибут | — |
| `progressive-disclosure` | ✅ | простой/расширенный режим кабинета | — |
| `inline-validation` | ⚠️ | проверка на blur только в части полей | P |
| `input-type-keyboard` | ✅ | `inputMode` email/numeric/url | — |
| `password-toggle` | ✅ | этап L, тест `AuthScreen.test.tsx` | — |
| `autofill-support` | ✅ | `autoComplete` на входе и профиле | — |
| `undo-support` | ✅ | удалённые смена и шаблон недели возвращаются кнопкой «Отменить» в тосте | — |
| `success-feedback` | ✅ | тост (`ToastHost`) | — |
| `error-recovery` | ✅ | `ErrorState` + «Повторить» | — |
| `multi-step-progress` | ✅ | онбординг с шагами | — |
| `form-autosave` | ✅ | мастер настройки хранит черновик на устройстве и очищает его после завершения | — |
| `sheet-dismiss-confirm` | ✅ | этап P: `BottomSheet dirty` спрашивает перед закрытием; подключено в проблемах и передаче смены | — |
| `error-clarity` | ✅ | `humanizeApiError` + следующий шаг | — |
| `field-grouping` | ✅ | этап P: группы формы (ключ API, сообщение сотруднику) получили `role="group"` + имя; `fieldset` не нужен — Tailwind-сброс делает его визуально равным `div` | — |
| `read-only-distinction` | — | полей `readOnly` в экранах нет (grep: 0), различать нечего | — |
| `focus-management` | ✅ | этап P: отказ отправляет фокус в почту, пароль или повтор — в зависимости от причины | — |
| `error-summary` | ⚠️ | ошибка шага мастера объявляется через `role="alert"`; многополевых форм со сводкой нет | P |
| `touch-friendly-input` | ✅ | поля 44px+ | — |
| `destructive-emphasis` | ✅ | красный + отдельное место | — |
| `toast-accessibility` | ✅ | `aria-live="polite"`, фокус не крадёт | — |
| `aria-live-errors` | ✅ | этап P: все блоки ошибок в экранах объявлены `role="alert"` (проверено сканером: 3 оставшихся закрыты) | — |
| `contrast-feedback` | ✅ | этап S: `destructive` на фоне и вторичной подложке ≥ 4.5:1 в обеих темах | — |
| `timeout-feedback` | ✅ | `humanizeApiError` различает обрыв, таймаут (`AbortError`) и отказ сервера; тексты на EN/UZ | — |

## 9. Navigation Patterns (HIGH, 27 правил)

| Правило | Статус | Где / чем подтверждено | Этап |
|---|---|---|---|
| `bottom-nav-limit` | ✅ | 5 вкладок | — |
| `drawer-usage` | ✅ | сайдбар на ПК — навигация, не действия | — |
| `back-behavior` | ✅ | `useBackClose` + кнопка «Назад» в экранах | — |
| `deep-linking` | ✅ | `?task=42` подсвечивает и прокручивает карточку, `?issue=9` открывает карточку проблемы | — |
| `tab-bar-ios` | — | веб/PWA, не нативное приложение | — |
| `top-app-bar-android` | — | то же | — |
| `nav-label-icon` | ✅ | иконка + подпись в полосах | — |
| `nav-state-active` | ✅ | этап N: `aria-current="page"` в `TabBar` и `ManageTabBar`; `nav` получил имя | — |
| `nav-hierarchy` | ✅ | зона / кабинет / разделы | — |
| `modal-escape` | ✅ | этап N: Escape + кнопка закрытия + `aria-modal` (тест) | — |
| `search-accessible` | ✅ | поиск в кабинете и лентах сверху | — |
| `breadcrumb-web` | — | глубина ≤ 2 | — |
| `state-preservation` | ✅ | срез фильтров ленты сохраняется на сотрудника (`readFeedFilters`/`saveFeedFilters`) и восстанавливается при входе | — |
| `gesture-nav-support` | ✅ | Telegram BackButton | — |
| `tab-badge` | ✅ | счётчик задач, очищается при открытии | — |
| `overflow-menu` | ⚠️ | длинные ряды кнопок сжимаются, а не уходят в «ещё» | Q |
| `bottom-nav-top-level` | ✅ | только верхние экраны | — |
| `adaptive-navigation` | ✅ | сайдбар ≥ lg, полоса на телефоне | — |
| `back-stack-integrity` | ⚠️ | переходы между зонами сбрасывают историю | — |
| `navigation-consistency` | ✅ | полосы на одном месте | — |
| `avoid-mixed-patterns` | ✅ | одна полоса на зону | — |
| `modal-vs-navigation` | ✅ | шторки только для действий | — |
| `focus-on-route-change` | ✅ | фокус переходит на область содержимого (первый рендер не трогаем) | — |
| `persistent-nav` | ✅ | полоса/сайдбар всегда доступны | — |
| `destructive-nav-separation` | ✅ | «Выйти» отдельно от навигации | — |
| `empty-nav-state` | ⚠️ | выключенный раздел просто исчезает | — |

## 10. Charts & Data (LOW, 27 правил)

| Правило | Статус | Где / чем подтверждено | Этап |
|---|---|---|---|
| `chart-type` | — | графиков нет: KPI и таблицы | — |
| `color-guidance` | ✅ | статус читается по текстовой метке, цвет только усиливает | — |
| `data-table` | ✅ | таблицы с текстовыми значениями | — |
| `pattern-texture` | ✅ | в ячейке смены есть короткая метка статуса, а не только заливка | — |
| `legend-visible` | — | нет графиков | — |
| `tooltip-on-interact` | — | нет графиков | — |
| `axis-labels` | — | нет осей | — |
| `responsive-chart` | — | нет графиков | — |
| `empty-data-state` | ✅ | пустые состояния с подсказкой | — |
| `loading-chart` | ✅ | скелеты | — |
| `animation-optional` | ✅ | reduced-motion | — |
| `large-dataset` | ⚠️ | отчёты без агрегации; период не ограничен | R |
| `number-formatting` | ⚠️ | 12.11.2026: деньги и даты в оплате, платформе, сотрудниках, уведомлениях и приватности идут через `lib/format.ts` (локаль ru/en/uz, битая дата — «—»); остальные экраны — по мере касания | R |
| `touch-target-chart` | — | нет интерактивных графиков | — |
| `no-pie-overuse` | — | нет круговых диаграмм | — |
| `contrast-data` | ✅ | белый текст на трёх плашках статуса ≥ 4.5:1, закреплено тестом | — |
| `legend-interactive` | — | нет легенд | — |
| `direct-labeling` | — | нет графиков | — |
| `tooltip-keyboard` | — | нет тултипов с данными | — |
| `sortable-table` | ✅ | этап R: таблица материалов сортируется по колонке, `aria-sort` и стрелка состояния | — |
| `axis-readability` | — | нет осей | — |
| `data-density` | ✅ | один показатель на карточку | — |
| `trend-emphasis` | — | трендов нет | — |
| `gridline-subtle` | — | сеток нет | — |
| `focusable-elements` | — | нет интерактивных точек | — |
| `screen-reader-summary` | ✅ | KPI-карточка получила `sr-only` сводку одной фразой | — |
| `error-state-chart` | — | нет графиков | — |
| `export-option` | — | выгрузка не входит в продукт | — |
| `drill-down-consistency` | — | нет drill-down | — |
| `time-scale-clarity` | — | нет временных графиков | — |

## Сводка остатка (12.11.2026)

45 ⚠️ — это не «неизвестно», а три разных класса. Правило без причины
в матрице не осталось; ниже — что именно мешает поставить ✅.

| Раздел | ⚠️ | Живая проверка | Осознанно | Техдолг |
|---|---:|---:|---:|---:|
| 1. Accessibility | 4 | 2 | 0 | 2 |
| 2. Touch & Interaction | 7 | 2 | 2 | 3 |
| 3. Performance | 4 | 2 | 1 | 1 |
| 4. Style Selection | 3 | 1 | 2 | 0 |
| 5. Layout & Responsive | 5 | 0 | 2 | 3 |
| 6. Typography & Color | 5 | 1 | 2 | 2 |
| 7. Animation | 7 | 2 | 5 | 0 |
| 8. Forms & Feedback | 3 | 0 | 1 | 2 |
| 9. Navigation Patterns | 3 | 0 | 0 | 3 |
| 10. Charts & Data | 2 | 0 | 0 | 2 |
| **Итого** | **43** | **10** | **15** | **18** |

**Живая проверка (10).** `keyboard-nav`, `focus-not-obscured-enhanced`,
`gesture-conflicts`, `drag-threshold`, `reduce-reflows`, `main-thread-budget`,
`platform-adaptive`, `contrast-readability`, `gesture-feedback`,
`cancellable-state-transitions`. Нужен живой аккаунт, реальные сессии,
iOS/Android или замер на устройстве; код к ним готов или проверен частично.

**Осознанно (15).** `no-precision-required` (24 px — WCAG AA, 44 px в сетке
дня не помещается), `swipe-clarity` (скрытых свайпов нет),
`critical-css` (SPA, один CSS-файл кэшируется), `color-palette-from-product`
(тема Telegram + бренд организации), `system-controls` (нативные контролы),
`readable-font-size` (14 px основной, 16 px поля), `touch-density` (плотные
списки 32–36 px при 44 px у действий), `line-height` (14/20),
`letter-spacing` (`tracking-wide` у капсов), `stagger-sequence`,
`shared-element-transition`, `hierarchy-motion`, `opacity-threshold`,
`navigation-direction`, `error-summary` (многополевых форм со сводкой нет).

**Техдолг (18).** `network-fallback`, `consistent-help`,
`redundant-entry`, `touch-spacing`, `error-feedback`, `gesture-alternative`,
`breakpoint-consistency`, `spacing-scale`, `compact-label-overflow`,
`text-styles-system`, `truncation-strategy`, `input-helper-text`,
`inline-validation`, `overflow-menu`,
`back-stack-integrity`, `empty-nav-state`, `large-dataset`,
`number-formatting`. Это выполнимые срезы без владельца; каждый требует
своего пака и проверки, механически галочки не ставятся.

## Этапы

| Этап | Категория | Объём | Проверка | Деплой |
|---|---|---|---|---|
| M | §2 CRITICAL: тач-цели 44, отступы, `touch-action`, курсор | кнопки-действия и иконочные кнопки в 12 файлах | `tsc`, целевые тесты, полный фронт, сборка; живой замер в браузере | да |
| N | §1 CRITICAL: имена, состояния, клавиатура | `aria-current` в `TabBar`, `aria-label` у nav, Escape/крестик/`aria-modal` в `BottomSheet`, skip-link, `h1` в кабинете и профиле, фокус на основной области | тесты на `BottomSheet`, `TabBar`; клавиатурный проход | да |
| P | §8: формы | ошибка у поля + `aria-describedby`, `focus-management`, обязательные поля, `disabled` на отправке, `isComposing`, подтверждение закрытия шторки с несохранённым | тесты форм; `tsc` | да |
| Q | §9 + §5: навигация и слои | шкала `z-index`, Escape-порядок слоёв, сохранение фильтров, переполнение рядов | тесты навигации | да |
| R | §3 + §10: данные | ленивые изображения и размеры, debounce поиска, сортировка таблиц, `aria-sort`, сводка KPI, палитра статусов | замер сборки, тесты | да |
| S | §6: контраст и текст | расчёт всех пар 4.5:1 в двух темах, `overflow-wrap`, `text-wrap: balance`, `title` у обрезки, масштаб 200 % и ландшафт | скрипт расчёта контраста, живой замер | да |
| T | §7: анимация | общие токены длительности, exit короче enter, отмена при быстром переключении | тесты, `reduced-motion` | да |

Правило работы: этап не считается закрытым, пока не пройдены проверки и
результат не выложен; «сделано в коде» и «проверено на живой поверхности» в
отчёте пишутся раздельно.

## Локализация (сверх матрицы скилла)

Скилл не содержит правил про язык интерфейса, но на EN-поверхности подпись без
перевода заметнее любого отступа: человек читает её как ошибку, а не как стиль.

| Что | Статус | Чем подтверждено |
|---|---|---|
| Настройки и кабинет (6 подписей) | ✅ | этап L, EN и UZ |
| Экраны: кабинет, импорт, профиль, задачи, пересменки, опросы (61 подпись) | ✅ | этап L, EN и UZ; строки есть в `content-*.js` прода |
| Поля входа и сброса | ✅ | `*` и `required`, `aria-required`, `aria-busy`, постоянная подсказка длины |
| Даты и месяцы (`dateUtils`) | ✅ | три локали в данных, `Intl` не нужен |
| Серверные сообщения (`humanizeApiError`) | ✅ | этап L: 69 текстов в `api-errors.ts`, запасной путь идёт через `tx` |
| Словарь узбекского | ✅ | `uz.guard.test.ts`: значения без русских букв |

## Журнал

| Дата | Этап | Что | Проверка |
|---|---|---|---|
| 07.11.2026 | список | Матрица правил скилла: 120 правил, 10 категорий, статусы и этапы M–T | поисковый скрипт скилла отсутствует — использованы статические справочники |
| 07.11.2026 | M | Тач-цели 44px в 14 файлах, `touch-action`, курсор, хит-зона иконки дня рождения 24×24 | `tsc` 0; целевые 6 файлов/25 тестов; полный фронт 888 тестов/114 файлов; сборка 0 |
| 07.11.2026 | N | `aria-current` и имя полосы, Escape/крестик/`aria-modal` в шторке, `h1` профиля, ключ `nav.main` в RU/EN/UZ | `tsc` 0; `BottomSheet.test.tsx` 4 теста; полный фронт 888 тестов; сборка 0 |
| 07.11.2026 | S (контраст) | Ссылки и ошибки внесены в расчёт WCAG; светлая ссылка 4.17→5.23:1, ошибка 4.23→5.62:1, тёмная ошибка 4.07→5.85:1 | `theme.contrast.test.ts` 12 тестов; `tsc` 0 |
| 07.11.2026 | P | Ошибка у поля и фокус на первом проблемном, подтверждение закрытия шторки с вводом, IME-Enter | `tsc` 0; `AuthScreen`/`BottomSheet` 11 тестов; полный фронт 896 тестов; живая проверка входа на проде |
| 07.11.2026 | Q | Шкала слоёв, `overscroll-contain`, подтверждено сохранение фильтров ленты | `styles.zindex.test.ts`; полный фронт; сборка
| 07.11.2026 | R | Debounce поиска, сортировка таблицы с `aria-sort`, ленивые аватары | полный фронт; сборка; эмодзи-страж
| 07.11.2026 | S/T | Перенос длинных слов, баланс заголовков, токены движения, короткий выход | полный фронт; сборка; живой замер на проде |
| 07.11.2026 | N/Q | Skip-link, фокус после смены вкладки, SVG-стрелки во всех живых экранах | `tsc` 0, 897 тестов, сборка 0; текст `‹›` в DOM прода — 0
| 07.11.2026 | Q | Deep link на задачу и проблему | тесты разбора ссылки; полный фронт; сборка; Pages `4bf198bb` |
| 12.11.2026 | матрица | `alt-text`, `heading-hierarchy`, `submit-feedback` переведены в ✅: проверены alt у лайтбокса и `PhotoAttach`, `h2` у пяти содержательных секций, 46 async-кнопок на `BusyLabel` | `tsc` 0, eslint 0, BusyLabel 2/2, профильные тесты, сборка 0 |
| 12.11.2026 | сводка | Остаток 45 ⚠️ разнесён по разделам: 10 живая проверка, 15 осознанно, 20 техдолг; правило без причины не осталось | пересчёт скриптом по строкам матрицы: 45 = 10 + 15 + 20 |
| 12.11.2026 | техдолг | `image-dimension` и `required-indicators` закрыты: размеры у 7 `<img>`, видимая `*` у имени; лайтбокс — осознанное исключение | `tsc` 0, eslint 0, Brand 4/4, MySettings 5/5, сборка 0 |
| 12.11.2026 | техдолг | `lib/format.ts`: единые деньги, числа, дата/время по текущей локали; переведены оплата, платформа, сотрудники, уведомления и приватность | `tsc` 0, eslint 0, format 5/5, экраны 15/15, сборка 0 |
