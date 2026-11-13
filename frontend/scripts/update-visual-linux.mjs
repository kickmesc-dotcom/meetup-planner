/**
 * Обновление Linux-эталонов пиксельной регрессии.
 *
 * Зачем скрипт, а не команда в документе. Эталон обязан сниматься в том же
 * образе, что и CI-джоба `visual`: шрифты и сглаживание другой ОС дают другой
 * растр при верной вёрстке. Здесь собраны все детали, которые легко забыть:
 * версия образа берётся из установленного `@playwright/test`, `node_modules`
 * монтируется отдельным томом (иначе `npm ci` внутри контейнера затрёт
 * Windows-зависимости на хосте), путь проекта переводится в docker-форму.
 *
 * Запуск: `npm run test:e2e:visual:update` из `frontend`.
 * Требуется запущенный Docker Desktop и скачанный образ; при отсутствии
 * образа скрипт сам его скачает.
 */
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

const cwd = process.cwd();
const pkg = JSON.parse(readFileSync(path.join(cwd, "package.json"), "utf8"));
const playwrightVersion =
  pkg.devDependencies?.["@playwright/test"]?.replace(/^[^\d]*/, "") ??
  pkg.dependencies?.["@playwright/test"]?.replace(/^[^\d]*/, "");

if (!playwrightVersion) {
  console.error("Не нашёл @playwright/test в package.json.");
  process.exit(1);
}

const image = `mcr.microsoft.com/playwright:v${playwrightVersion}-jammy`;
// Том отдельный от хоста: Linux-зависимости не должны попасть в Windows
// `node_modules`, а Windows-бинарники — в контейнер.
const volume = "semitask-pw-node-modules";
const projectDir = cwd.replace(/\\/g, "/");

function run(command, args, options = {}) {
  return spawnSync(command, args, { stdio: "inherit", ...options });
}

const dockerCheck = spawnSync("docker", ["info"], { stdio: "ignore" });
if (dockerCheck.status !== 0) {
  console.error(
    "Docker недоступен. Запусти Docker Desktop и повтори: эталон снимается в Linux-образе.",
  );
  process.exit(1);
}

const imageCheck = spawnSync("docker", ["image", "inspect", image], {
  stdio: "ignore",
});
if (imageCheck.status !== 0) {
  console.log(`Образ ${image} не найден, скачиваю…`);
  const pull = run("docker", ["pull", image]);
  if (pull.status !== 0) process.exit(pull.status ?? 1);
}

const script = [
  "npm ci --no-audit --no-fund",
  // Конфиг обязателен: основной `playwright.config.ts` исключает visual из
  // обычного прогона, и без `--config` Playwright не находит ни одного теста.
  "npx playwright test --config playwright.visual.config.ts --update-snapshots",
].join(" && ");

console.log(`Снимаю Linux-эталоны в ${image}…`);
const result = run("docker", [
  "run",
  "--rm",
  "-e",
  "CI=1",
  "-v",
  `${projectDir}:/work`,
  "-v",
  `${volume}:/work/node_modules`,
  "-w",
  "/work",
  image,
  "bash",
  "-lc",
  script,
]);

if (result.status === 0) {
  console.log(
    "Готово: e2e/visual.spec.ts-snapshots/*-linux.png обновлены. Проверь дифф перед коммитом.",
  );
}
process.exit(result.status ?? 1);
