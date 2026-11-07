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
| `alt-text` | ⚠️ | аватары `alt=""` (декоративные, имя рядом) — верно; фото в лайтбоксе проверить | O |
| `aria-labels` | ⚠️ | у `Icon` всегда `aria-hidden`; не все иконочные кнопки имеют имя | N |
| `icon-context` | ⚠️ | декоративные скрыты; у Controls нет единого правила «иконка = имя» | N |
| `keyboard-nav` | ⚠️ | фокус виден; порядок табов не проверен на живом экране | N |
| `form-labels` | ⚠️ | вход — `label htmlFor`; в кабинете часть полей только с placeholder | P |
| `skip-links` | ❌ | ссылки «к содержимому» нет | N |
| `heading-hierarchy` | ⚠️ | этап N: профиль получил `h1`; в кабинете заголовок пока `div` — остаётся в N | N |
| `color-not-only` | ✅ | статусы = цвет + текст/иконка | — |
| `dynamic-type` | ⚠️ | масштаб текста не проверялся на 200 % | S |
| `reduced-motion` | ✅ | `motion-reduce` + `@media (prefers-reduced-motion)`; `press.guard` | — |
| `voiceover-sr` | ⚠️ | `role=status`/`aria-live` у тостов; у форм — только `role=alert` | P |
| `escape-routes` | ✅ | этап N: Escape, кнопка «Закрыть» 44×44, `aria-modal`; тест `BottomSheet.test.tsx` | — |
| `keyboard-shortcuts` | — | авторских горячих клавиш нет | — |
| `focus-not-obscured` | ⚠️ | липкие шапки есть (`HrFeedScreen`), фокус под ними не проверялся | N |
| `focus-not-obscured-enhanced` | ⚠️ | то же, AAA-уровень | N |
| `focus-appearance` | ⚠️ | площадь кольца и контраст 3:1 не измерены | S |
| `dragging-alternative` | ⚠️ | календарь: drag есть, кнопочные альтернативы частично | N |
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
| `loading-buttons` | ⚠️ | `disabled` есть, но не у всех async-кнопок | P |
| `error-feedback` | ⚠️ | ошибка в блоке формы, не у конкретного поля | P |
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
| `image-optimization` | ⚠️ | аватары без `loading="lazy"`: `MeetingsScreen:199`, `HoursView:87`, `ParticipantRow:157`, `PollsScreen:148` | O |
| `image-dimension` | ⚠️ | у части `<img>` нет `width/height` или `aspect-ratio` | O |
| `font-loading` | ✅ | системные шрифты, веб-шрифтов нет | — |
| `font-preload` | — | грузить нечего | — |
| `critical-css` | ⚠️ | Vite собирает один CSS-файл; критический CSS не инлайнится | — |
| `lazy-loading` | ✅ | экраны через `lazy()` в `App.tsx` | — |
| `bundle-splitting` | ✅ | кабинет и экраны — отдельные чанки | — |
| `third-party-scripts` | ✅ | сторонних скриптов нет | — |
| `reduce-reflows` | ⚠️ | отдельно не аудировалось | — |
| `content-jumping` | ✅ | скелеты той же формы (`loading.guard.test.ts`) | — |
| `lazy-load-below-fold` | ⚠️ | см. `image-optimization` | O |
| `virtualize-lists` | ⚠️ | лента и журнал без виртуализации; на 50+ записей — риск | R |
| `main-thread-budget` | ⚠️ | не измерялось | — |
| `progressive-loading` | ✅ | `Skeleton`, а не «Загрузка…» | — |
| `input-latency` | ⚠️ | поиск в кабинете без debounce | R |
| `tap-feedback-speed` | ✅ | CSS-переход 120мс | — |
| `debounce-throttle` | ⚠️ | поиск фильтрует на каждый ввод | R |
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
| `state-clarity` | ⚠️ | hover почти не используется (тач), disabled есть | P |
| `elevation-consistent` | ⚠️ | `shadow-sm/xl` в разных слоях без шкалы | P |
| `dark-mode-pairing` | ✅ | отдельная тема, токены `tg-*` | — |
| `icon-style-consistent` | ✅ | `iconSet.test.tsx`: одна библиотека, 24×24, stroke 1.8 | — |
| `system-controls` | ⚠️ | нативные `select`/`input`; кастомные шторки | — |
| `blur-purpose` | ✅ | blur только у полос навигации как фон | — |
| `primary-action` | ⚠️ | на части экранов несколько залитых кнопок | R |

## 5. Layout & Responsive (HIGH, 17 правил)

