/**
 * Узбекские тексты экранов (план, 8.3). Ключ — русский оригинал, как и у EN_CONTENT.
 *
 * Почему отдельный файл, а не строка в `content.ts`. Это не «третий словарь
 * рядом с первыми двумя»: узбекский — пакет, который включается и выключается
 * организацией, и, скорее всего, будет расти отдельно от английского. Один
 * файл на язык позволяет добавлять язык, не трогая общий словарь и не рискуя
 * задеть переводы других.
 *
 * Что здесь переведено: рабочий путь сотрудника целиком — «Чек-лист» (открытие
 * зала и закрытие смены, фотоотчёт, заметка) и «Мои задачи» (список, приёмка,
 * проблемы, сроки). Это то, что человек видит в каждой смене.
 *
 * Что остаётся русским и почему это осознанно: остальные экраны. Русский здесь
 * не «дыра», а запасной вариант — `tx` возвращает оригинал, если перевода нет.
 * Русский в команде понимает каждый, поэтому непереведённая строка читается, а
 * не превращается в ключ вида `tasks.title`. Английский словарь устроен так же
 * и заполнялся точно по такому же принципу — экран за экраном.
 *
 * Формат: `"Русский оригинал": "Oʻzbekcha matn"`, подстановки `{name}` — те же,
 * что в русском. Проверка — `src/i18n/uz.guard.test.ts`.
 */
