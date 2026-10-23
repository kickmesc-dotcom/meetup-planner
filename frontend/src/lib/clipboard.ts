/**
 * Копирование в буфер обмена с запасным путём.
 *
 * В Telegram-webview `navigator.clipboard` доступен не всегда (нет secure
 * context или политика клиента), а ссылку-приглашение управляющий почти всегда
 * копирует именно оттуда. Поэтому: сначала современный API, потом скрытая
 * textarea с `execCommand("copy")` — он работает и в старых webview.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // переходим к запасному пути
  }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}
