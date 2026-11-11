/**
 * Lighthouse CI (этап 4, `docs/AAA_ROADMAP.md`).
 *
 * Зачем. Бюджет бандла меряет байты, но не то, что видит человек: 126 КБ
 * главного чанка можно потратить на синхронный код и всё равно ждать LCP
 * четыре секунды. Lighthouse смотрит на реальный браузер, поэтому падение
 * LCP видно в том же коммите, что и его причина.
 *
 * Почему `staticDistDir`, а не боевой адрес. Так проверка не зависит от
 * доступности Amvera и от того, отвечает ли API, — измеряется только фронт.
 * Прогон идёт с мобильным профилем Lighthouse (simulated Slow 4G + 4×CPU):
 * это и есть «4G-профиль» из DoD, а не быстрый десктоп.
 *
 * Почему один URL. Роутера по путям в приложении нет — экраны переключаются
 * состоянием, поэтому «лента» и «кабинет» не открываются ссылкой. Они за
 * авторизацией с аккаунтом владельца, которого у CI нет; их покрывают e2e
 * (`e2e/a11y.spec.ts`) и RUM из этапа 5. Здесь измеряется входной экран —
 * то, что видит каждый без исключения.
 *
 * `is-on-https`/`uses-http2` отключены осознанно: локальный статический сервер
 * LHCI отдаёт по http, и эти аудиты мерили бы стенд, а не продукт. TLS
 * проверяется на Pages.
 */
module.exports = {
  ci: {
    collect: {
      staticDistDir: "./dist",
      url: ["http://localhost/index.html"],
      numberOfRuns: 3,
    },
    assert: {
      assertions: {
        "largest-contentful-paint": ["error", { maxNumericValue: 2500 }],
        "cumulative-layout-shift": ["error", { maxNumericValue: 0.1 }],
        "total-blocking-time": ["error", { maxNumericValue: 300 }],
        "first-contentful-paint": ["error", { maxNumericValue: 2000 }],
        "categories:performance": ["error", { minScore: 0.85 }],
        "categories:accessibility": ["error", { minScore: 0.95 }],
        // Стенд, а не продукт: см. комментарий выше.
        "is-on-https": "off",
        "uses-http2": "off",
        "service-worker": "off",
        "csp-xss": "off",
        // Кеш-заголовки задаёт Pages, а не `vite preview`/статический сервер.
        "uses-long-cache-ttl": "off",
      },
    },
    upload: { target: "filesystem", outputDir: ".lighthouseci" },
  },
};