export const UZ_CONTENT: Record<string, string> = {
  // --------------------------------------------------- «Чек-лист» --------
  // Экран смены: зал, пункты, фотоотчёт, закрытие.
  "Чек-лист смены": "Smena chek-listi",
  "Сегодня работаешь:": "Bugun ishlaysiz:",
  "сменить": "almashtirish",
  "Чек-лист": "Chek-list",
  "Смена закрыта. Спасибо за работу!": "Smena yopildi. Ish uchun rahmat!",
  "Смена открыта. Хорошей смены!": "Smena ochildi. Yaxshi smena tilaymiz!",
  "В каком зале работаешь?": "Qaysi zalda ishlaysiz?",
  "У каждого зала свой чек-лист открытия. Выбор запомнится на сегодня — сменить можно в любой момент.":
    "Har bir zalning ochilish chek-listi bor. Tanlov bugun uchun eslab qolinadi — istalgan paytda almashtirish mumkin.",
  "Залы не заведены. Попроси руководителя добавить их в разделе «Чек-листы».":
    "Zallar kiritilmagan. Rahbardan ularni «Chek-listlar» boʻlimida qoʻshishni soʻrang.",
  "выбран": "tanlangan",
  "выбрать": "tanlash",
  "закрытия смены": "smenani yopish",
  "открытия зала": "zalni ochish",
  "первого дня": "birinchi kun",
  "Попроси руководителя назначить шаблон {variant}.":
    "Rahbardan {variant} shablonini tayinlashni soʻrang.",
  "Не сегодня — {label}": "Bugun emas — {label}",
  "по расписанию": "jadval boʻyicha",
  "Пункт закрывается фотоотчётом": "Band foto-hisobot bilan yopiladi",
  "Отметить пункт": "Bandni belgilash",
  "(опц.)": "(majburiy emas)",
  "не сегодня · {label}": "bugun emas · {label}",
  "фотоотчёт приложен": "foto-hisobot qoʻshildi",
  "нужен фотоотчёт: снимок с камеры или из галереи":
    "foto-hisobot kerak: kameradan yoki galereyadan surat",
  "Снять отчёт": "Hisobotni olish",
  "закрыто в {time}": "{time} da yopildi",
  "Отмена": "Bekor qilish",
  "Заметка": "Izoh",
  "Например: инвентарь в порядке, не хватило 2 упаковок":
    "Masalan: inventar joyida, 2 dona qadoq yetmadi",
  "Сохранить заметку": "Izohni saqlash",

  // ------------------------------------------------ «Мои задачи» --------
  // Список поручений, приёмка, проблемы, «не успеваю».
  "Привет, {name}": "Salom, {name}",
  "Мои задачи": "Mening vazifalarim",
  "Спросить: поиск по инструкциям": "Soʻrash: yoʻriqnomalardan qidirish",
  "База стандартов": "Standartlar bazasi",
  "Приёмка работ": "Ishlarni qabul qilish",
  "Передача смены": "Smenani topshirish",
  "Что нужно сделать сегодня": "Bugun nima qilish kerak",
  "задач {count}": "vazifa {count}",
  "просрочено {count}": "muddati oʻtgan {count}",
  "Активные": "Faol",
  "Все": "Hammasi",
  "Проблемы": "Muammolar",
  "Смена сегодня": "Bugungi smena",
  "Смена закрыта": "Smena yopildi",
  "Открыть чек-лист": "Chek-listni ochish",
  "открыто {count}": "ochiq {count}",
  "{count} ждут внимания: срок или повтор.": "{count} eʼtibor kutmoqda: muddat yoki takror.",
  "Все в работе — открой журнал, если нужен статус.":
    "Hammasi ishda — holat kerak boʻlsa jurnalni oching.",
  "Посмотреть чек-лист": "Chek-listni koʻrish",
  "Продолжить чек-лист": "Chek-listni davom ettirish",
  "Начать смену": "Smenani boshlash",
  "смена {date}": "smena {date}",
  "приоритет: {label}": "muhimlik: {label}",
  "фото есть": "foto bor",
  "нужен фотоотчёт": "foto-hisobot kerak",
  "с приёмкой": "qabul bilan",
  "просрочено": "muddati oʻtgan",
  "сделали {done} из {total}": "{total} dan {done} bajarildi",
  "Моя часть:": "Mening qismim:",
  "Результат:": "Natija:",
  "Работа сдана — ждёт приёмки руководителя.":
    "Ish topshirildi — rahbar qabul qilishini kutmoqda.",
  "Принять": "Qabul qilish",
  "Взять в работу": "Ishga olish",
  "Начать": "Boshlash",
  "Сдать на проверку": "Tekshiruvga topshirish",
  "Выполнено": "Bajarildi",
  "Не успеваю": "Ulgurolmayman",
  "Фотоотчёт: сними или выбери фото — поручение закроется само.":
    "Foto-hisobot: suratga oling yoki tanlang — topshiriq oʻzi yopiladi.",
  "Добавить фото": "Foto qoʻshish",
  "Руководителю отправлено объяснение. Срок отсчитывается заново.":
    "Rahbarga izoh yuborildi. Muddat qaytadan hisoblanadi.",
  "Причина": "Sabab",
  "Когда сможешь закончить (необязательно)": "Qachon tugata olasiz (majburiy emas)",
  "Комментарий": "Izoh",
  "Что именно мешает?": "Aynan nima xalaqit bermoqda?",
  "Отправить руководителю": "Rahbarga yuborish",

  // ------------------------------------------ админка: «Языки» ---------
  // Экран открывает владелец, но текст на языке того, кто смотрит.
  "Языки": "Tillar",
  "Языковой пакет для команды: включён по умолчанию":
    "Jamoa uchun oʻzbek tili paketi: standart holatda yoniq",
  "Языковой пакет команды": "Jamoa til paketi",
  "Узбекский язык": "Oʻzbek tili",
  "Выключен": "Oʻchirilgan",
  "Как работает перевод": "Tarjima qanday ishlaydi",

  // -------------------------------------- общие единицы и статусы ------
  // «7 kun», «4 soat» — то, что показывается в проблемах и сроках.
  "день": "kun",
  "дня": "kun",
  "дней": "kun",
  "ч": "soat",
  "меньше часа": "bir soatdan kam",

  // ------ «Спасибо коллеге» (план, 8.4): карточка недели и лист ------ 
  "Спасибо на этой неделе":
    "Bu haftadagi rahmatlar",
  "Ты на {place} месте":
    "Siz {place}-oʻrindasiz",
  "Получено":
    "Olingan",
  "Сказал(а)":
    "Aytilgan",
  "Осталось сегодня":
    "Bugun qoldi",
  "{count} спасибо":
    "{count} rahmat",
  "Пока некого благодарить — коллег в твоём подразделении нет.":
    "Hozircha rahmat aytadigan odam yoʻq — boʻlimingizda hamkasblar yoʻq.",
  "Сказать спасибо":
    "Rahmat aytish",
  "Кому сказать спасибо":
    "Kimga rahmat aytish",
  "Поиск по имени":
    "Ism boʻyicha qidirish",
  "Никого не нашли":
    "Hech kim topilmadi",
  "Что сделал(а) — необязательно":
    "Nima qildi — majburiy emas",
  "Спасибо за смену":
    "Smena uchun rahmat",
  "Не удалось сказать спасибо.":
    "Rahmat aytib boʻlmadi.",
  "Благодарности сейчас не загрузились — остальное в ленте работает.":
    "Rahmatlar yuklanmadi — lentaning qolgani ishlayapti.",
  "Себе спасибо не говорят — выбери коллегу.":
    "Oʻzingizga rahmat aytilmaydi — hamkasbni tanlang.",
  "Этому человеку сказать спасибо нельзя: он не в твоей команде.":
    "Bu odamga rahmat aytib boʻlmaydi: u sizning jamoangizda emas.",
  "Сегодня ты уже благодарил(а) этого человека — завтра можно снова.":
    "Bugun bu odamga allaqachon rahmat aytdingiz — ertaga yana mumkin.",
  "На сегодня лимит благодарностей исчерпан. Вернись к этому завтра.":
    "Bugun uchun rahmatlar chegarasi tugadi. Ertaga qaytib keling.",
  "Слишком длинная запись — хватит одной фразы.":
    "Yozuv juda uzun — bir jumla yetarli.",
  "Поблагодарил(а) коллегу":
    "Hamkasbga rahmat aytdi",

  "Не удалось сказать спасибо. Попробуй ещё раз.":
    "Rahmat aytib boʻlmadi. Yana urinib koʻring.",
};