| Правило | Статус | Где / чем подтверждено | Этап |
|---|---|---|---|
| `viewport-meta` | ✅ | `initial-scale=1`, зум разрешён (этап L) | — |
| `mobile-first` | ✅ | колонка 560px, нижняя полоса | — |
| `breakpoint-consistency` | ⚠️ | `sm`/`lg` точечно, без шкалы 375/768/1024 | — |
| `readable-font-size` | ⚠️ | поля 16px; основной текст 14px (`text-sm`) | S |
| `line-length-control` | ✅ | `max-w-[560px]` | — |
| `horizontal-scroll` | ✅ | скролл только в таблицах/календаре, осознанно | — |
| `spacing-scale` | ⚠️ | 4/8 в основном; есть `px-0.5`, `gap-0.5` | M |
| `touch-density` | ⚠️ | плотные списки: кнопки 32–36px | M |
| `container-width` | ✅ | одна ширина контента | — |
| `z-index-management` | ❌ | `z-[100]`, `z-40`, `z-50`, `z-10` без шкалы (`MediaLightbox`, `BottomSheet`) | Q |
| `fixed-element-offset` | ✅ | полоса вкладок + safe-area; `Suspense`-скелет | — |
| `scroll-behavior` | ⚠️ | вложенные скроллы в шторках | Q |
| `viewport-units` | ✅ | `h-full`/`dvh`-эквивалент, без `100vh` | — |
| `orientation-support` | ⚠️ | ландшафт не проверялся | S |
| `content-priority` | ✅ | главное сверху, каталог ниже | — |
| `visual-hierarchy` | ✅ | размер/вес/отступ, не только цвет | — |
| `compact-label-overflow` | ⚠️ | `truncate` без доступа к полному тексту | S |
| `chip-collection-reflow` | ⚠️ | фильтры с `overflow-x-auto`, а не переносом | R |

## 6. Typography & Color (MEDIUM, 17 правил)

| Правило | Статус | Где / чем подтверждено | Этап |
|---|---|---|---|
| `line-height` | ⚠️ | `leading-tight` в плотных строках | S |
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
| `truncation-strategy` | ❌ | `truncate` без `title`/раскрытия (имена, подписи) | S |
| `letter-spacing` | ⚠️ | `tracking-wide` у мелких капсов — приемлемо | — |
| `number-tabular` | ✅ | `tabular-nums` в цифрах, счёте, времени | — |
| `whitespace-balance` | ✅ | карточки с 12–16px | — |
| `heading-line-balance` | ⚠️ | `text-wrap: balance` не задан | S |
| `long-token-wrapping` | ❌ | длинные адреса/имена: `break-words` только в `ErrorState` | S |

## 7. Animation (MEDIUM, 25 правил)

| Правило | Статус | Где / чем подтверждено | Этап |
|---|---|---|---|
| `duration-timing` | ⚠️ | 120мс press, 150мс fade, spring у шторки — без токенов | T |
| `transform-performance` | ✅ | transform/opacity | — |
| `loading-states` | ✅ | скелет >1с, спиннер в кнопках | — |
| `excessive-motion` | ⚠️ | одновременно подсветка вкладки и переход | T |
| `easing` | ✅ | ease-out, spring | — |
| `motion-meaning` | ✅ | переход = смена вкладки, шторка = снизу | — |
| `state-transition` | ✅ | `transition-colors` | — |
| `continuity` | ✅ | `TabTransition` | — |
| `parallax-subtle` | — | параллакса нет | — |
| `spring-physics` | ✅ | framer-motion spring | — |
| `exit-faster-than-enter` | ⚠️ | длительности равны | T |
| `stagger-sequence` | ⚠️ | списки появляются целиком | — |
| `shared-element-transition` | ⚠️ | нет общих элементов между экранами | — |
| `interruptible` | ⚠️ | шторка не отменяется новым тапом до завершения | T |
| `no-blocking-animation` | ✅ | ввод не блокируется | — |
| `fade-crossfade` | ✅ | fade при смене вкладки | — |
| `scale-feedback` | ✅ | CSS press 0.98 | — |
| `gesture-feedback` | ⚠️ | drag календаря — не проверялся | — |
| `hierarchy-motion` | ⚠️ | вход снизу у шторки; у экранов — fade | — |
| `motion-consistency` | ⚠️ | три разных длительности без общего токена | T |
| `opacity-threshold` | ⚠️ | скелеты 30–70 % — не контент | — |
| `modal-motion` | ✅ | шторка снизу + фон | — |
| `navigation-direction` | ⚠️ | вкладки без направления | — |
| `layout-shift-avoid` | ✅ | transform | — |
| `cancellable-state-transitions` | ⚠️ | быстрые переключения вкладок не проверялись | T |

