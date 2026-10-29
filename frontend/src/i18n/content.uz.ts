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

  // Кнопка перевода данных (план, 11).
  "Перевести": "Tarjima qilish",
  "Показать оригинал": "Asl matnni koʻrsatish",
  "Перевод недоступен": "Tarjima bu yerda mavjud emas",

  // ------------------------------------------------- «Профиль» (план, 11.4) --
  // Скриншот 29.10: переключатель показывал UZ, а тело карточки было русским.
  // Переведено ровно то, что на этом экране видно.
  "Профиль готов. Смена начнётся с чек-листа.":
    "Profil tayyor. Smena chek-listdan boshlanadi.",
  "Сохранили — остался один шаг.": "Saqlandi — bitta qadam qoldi.",
  "Изменить мои данные": "Maʼlumotlarimni oʻzgartirish",
  "Изменить": "Oʻzgartirish",
  "Доступ": "Ruxsat",
  "Подразделение": "Boʻlim",
  "Опыт": "Tajriba",
  "новичок": "yangi",
  "с опытом": "tajribali",
  "выбери ниже": "quyidan tanlang",
  "не указан": "koʻrsatilmagan",
  "Профиль открыт": "Profil ochiq",
  "Профиль закрыт": "Profil yopiq",
  "Коллеги видят твою активность и цифры. Руководитель видит их всегда.":
    "Hamkasblar faolligingiz va raqamlaringizni koʻradi. Rahbar ularni doim koʻradi.",
  "Коллеги видят только имя и отдел. Руководитель и админ — всё.":
    "Hamkasblar faqat ism va boʻlimni koʻradi. Rahbar va admin — hammasini.",
  "Так решили": "Shunday belgilangan",
  "Открыт": "Ochiq",
  "Закрыт": "Yopiq",
  "Последний заход": "Oxirgi kirish",
  "Коллеги видят, когда ты последний раз открывал приложение.":
    "Hamkasblar ilovani oxirgi marta qachon ochganingizni koʻradi.",
  "Включено руководителем — выключить нельзя.":
    "Rahbar yoqqan — oʻchirib boʻlmaydi.",
  "Последнее медиа": "Oxirgi media",
  "Коллеги видят твоё последнее фото из отчёта.":
    "Hamkasblar hisobotdagi oxirgi suratingizni koʻradi.",
  "Настройка организации": "Tashkilot sozlamalari",
  "Разделы, подразделения и кто что видит":
    "Boʻlimlar, tuzilmalar va kim nima koʻradi",
  "Закончим знакомство": "Tanishuvni yakunlaymiz",
  "Мои данные": "Mening maʼlumotlarim",
  "Подразделение определяет чек-листы, поручения и ссылки, которые тебе приходят.":
    "Boʻlim sizga keladigan chek-listlar, topshiriqlar va havolalarni belgilaydi.",
  "Продолжить": "Davom etish",
  "Сохранить": "Saqlash",
  "Опыт и обучение": "Tajriba va oʻqish",
  "Курс": "Kurs",
  "Три уровня от знакомства до самостоятельной работы — по одному действию на урок.":
    "Tanishuvdan mustaqil ishgacha uch daraja — har darsda bitta amal.",
  "Учимся вместе · вкл": "Birga oʻrganamiz · yoniq",
  "Учимся вместе · выкл": "Birga oʻrganamiz · oʻchiq",
  "Открыть курс": "Kursni ochish",
  "Продолжить курс": "Kursni davom ettirish",
  "Все разделы": "Barcha boʻlimlar",
  "Для администратора": "Administrator uchun",
  "Примерить роль": "Rolni sinab koʻrish",
  "Роль меняет только твой обзор: задачи, ленту и кабинет. Доступ в админку остаётся — вернуть себя можно этой же кнопкой.":
    "Rol faqat koʻrinishingizni oʻzgartiradi: vazifalar, lenta va kabinet. Adminga kirish qoladi — shu tugma bilan qaytish mumkin.",
  "Режим проверки": "Tekshiruv rejimi",
  "Открой приложение глазами сотрудника. Тестовые задачи и смены удалятся при выходе — настоящие данные не изменятся.":
    "Ilovani xodim koʻzi bilan oching. Sinov vazifalari va smenalari chiqishda oʻchiriladi — haqiqiy maʼlumotlar oʻzgarmaydi.",
  "Кого проверяем": "Kimni tekshiramiz",
  "Выбери сотрудника": "Xodimni tanlang",
  "Открываем…": "Ochilmoqda…",
  "Открыть как сотрудник": "Xodim sifatida ochish",
  "Тестовый пул": "Sinov toʻplami",
  "Сотрудники `[BOT]` для проверки сценариев. Настоящие данные не затрагиваются.":
    "`[BOT]` xodimlari ssenariylarni tekshirish uchun. Haqiqiy maʼlumotlarga tegmaydi.",
  "Открыть тестовый пул": "Sinov toʻplamini ochish",
  "Вернуться в чат с ботом": "Bot chatiga qaytish",
  "Сервер": "Server",
  "Если основной адрес недоступен, укажи резервный — приложение продолжит работать без переустановки. Пусто — адрес из сборки.":
    "Asosiy manzil ishlamasa, zaxirasini koʻrsating — ilova qayta oʻrnatishsiz ishlashda davom etadi. Boʻsh — yigʻilgan manzil ishlatiladi.",
  "Сохранить и перезагрузить": "Saqlash va qayta yuklash",
  "Видно": "Koʻrinadi",
  "Скрыто": "Yashirin",

  // ------------------------------- «Сказал — стало поручением» (план, 8.5) --
  // Экран, который руководитель открывает в зале: строки короткие, разговорные.
  "Сказать, что нужно сделать — станет поручением":
    "Nima qilish kerakligini ayting — topshiriqqa aylanadi",
  "Скажи, что нужно сделать": "Nima qilish kerakligini ayting",
  "Например: Аня, протри витрину до 18:00":
    "Masalan: Anya, vitrinani soat 18:00 gacha artib chiqing",
  "Напиши или продиктуй одной фразой: что сделать, кому и к когда. Срок и исполнителя разберём сами.":
    "Bir jumla bilan yozing yoki ayting: nima qilish, kimga va qachonga. Muddat va ijrochini oʻzimiz aniqlaymiz.",
  "Что нужно сделать": "Nima qilish kerak",
  "Сказать голосом": "Ovoz bilan aytish",
  "Остановить запись": "Yozuvni toʻxtatish",
  "Голос распознаёт браузер — запись никуда не отправляется.":
    "Ovozni brauzer taniydi — yozuv hech qayerga yuborilmaydi.",
  "Не расслышал — попробуй ещё раз или напиши словами.":
    "Eshitmadim — yana urinib koʻring yoki yozib yuboring.",
  "Кому?": "Kimga?",
  "Всему отделу": "Butun boʻlimga",
  "Кто именно:": "Aynan kim:",
  "В команде пока никого нет.": "Jamoada hozircha hech kim yoʻq.",
  "Выбери исполнителя — без него поручение не создать.":
    "Ijrochini tanlang — usiz topshiriq yaratilmaydi.",
  "У тебя не указано подразделение — выбери человека, кому поручить.":
    "Sizda boʻlim koʻrsatilmagan — topshiriq beradigan odamni tanlang.",
  "Создать поручение": "Topshiriq yaratish",
  "Создаю…": "Yaratilmoqda…",
  "Поручение создано": "Topshiriq yaratildi",
  "Поручение отправлено отделу.": "Topshiriq boʻlimga yuborildi.",
  "Исполнитель: {name}": "Ijrochi: {name}",
  "Ещё одно": "Yana bitta",
  "Готово": "Tayyor",

  // Сроки и чипы разбора: те же слова, что человек говорит вслух.
  "Без срока": "Muddatsiz",
  "К концу смены": "Smena oxirigacha",
  "Через час": "Bir soatdan keyin",
  "Завтра": "Ertaga",
  "Точное время": "Aniq vaqt",
  "Срочно": "Shoshilinch",
  "Фото": "Foto",
  "Срок: конец смены": "Muddat: smena oxiri",
  "Срок взят из фразы": "Muddat jumladan olindi",
  "сегодня": "bugun",
  "завтра": "ertaga",

  // ------------------------------------------------------ «Команда» (11.4) --
  // Руководительская сторона смены: сводка, люди, часы и опасная зона очистки.
  "Команда": "Jamoa",
  "все подразделения": "barcha boʻlimlar",
  "моё подразделение": "mening boʻlimim",
  "Сводка смены": "Smena xulosasi",
  "Сводка дня": "Kun xulosasi",
  "Смена начата": "Smena boshlandi",
  "Закрыто": "Yopilgan",
  "Просрочено": "Muddati oʻtgan",
  "Требует внимания": "Eʼtibor talab qiladi",
  "и ещё {count}": "va yana {count}",
  "Позвать в команду": "Jamoaga taklif qilish",
  "Ссылка-приглашение или код компании: человек входит сам и сразу попадает в свой отдел.":
    "Taklif havolasi yoki kompaniya kodi: odam oʻzi kiradi va darhol oʻz boʻlimiga tushadi.",
  "Пригласить сотрудника": "Xodimni taklif qilish",
  "Подразделения": "Boʻlimlar",
  "Подразделений пока нет.": "Hozircha boʻlimlar yoʻq.",
  "Сотрудники": "Xodimlar",
  "из {count}": "{count} tadan",
  "Найти человека или должность": "Odam yoki lavozimni izlash",
  "Поиск по сотрудникам": "Xodimlar boʻyicha qidiruv",
  "Никого не нашли.": "Hech kim topilmadi.",
  "Сотрудников пока нет.": "Hozircha xodimlar yoʻq.",
  "Последние действия": "Soʻnggi amallar",
  "Рабочие часы и уведомления": "Ish soatlari va bildirishnomalar",
  "закрыто {count}": "yopilgan {count}",
  "проблем {count}": "muammo {count}",
  "Открыть карточку": "Kartochkani ochish",
  "Открытие": "Ochilish",
  "Закрытие": "Yopilish",
  "Сохранить часы": "Soatlarni saqlash",
  "Алерты только в рабочее время": "Ogohlantirishlar faqat ish vaqtida",
  "Вторая ступень: пинг админам": "Ikkinchi bosqich: adminlarga signal",
  "Если руководитель молчит": "Agar rahbar javob bermasa",
  "Порог второй ступени, часы": "Ikkinchi bosqich chegarasi, soat",
  "{hours} ч": "{hours} soat",
  "Напоминать в каждой смене": "Har smenada eslatish",
  "Мьют до {when}": "{when} gacha ovozsiz",
  "Мьют выключен": "Ovozsiz rejim oʻchirilgan",
  "Ночью уведомления не уходят в чат, но копятся в приложении — утренний разбор не потеряется.":
    "Kechasi bildirishnomalar chatga ketmaydi, lekin ilovada toʻplanadi — ertalabki tahlil yoʻqolmaydi.",
  "Сбрасывать нечего — всё уже закрыто.":
    "Tozalash uchun hech narsa yoʻq — hammasi yopilgan.",
  "Удалить {tasks} поручений и {issues} проблем?":
    "{tasks} ta topshiriq va {issues} ta muammo oʻchirilsinmi?",
  "Точно? Действие необратимо. Завершённые поручения и история останутся.":
    "Ishonchingiz komilmi? Amalni qaytarib boʻlmaydi. Tugallangan topshiriqlar va tarix qoladi.",
  "Удалено: поручений {tasks}, проблем {issues}.":
    "Oʻchirildi: topshiriqlar {tasks}, muammolar {issues}.",
  "Данные изменились, пока ты подтверждал. Открой сброс заново.":
    "Tasdiqlayotganingizda maʼlumotlar oʻzgardi. Tozalashni qaytadan oching.",
  "Опасная зона": "Xavfli hudud",
  "Убирает незакрытые поручения и открытые проблемы. Завершённые задачи, KPI и история сдач остаются; тестовый пул сбрасывается отдельно.":
    "Yopilmagan topshiriqlar va ochiq muammolarni olib tashlaydi. Tugallangan vazifalar, KPI va topshirish tarixi qoladi; sinov toʻplami alohida tozalanadi.",
  "Считаем…": "Hisoblanmoqda…",
  "Сбросить текущую работу": "Joriy ishni tozalash",

  // -------------------------------------------- «Проблемы» смены (11.4) ---
  "Журнал проблем не открылся": "Muammolar jurnali ochilmadi",
  "Назад к задачам": "Vazifalarga qaytish",
  "Журнал проблем": "Muammolar jurnali",
  "Что на смене пошло не так — и кто это закрывает.":
    "Smenada nima xato boʻldi — va buni kim hal qilmoqda.",
  "+ Сообщить": "+ Xabar berish",
  "У тебя открытых проблем нет": "Sizda ochiq muammo yoʻq",
  "Журнал пуст": "Jurnal boʻsh",
  "Сломалось оборудование, закончились расходники, гость недоволен — заведи карточку, чтобы смена не теряла проблему.":
    "Jihoz buzildi, sarf materiallari tugadi, mehmon norozi — kartochka oching, smena muammoni yoʻqotmasin.",
  "висит {age}": "{age} ochiq turibdi",
  "· завёл {name}": "· ochgan: {name}",
  "· на {name}": "· {name} ga",
  "· из поручения": "· topshiriqdan",
  "Новая проблема": "Yangi muammo",
  "Что случилось": "Nima boʻldi",
  "Например: не работает терминал на баре":
    "Masalan: bardagi terminal ishlamayapti",
  "Категория": "Turkum",
  "Насколько срочно": "Qanchalik shoshilinch",
  "Где (необязательно)": "Qayerda (majburiy emas)",
  "Зал, кухня, бар, склад…": "Zal, oshxona, bar, ombor…",
  "Подробности (необязательно)": "Tafsilotlar (majburiy emas)",
  "Что уже пробовали, кому сказали, что нужно для решения":
    "Nima sinab koʻrildi, kimga aytildi, hal qilish uchun nima kerak",
  "Записываю…": "Yozilmoqda…",
  "Завести карточку": "Kartochka ochish",
  "Руководитель отдела увидит проблему в колокольчике и в журнале. В чат сообщение не уходит — это не срочный алерт.":
    "Boʻlim rahbari muammoni qoʻngʻiroqcha va jurnalda koʻradi. Chatga xabar ketmaydi — bu shoshilinch ogohlantirish emas.",
  "Проблема": "Muammo",
  "Завёл {name} · смена {date} · висит {age}":
    "Ochgan: {name} · smena {date} · {age} ochiq",
  " · ответственный: {name}": " · masʼul: {name}",
  "Решено": "Hal qilindi",
  "Переоткрыть": "Qayta ochish",
  "Назначить на себя": "Oʻzimga belgilash",
  "История": "Tarix",
  "система": "tizim",
  "Добавить комментарий": "Izoh qoʻshish",
  "Отправить": "Yuborish",

  // Общие мелкие подписи, которые встречаются на обоих экранах.
  "Назад": "Orqaga",
  "Обновить": "Yangilash",
  "Снять": "Bekor qilish",

  // -------------------------------------------------------- «Лента» (11.4) --
  // Экран, куда приложение открывается по умолчанию: события смены и фильтры.
  "Лента недоступна": "Lenta mavjud emas",
  "События смены": "Smena voqealari",
  "{count} новых": "{count} yangi",
  "Поиск по имени или должности": "Ism yoki lavozim boʻyicha qidiruv",
  "Поиск сотрудника": "Xodimni izlash",
  "Фильтр": "Filtr",
  "Сбросить фильтры": "Filtrlarni tozalash",
  "Видны только твои действия. Расширенные фильтры доступны руководителю подразделения и управляющему.":
    "Faqat sizning amallaringiz koʻrinadi. Kengaytirilgan filtrlar boʻlim rahbari va boshqaruvchiga ochiq.",
  "Пока тихо": "Hozircha jim",
  "Здесь появятся отметки и поручения.":
    "Bu yerda belgilar va topshiriqlar paydo boʻladi.",
  "Предыдущий день": "Oldingi kun",
  "Следующий день": "Keyingi kun",
  "Новые события: {count}": "Yangi voqealar: {count}",
  "Новые · {count}": "Yangi · {count}",
  "Убрать фильтр {label}": "Filtrni olib tashlash: {label}",
  "Фильтры ленты": "Lenta filtrlari",
  "Закрыть фильтры": "Filtrlarni yopish",
  "Фильтры": "Filtrlar",
  "Закрыть": "Yopish",
  "Все подразделения": "Barcha boʻlimlar",
  "Сотрудник": "Xodim",
  "Поиск сотрудника в фильтре": "Filtrda xodim izlash",
  "Все сотрудники": "Barcha xodimlar",
  "Сбросить": "Tozalash",
  "Тестовый сотрудник": "Sinov xodimi",
  "тест": "sinov",
  "Открыть подразделение {name}": "Boʻlimni ochish: {name}",

  // ---------------------------------------------------- «Стандарты» (11.4) ---
  // Инструкции с короткими тестами: читают новые сотрудники и сдают сменой.
  "Стандарты": "Standartlar",
  "Инструкции и короткие тесты по ним":
    "Yoʻriqnomalar va ular boʻyicha qisqa testlar",
  "+ Стандарт": "+ Standart",
  "Стандартов пока нет": "Hozircha standartlar yoʻq",
  "Руководитель добавит инструкции — здесь появятся они и тесты к ним.":
    "Rahbar yoʻriqnomalar qoʻshadi — bu yerda ular va testlar paydo boʻladi.",
  "Сдано стандартов": "Topshirilgan standartlar",
  "сдано": "topshirilgan",
  "не сдано": "topshirilmagan",
  "Назад к списку": "Roʻyxatga qaytish",
  "Стандарт": "Standart",
  "{category} · порог {percent}%": "{category} · chegara {percent}%",
  "Обязательный: не сдавшие попадают в отчёт смены":
    "Majburiy: topshirmaganlar smena hisobotiga tushadi",
  "Сделать обязательным для отчёта смены":
    "Smena hisoboti uchun majburiy qilish",
  "Теста к этому стандарту нет — достаточно прочитать инструкцию.":
    "Bu standartga test yoʻq — yoʻriqnomani oʻqish kifoya.",
  "Ответ неверный — вернись к инструкции выше.":
    "Javob xato — yuqoridagi yoʻriqnomaga qayting.",
  "Сдано": "Topshirildi",
  "Пока не сдано": "Hozircha topshirilmagan",
  " Перечитай инструкцию и попробуй снова.":
    " Yoʻriqnomani qayta oʻqing va yana urinib koʻring.",
  "Попробовать снова": "Yana urinib koʻrish",
  "Проверить ответы": "Javoblarni tekshirish",
  "Новый стандарт": "Yangi standart",
  "Пиши как для нового сотрудника: что сделать, в каком порядке и почему.":
    "Yangi xodim uchun yozing: nima qilish, qanday tartibda va nima uchun.",
  "Название": "Nomi",
  "Гигиена рук перед сменой": "Smenadan oldin qoʻl gigienasi",
  "Значок": "Belgi",
  "Короткое описание (для списка)": "Qisqa taʼrif (roʻyxat uchun)",
  "Инструкция": "Yoʻriqnoma",
  "1. Помой руки…": "1. Qoʻllarni yuving…",
  "Обязательный: не сдавшие попадут в пробелы отчёта смены.":
    "Majburiy: topshirmaganlar smena hisoboti kamchiliklariga tushadi.",
  "Тест": "Test",
  "Вопрос {number}": "Savol {number}",
  "Удалить вопрос": "Savolni oʻchirish",
  "График": "Jadval",
  "График смен": "Smenalar jadvali",
  "Верный вариант": "Toʻgʻri variant",
  "Вариант": "Variant",
  "+ Вопрос": "+ Savol",
  "Сохранить стандарт": "Standartni saqlash",
};
