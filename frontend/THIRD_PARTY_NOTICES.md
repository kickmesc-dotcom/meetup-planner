# Сторонние компоненты и лицензии

В проекте используются материалы сторонних авторов. Уведомления обязательны по
условиям лицензий и сохраняются здесь — не удаляйте этот файл при чистке
репозитория.

## Иконки интерфейса — Iconoir

- Пакет: `iconoir-react` 7.12.1 (официальный React-пакет библиотеки)
- Источник: https://iconoir.com · https://github.com/iconoir-icons/iconoir
- Лицензия: **MIT** (разрешает коммерческое использование, изменение и
  распространение при сохранении уведомления)
- Что используется: контурные (regular) иконки, оригинальные SVG из пакета —
  без перерисовки и без иконок из других наборов
- Где: `src/components/Icon.tsx` — единственная точка подключения набора

```
MIT License

Copyright (c) 2021 Daniel Martin

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Что сознательно не используется

- **Apple SF Symbols** — лицензия Apple ограничивает применение платформой
  Apple; в веб-версии продукта они не используются вовсе.
- Наборы без явной лицензии, «иконки из интернета» и SVG неизвестного
  происхождения — не добавлять даже для одного экрана.
- Смешивание наборов (Iconoir + Phosphor + Tabler в одном интерфейсе) — не
  допускается: у них разная сетка и оптическая толщина, и список начинает
  «дрожать» по высоте строки.
