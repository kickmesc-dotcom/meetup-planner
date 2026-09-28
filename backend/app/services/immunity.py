"""GHG10 Э9: общие типы иммунитетов к лоху/чухану.

Иммунитет — это «этого участника выбирать нельзя». Причин ровно три:

- ``birthday`` — сегодня день рождения (GHG8 P3, `services/birthday_immunity.py`);
- ``loser_immunity`` — пожизненный иммунитет к лоху со 9 ранга (GHG10 Э9);
- ``chukhan_immunity`` — пожизненный иммунитет к чухану с 10 ранга (GHG10 Э9).

Механика оглашения у всех одна: в announce-режиме чат слышит «мог бы стать X,
но …», и бросок повторяется по пулу без этого участника; в silent-режиме
участник выкидывается из пула заранее. Поэтому причина описывается данными —
кодом (для логов) и шаблоном текста, — а не отдельной веткой логики на каждый
случай. Новый вид иммунитета = новая константа здесь + строка в
`services/game/immunity.py`.
"""
from __future__ import annotations

from dataclasses import dataclass

BIRTHDAY = "birthday"
LOSER_IMMUNITY = "loser_immunity"
CHUKHAN_IMMUNITY = "chukhan_immunity"


@dataclass(frozen=True)
class ImmuneReason:
    """Почему участник неприкосновенен + шаблон текста оглашения.

    `template` рендерится через `str.format(name=...)`. Других плейсхолдеров
    намеренно нет: ранг и уровень у каждого свои, поэтому их вшивает тот, кто
    собирает причину (`services/game/immunity.py`), а не общий форматтер.
    """

    code: str
    template: str

    def text(self, name: str) -> str:
        return self.template.format(name=name)


# Единственная причина, живущая с GHG8 (до игровой системы) — текст сохранён
# дословно, его уже видел чат.
BIRTHDAY_REASON = ImmuneReason(
    BIRTHDAY,
    "🎂 Мог бы стать <b>{name}</b>, но у него сегодня день "
    "рождения — иммунитет. Крутим заново…",
)


@dataclass(frozen=True)
class ImmuneSkip:
    """Оглашённый «черновой» кандидат: кто, почему и готовый текст в чат.

    `text` — свойство, а не поле: причина (а с ней и формулировка) может быть
    общей на несколько участников, дублировать строку в каждом скипе ни к чему.
    """

    user_id: int
    name: str
    reason: ImmuneReason

    @property
    def text(self) -> str:
        return self.reason.text(self.name)