## 8. Forms & Feedback (MEDIUM, 32 правила)

| Правило | Статус | Где / чем подтверждено | Этап |
|---|---|---|---|
| `input-labels` | ⚠️ | вход — да; кабинет — часть полей только placeholder | P |
| `error-placement` | ✅ | этап P: `auth-error`/`reset-error`, `aria-invalid` и `aria-describedby` на полях входа и смены пароля | — |
| `submit-feedback` | ⚠️ | `disabled` + спиннер не у всех форм | P |
| `ime-composition-enter` | ✅ | этап P: поле подразделения не отправляется на Enter во время IME-подтверждения | — |
| `required-indicators` | ⚠️ | обязательность описана словами, без `required`/метки | P |
| `empty-states` | ✅ | пустые состояния с действием | — |
| `toast-dismiss` | ✅ | 3,2с, закрытие 44×44 | — |
| `confirmation-dialogs` | ⚠️ | удаления через `window.confirm` (нативно, но не оформлено) | P |
| `input-helper-text` | ⚠️ | подсказки есть, постоянных — мало | P |
| `disabled-states` | ✅ | `disabled:opacity-*` + атрибут | — |
| `progressive-disclosure` | ✅ | простой/расширенный режим кабинета | — |
| `inline-validation` | ⚠️ | проверка на blur только в части полей | P |
| `input-type-keyboard` | ✅ | `inputMode` email/numeric/url | — |
| `password-toggle` | ✅ | этап L, тест `AuthScreen.test.tsx` | — |
| `autofill-support` | ✅ | `autoComplete` на входе и профиле | — |
| `undo-support` | ❌ | удаления необратимы (тост «Отменить» отсутствует) | P |
| `success-feedback` | ✅ | тост (`ToastHost`) | — |
| `error-recovery` | ✅ | `ErrorState` + «Повторить» | — |
| `multi-step-progress` | ✅ | онбординг с шагами | — |
| `form-autosave` | ❌ | длинные формы (чек-лист, стандарты) не сохраняют черновик | P |
| `sheet-dismiss-confirm` | ✅ | этап P: `BottomSheet dirty` спрашивает перед закрытием; подключено в проблемах и передаче смены | — |
| `error-clarity` | ✅ | `humanizeApiError` + следующий шаг | — |
| `field-grouping` | ⚠️ | группы визуальные, без `fieldset/legend` | P |
| `read-only-distinction` | ⚠️ | read-only и disabled не всегда различимы | P |
| `focus-management` | ✅ | этап P: отказ отправляет фокус в почту, пароль или повтор — в зависимости от причины | — |
| `error-summary` | ❌ | сводки ошибок нет | P |
| `touch-friendly-input` | ✅ | поля 44px+ | — |
| `destructive-emphasis` | ✅ | красный + отдельное место | — |
| `toast-accessibility` | ✅ | `aria-live="polite"`, фокус не крадёт | — |
| `aria-live-errors` | ⚠️ | `role=alert` есть не у всех ошибок | P |
| `contrast-feedback` | ✅ | этап S: `destructive` на фоне и вторичной подложке ≥ 4.5:1 в обеих темах | — |
| `timeout-feedback` | ⚠️ | таймаут показывается как общая ошибка | P |

## 9. Navigation Patterns (HIGH, 27 правил)

| Правило | Статус | Где / чем подтверждено | Этап |
|---|---|---|---|
| `bottom-nav-limit` | ✅ | 5 вкладок | — |
| `drawer-usage` | ✅ | сайдбар на ПК — навигация, не действия | — |
| `back-behavior` | ✅ | `useBackClose` + кнопка «Назад» в экранах | — |
| `deep-linking` | ⚠️ | deep link ведёт на вкладку, но не на запись | Q |
| `tab-bar-ios` | — | веб/PWA, не нативное приложение | — |
| `top-app-bar-android` | — | то же | — |
| `nav-label-icon` | ✅ | иконка + подпись в полосах | — |
| `nav-state-active` | ✅ | этап N: `aria-current="page"` в `TabBar` и `ManageTabBar`; `nav` получил имя | — |
| `nav-hierarchy` | ✅ | зона / кабинет / разделы | — |
| `modal-escape` | ✅ | этап N: Escape + кнопка закрытия + `aria-modal` (тест) | — |
| `search-accessible` | ✅ | поиск в кабинете и лентах сверху | — |
| `breadcrumb-web` | — | глубина ≤ 2 | — |
| `state-preservation` | ⚠️ | фильтры ленты живут в состоянии компонента | Q |
| `gesture-nav-support` | ✅ | Telegram BackButton | — |
| `tab-badge` | ✅ | счётчик задач, очищается при открытии | — |
| `overflow-menu` | ⚠️ | длинные ряды кнопок сжимаются, а не уходят в «ещё» | Q |
| `bottom-nav-top-level` | ✅ | только верхние экраны | — |
| `adaptive-navigation` | ✅ | сайдбар ≥ lg, полоса на телефоне | — |
| `back-stack-integrity` | ⚠️ | переходы между зонами сбрасывают историю | — |
| `navigation-consistency` | ✅ | полосы на одном месте | — |
| `avoid-mixed-patterns` | ✅ | одна полоса на зону | — |
| `modal-vs-navigation` | ✅ | шторки только для действий | — |
| `focus-on-route-change` | ❌ | после смены вкладки фокус остаётся на кнопке | N |
| `persistent-nav` | ✅ | полоса/сайдбар всегда доступны | — |
| `destructive-nav-separation` | ✅ | «Выйти» отдельно от навигации | — |
| `empty-nav-state` | ⚠️ | выключенный раздел просто исчезает | — |

