/**
 * ESLint 9, flat config (этап 1 плана `docs/AAA_ROADMAP.md`).
 *
 * Зачем. `npm run lint` существовал, но конфига не было: команда падала на
 * отсутствующем файле, и линт не входил в CI. Здесь — минимальный набор
 * правил, который ловит реальные ошибки, а не спорит о стиле: типы уже
 * проверяет `tsc` (strict), поэтому `no-undef` выключен — он не знает про
 * DOM-глобалы и даёт ложные срабатывания в TS.
 *
 * Почему правила выбраны так:
 *  • `no-unused-vars` — единственное, что `tsc` не покрывает в тестах и
 *    обработчиках; подчёркивание в начале имени — осознанное исключение;
 *  • `rules-of-hooks` — ошибка рантайма, которую нельзя допускать;
 *  • `exhaustive-deps` — предупреждение, а не ошибка: в проекте есть
 *    осознанные зависимости, и `--max-warnings 0` не должен запрещать код,
 *    который работает;
 *  • `no-explicit-any` выключен: в проекте два места с `any` на границе API,
 *    и запрет ничего не улучшит.
 */
import js from "@eslint/js";
import tseslint from "@typescript-eslint/eslint-plugin";
import tsParser from "@typescript-eslint/parser";
import reactHooks from "eslint-plugin-react-hooks";

export default [
  { ignores: ["dist", "node_modules", "coverage", "public/sw.js"] },
  js.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      parser: tsParser,
      ecmaVersion: 2022,
      sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: {
      "@typescript-eslint": tseslint,
      "react-hooks": reactHooks,
    },
    rules: {
      ...tseslint.configs.recommended.rules,
      "no-undef": "off",
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/no-empty-object-type": "off",
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
    },
  },
  {
    // Скрипты сборки — обычный Node: `process` и `console` здесь не ошибка.
    files: ["scripts/**/*.{js,mjs}"],
    rules: { "no-undef": "off" },
  },
  {
    // `_legacy` — старый плеер, который не переписываем: правила зависимостей
    // там шумят на осознанных решениях (ref вместо state). `rules-of-hooks`
    // остаётся включённым — это уже баг, а не стиль.
    files: ["src/_legacy/**/*.{ts,tsx}"],
    rules: { "react-hooks/exhaustive-deps": "off" },
  },
];
