#!/usr/bin/env node
/**
 * Бюджет бандла (этап 1, `docs/AAA_ROADMAP.md`).
 *
 * Зачем. `PERF_AUDIT.md` уже ловил главный чанк в 939 КБ: вес растёт тихо,
 * потому что сборка остаётся зелёной при любом размере. Здесь потолок
 * зафиксирован по факту на 08.11.2026 с небольшим запасом: превышение валит
 * CI, и рост виден в том же коммите, а не через месяц на 3G.
 *
 * Почему без size-limit и других пакетов: проверка — это двадцать строк на
 * `node:fs` и `node:zlib`, а лишняя зависимость в CI стоит дороже.
 *
 * Что считается:
 *  • главный чанк `index-*.js` — raw и gzip (его грузит каждый визит);
 *  • все `.js` и `.css` в `dist/assets` — суммарный вес сборки.
 * Карты исходников в `dist` не попадают (`sourcemap: false`); если появятся —
 * это отдельная ошибка, а не повод считать бюджет.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const ASSETS = "dist/assets";

/** Потолки с запасом ~4 % к замеру 08.11.2026 (497 КБ raw / 1,5 МБ всего). */
const BUDGET = {
  mainRaw: 520 * 1024,
  mainGzip: 160 * 1024,
  totalRaw: 1600 * 1024,
};

const kb = (bytes) => `${(bytes / 1024).toFixed(1)} КБ`;

let files;
try {
  files = readdirSync(ASSETS);
} catch {
  console.error(`Нет ${ASSETS}: сначала выполните npm run build`);
  process.exit(2);
}

const maps = files.filter((file) => file.endsWith(".map"));
if (maps.length > 0) {
  console.error(`В сборке ${maps.length} карт исходников — их не должно быть в проде`);
  process.exit(1);
}

const bundle = files.filter(
  (file) => /\.(js|css)$/.test(file) && !file.endsWith(".map"),
);
const main = files.find((file) => /^index-.*\.js$/.test(file));

if (!main) {
  console.error("Главный чанк index-*.js не найден");
  process.exit(2);
}

const mainBytes = readFileSync(join(ASSETS, main));
const mainRaw = mainBytes.byteLength;
const mainGzip = gzipSync(mainBytes).byteLength;
const totalRaw = bundle.reduce(
  (sum, file) => sum + readFileSync(join(ASSETS, file)).byteLength,
  0,
);

const rows = [
  ["Главный чанк, raw", mainRaw, BUDGET.mainRaw],
  ["Главный чанк, gzip", mainGzip, BUDGET.mainGzip],
  ["Все js/css, raw", totalRaw, BUDGET.totalRaw],
];

let failed = false;
for (const [label, value, limit] of rows) {
  const over = value > limit;
  failed = failed || over;
  console.log(
    `${over ? "✗" : "✓"} ${label}: ${kb(value)} (потолок ${kb(limit)})`,
  );
}

if (failed) {
  console.error(
    "Бюджет превышен. Проверьте, что новый код не тянет лишние зависимости в главный чанк.",
  );
  process.exit(1);
}

console.log("Бюджет в норме");