## 10. Charts & Data (LOW, 27 правил)

| Правило | Статус | Где / чем подтверждено | Этап |
|---|---|---|---|
| `chart-type` | — | графиков нет: KPI и таблицы | — |
| `color-guidance` | ⚠️ | статусы цвет + текст, но без проверки палитры на дальтонизм | R |
| `data-table` | ✅ | таблицы с текстовыми значениями | — |
| `pattern-texture` | ⚠️ | только цвет ячейки смены | R |
| `legend-visible` | — | нет графиков | — |
| `tooltip-on-interact` | — | нет графиков | — |
| `axis-labels` | — | нет осей | — |
| `responsive-chart` | — | нет графиков | — |
| `empty-data-state` | ✅ | пустые состояния с подсказкой | — |
| `loading-chart` | ✅ | скелеты | — |
| `animation-optional` | ✅ | reduced-motion | — |
| `large-dataset` | ⚠️ | отчёты без агрегации; период не ограничен | R |
| `number-formatting` | ⚠️ | даты/числа форматируются точечно | R |
| `touch-target-chart` | — | нет интерактивных графиков | — |
| `no-pie-overuse` | — | нет круговых диаграмм | — |
| `contrast-data` | ⚠️ | цвет ячеек смены не измерен | R |
| `legend-interactive` | — | нет легенд | — |
| `direct-labeling` | — | нет графиков | — |
| `tooltip-keyboard` | — | нет тултипов с данными | — |
| `sortable-table` | ⚠️ | таблицы не сортируются, `aria-sort` нет | R |
| `axis-readability` | — | нет осей | — |
| `data-density` | ✅ | один показатель на карточку | — |
| `trend-emphasis` | — | трендов нет | — |
| `gridline-subtle` | — | сеток нет | — |
| `focusable-elements` | — | нет интерактивных точек | — |
| `screen-reader-summary` | ⚠️ | KPI читаются как числа с подписями, без сводки | R |
| `error-state-chart` | — | нет графиков | — |
| `export-option` | — | выгрузка не входит в продукт | — |
| `drill-down-consistency` | — | нет drill-down | — |
| `time-scale-clarity` | — | нет временных графиков | — |

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

## Журнал

| Дата | Этап | Что | Проверка |
|---|---|---|---|
| 07.11.2026 | список | Матрица правил скилла: 120 правил, 10 категорий, статусы и этапы M–T | поисковый скрипт скилла отсутствует — использованы статические справочники |
| 07.11.2026 | M | Тач-цели 44px в 14 файлах, `touch-action`, курсор, хит-зона иконки дня рождения 24×24 | `tsc` 0; целевые 6 файлов/25 тестов; полный фронт 888 тестов/114 файлов; сборка 0 |
| 07.11.2026 | N | `aria-current` и имя полосы, Escape/крестик/`aria-modal` в шторке, `h1` профиля, ключ `nav.main` в RU/EN/UZ | `tsc` 0; `BottomSheet.test.tsx` 4 теста; полный фронт 888 тестов; сборка 0 |
| 07.11.2026 | S (контраст) | Ссылки и ошибки внесены в расчёт WCAG; светлая ссылка 4.17→5.23:1, ошибка 4.23→5.62:1, тёмная ошибка 4.07→5.85:1 | `theme.contrast.test.ts` 12 тестов; `tsc` 0 |
| 07.11.2026 | P | Ошибка у поля и фокус на первом проблемном, подтверждение закрытия шторки с вводом, IME-Enter | `tsc` 0; `AuthScreen`/`BottomSheet` 11 тестов; полный фронт 896 тестов |
