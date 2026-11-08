/**
 * Тексты, которые `humanizeApiError` собирает из кодов сервера.
 *
 * Почему отдельный файл: коды и их человеческие формулировки живут в
 * `api/client.ts` рядом с логикой, и переносить их в `content.ts` значило бы
 * разорвать пару «код → текст». Здесь только переводы, ключ — русский
 * оригинал, как у остальных словарей экранов.
 *
 * Без них экран на английском показывал русский абзац про интернет, лимиты и
 * увольнение: `messages.ts` переводит 84 серверных кода, но общий разбор
 * (`humanizeApiError`) шёл мимо словаря.
 */
export const API_ERRORS_EN: Record<string, string> = {
  "Нет интернета. Включи сеть — введённое останется на месте, отправка повторится.":
    "No internet. Turn the network on — what you typed stays put and sending resumes.",
  "Сервер не ответил вовремя. Проверь сеть и повтори.":
    "The server did not answer in time. Check the network and try again.",
  "Нет связи с сервером. Проверь интернет и повтори — данные не потеряны.":
    "No connection to the server. Check the internet and try again — your data is safe.",
  "Файл слишком большой для загрузки. Сожми его или выбери другой.":
    "The file is too large to upload. Compress it or pick another one.",
  "Этот адрес для уведомлений не поддерживается. Попробуй включить напоминания в обычном браузере.":
    "This notification address is not supported. Try enabling reminders in a regular browser.",
  "ID состоит только из цифр — скопируй его из профиля Telegram.":
    "The ID contains digits only — copy it from the Telegram profile.",
  "Этот диапазон ID занят тестовым пулом: для человека он не подойдёт.":
    "This ID range is reserved for the demo pool: it will not work for a real person.",
  "Такой ID уже заведён в боте.": "This ID is already registered in the bot.",
  "Этот человек уволен — верни его из корзины в списке ниже.":
    "This person was dismissed — restore them from the trash below.",
  "Такой роли нет.": "No such role.",
  "Подразделение не найдено — обнови список.":
    "Department not found — refresh the list.",
  "Снимок уже удалён.": "The snapshot was already deleted.",
  "🔒 Эта функция пока недоступна.": "🔒 This feature is not available yet.",
  "Telegram сейчас недоступен (таймаут сети). Попробуй через минуту.":
    "Telegram is unavailable right now (network timeout). Try again in a minute.",
  "Бот не может писать в групповой чат. Проверь права бота.":
    "The bot cannot post in a group chat. Check the bot's permissions.",
  "Ошибка Telegram API. Попробуй ещё раз.": "Telegram API error. Try again.",
  "Не получилось отправить сообщение в чат. Попробуй ещё раз.":
    "Could not send the message to the chat. Try again.",
  "Бот ещё не видел ни одного мема такого типа — нужно, чтобы кто-то скинул медиа в чат после запуска бота.":
    "The bot has not seen a meme of this type yet — someone needs to send media to the chat after the bot starts.",
  "Игровая система сейчас выключена.": "The game system is off right now.",
  "На эту дату праздник уже есть.": "A holiday already exists on that date.",
  "Такой даты не существует — проверь день и месяц.":
    "That date does not exist — check the day and month.",
  "Напиши текст поздравления — без него праздник некуда публиковать.":
    "Write the greeting text — without it there is nowhere to publish the holiday.",
  "Праздник уже удалён.": "The holiday was already deleted.",
  "Себе дарить опыт не получится 🙂": "You cannot gift XP to yourself 🙂",
  "Донат доступен только в сам день рождения именинника.":
    "Gifting is only available on the person's birthday.",
  "Ты уже дарил опыт этому участнику в этом году.":
    "You have already gifted XP to this person this year.",
  "Своих очков не хватает: чтобы подарить 100 XP, надо их иметь. В чат уже улетела насмешка 😈":
    "Not enough XP: you need to have 100 XP to gift them. The chat already got the joke 😈",
  "Доступ закрыт: профиль уволен. Обратись к управляющему.":
    "Access closed: the profile was dismissed. Contact the manager.",
  "Этот сотрудник уже уволен.": "This employee is already dismissed.",
  "Данные уже удалены: восстановить нельзя.":
    "The data is already deleted: it cannot be restored.",
  "Сотрудник не в корзине — восстанавливать нечего.":
    "The employee is not in the trash — nothing to restore.",
  "Себя уволить нельзя.": "You cannot dismiss yourself.",
  "Управляющего увольняет только администратор.":
    "Only an administrator can dismiss a manager.",
  "Поручение уже зачтено.": "The task is already accepted.",
  "Проверь адрес почты — похоже, в нём опечатка.":
    "Check the email address — there seems to be a typo.",
  "Пароль короче 8 символов.": "The password is shorter than 8 characters.",
  "Пароль длиннее 128 символов.":
    "The password is longer than 128 characters.",
  "Пароль не должен начинаться или заканчиваться пробелом.":
    "The password must not start or end with a space.",
  "Этот адрес уже зарегистрирован — попробуй войти.":
    "This address is already registered — try signing in.",
  "Неверная почта или пароль.": "Wrong email or password.",
  "У этого аккаунта нет пароля: войди через Telegram или запроси сброс по почте.":
    "This account has no password: sign in via Telegram or request an email reset.",
  "Ссылка сброса не подходит — запроси новую.":
    "The reset link is not valid — request a new one.",
  "Срок ссылки истёк — запроси новую.":
    "The link has expired — request a new one.",
  "Ссылка подтверждения не подходит — запроси новую в профиле.":
    "The verification link is not valid — request a new one in your profile.",
  "Срок ссылки истёк (двое суток) — запроси новую в профиле.":
    "The link has expired (two days) — request a new one in your profile.",
  "Вход истёк — войди снова.": "The session expired — sign in again.",
  "Тебя ещё не пригласили в организацию.":
    "You have not been invited to an organization yet.",
  "Организация заблокирована — обратись к управляющему.":
    "The organization is blocked — contact the manager.",
  "Организация не найдена — обратись к управляющему.":
    "Organization not found — contact the manager.",
  "Ссылка не подходит — попроси новую у управляющего.":
    "The link is not valid — ask the manager for a new one.",
  "Срок приглашения истёк — попроси новую ссылку.":
    "The invitation has expired — ask for a new link.",
  "Этой ссылкой уже воспользовались.": "This link has already been used.",
  "Приглашение отозвали.": "The invitation was revoked.",
  "Приглашение уже удалено.": "The invitation was already deleted.",
  "По этой ссылке уже присоединились.":
    "Someone has already joined with this link.",
  "Приглашение выписано на другую почту — войди под тем адресом, на который его прислали.":
    "The invitation was issued for another email — sign in with the address it was sent to.",
  "Слишком много активных приглашений — отзови лишние и попробуй снова.":
    "Too many active invitations — revoke the extra ones and try again.",
  "Срок приглашения — от 1 до 30 дней.":
    "The invitation term is from 1 to 30 days.",
  "Это не изображение или формат не поддерживается. Нужен JPEG, PNG или WebP.":
    "This is not an image or the format is not supported. Use JPEG, PNG or WebP.",
  "Фото больше 8 МБ — выбери снимок поменьше.":
    "The photo is over 8 MB — pick a smaller one.",
  "Место для фото по тарифу закончилось — удали старые снимки или перейди на тариф выше.":
    "The photo quota for the plan is full — delete old photos or upgrade the plan.",
  "Файл пустой — выбери другой снимок.":
    "The file is empty — pick another photo.",
  "Фото не найдено — приложи его заново.":
    "The photo was not found — attach it again.",
  "У этого поручения нет такого исполнителя.":
    "This task has no such assignee.",
  "Сервис временно недоступен. Попробуй через минуту.":
    "The service is temporarily unavailable. Try again in a minute.",
  "Нет доступа.": "No access.",
  "Сервер ещё не обновился: функция появится после пересборки бэкенда.":
    "The server is not updated yet: the feature will appear after the backend rebuild.",
  "Не найдено.": "Not found.",
  "Не получилось. Попробуем ещё раз?": "Something went wrong. Try again?",
  "Неизвестная ошибка": "Unknown error",
};

export const API_ERRORS_UZ: Record<string, string> = {
  "Нет интернета. Включи сеть — введённое останется на месте, отправка повторится.":
    "Internet yoʻq. Tarmoqni yoqing — kiritilganlar joyida qoladi, yuborish davom etadi.",
  "Сервер не ответил вовремя. Проверь сеть и повтори.":
    "Server oʻz vaqtida javob bermadi. Tarmoqni tekshirib, qayta urinib koʻring.",
  "Нет связи с сервером. Проверь интернет и повтори — данные не потеряны.":
    "Server bilan aloqa yoʻq. Internetni tekshirib, qayta urinib koʻring — maʼlumotlar yoʻqolmadi.",
  "Файл слишком большой для загрузки. Сожми его или выбери другой.":
    "Fayl yuklash uchun juda katta. Uni siqib qoʻying yoki boshqasini tanlang.",
  "Этот адрес для уведомлений не поддерживается. Попробуй включить напоминания в обычном браузере.":
    "Bu bildirishnoma manzili qoʻllab-quvvatlanmaydi. Eslatmalarni oddiy brauzerda yoqib koʻring.",
  "ID состоит только из цифр — скопируй его из профиля Telegram.":
    "ID faqat raqamlardan iborat — uni Telegram profilidan koʻchirib oling.",
  "Этот диапазон ID занят тестовым пулом: для человека он не подойдёт.":
    "Bu ID oraligʻi demo pulga ajratilgan: haqiqiy odam uchun mos kelmaydi.",
  "Такой ID уже заведён в боте.": "Bunday ID botda allaqachon mavjud.",
  "Этот человек уволен — верни его из корзины в списке ниже.":
    "Bu odam ishdan boʻshatilgan — uni quyidagi roʻyxatdagi savatdan tiklang.",
  "Такой роли нет.": "Bunday rol yoʻq.",
  "Подразделение не найдено — обнови список.":
    "Boʻlinma topilmadi — roʻyxatni yangilang.",
  "Снимок уже удалён.": "Surat allaqachon oʻchirilgan.",
  "🔒 Эта функция пока недоступна.": "🔒 Bu funksiya hozircha mavjud emas.",
  "Telegram сейчас недоступен (таймаут сети). Попробуй через минуту.":
    "Telegram hozir mavjud emas (tarmoq kutilmoqda). Bir daqiqadan soʻng urinib koʻring.",
  "Бот не может писать в групповой чат. Проверь права бота.":
    "Bot guruh chatiga yozolmaydi. Bot huquqlarini tekshiring.",
  "Ошибка Telegram API. Попробуй ещё раз.":
    "Telegram API xatosi. Yana bir marta urinib koʻring.",
  "Не получилось отправить сообщение в чат. Попробуй ещё раз.":
    "Chatga xabar yuborilmadi. Yana bir marta urinib koʻring.",
  "Бот ещё не видел ни одного мема такого типа — нужно, чтобы кто-то скинул медиа в чат после запуска бота.":
    "Bot bunday memni hali koʻrmagan — bot ishga tushgandan keyin kimdir chatga media tashlashi kerak.",
  "Игровая система сейчас выключена.": "Oʻyin tizimi hozir oʻchirilgan.",
  "На эту дату праздник уже есть.": "Bu sanada bayram allaqachon bor.",
  "Такой даты не существует — проверь день и месяц.":
    "Bunday sana yoʻq — kun va oyni tekshiring.",
  "Напиши текст поздравления — без него праздник некуда публиковать.":
    "Tabrik matnini yozing — usiz bayramni joylashtirib boʻlmaydi.",
  "Праздник уже удалён.": "Bayram allaqachon oʻchirilgan.",
  "Себе дарить опыт не получится 🙂": "Oʻzingizga tajriba bera olmaysiz 🙂",
  "Донат доступен только в сам день рождения именинника.":
    "Sovgʻa faqat tugʻilgan kun egasining oʻz kunida mumkin.",
  "Ты уже дарил опыт этому участнику в этом году.":
    "Siz bu ishtirokchiga shu yilda allaqachon tajriba bergansiz.",
  "Своих очков не хватает: чтобы подарить 100 XP, надо их иметь. В чат уже улетела насмешка 😈":
    "Oʻz ballaringiz yetmaydi: 100 XP sovgʻa qilish uchun ular boʻlishi kerak. Chatga masxara allaqachon uchdi 😈",
  "Доступ закрыт: профиль уволен. Обратись к управляющему.":
    "Kirish yopildi: profil ishdan boʻshatilgan. Menejerga murojaat qiling.",
  "Этот сотрудник уже уволен.": "Bu xodim allaqachon ishdan boʻshatilgan.",
  "Данные уже удалены: восстановить нельзя.":
    "Maʼlumotlar allaqachon oʻchirilgan: tiklab boʻlmaydi.",
  "Сотрудник не в корзине — восстанавливать нечего.":
    "Xodim savatda emas — tiklaydigan narsa yoʻq.",
  "Себя уволить нельзя.": "Oʻzingizni ishdan boʻshatib boʻlmaydi.",
  "Управляющего увольняет только администратор.":
    "Menejerni faqat administrator ishdan boʻshatadi.",
  "Поручение уже зачтено.": "Topshiriq allaqachon qabul qilingan.",
  "Проверь адрес почты — похоже, в нём опечатка.":
    "Pochta manzilini tekshiring — xatoga oʻxshaydi.",
  "Пароль короче 8 символов.": "Parol 8 belgidan qisqa.",
  "Пароль длиннее 128 символов.": "Parol 128 belgidan uzun.",
  "Пароль не должен начинаться или заканчиваться пробелом.":
    "Parol boʻsh joy bilan boshlanmasligi yoki tugamasligi kerak.",
  "Этот адрес уже зарегистрирован — попробуй войти.":
    "Bu manzil allaqachon roʻyxatdan oʻtgan — kirib koʻring.",
  "Неверная почта или пароль.": "Pochta yoki parol notoʻgʻri.",
  "У этого аккаунта нет пароля: войди через Telegram или запроси сброс по почте.":
    "Bu akkauntda parol yoʻq: Telegram orqali kiring yoki pochta orqali tiklashni soʻrang.",
  "Ссылка сброса не подходит — запроси новую.":
    "Tiklash havolasi mos emas — yangisini soʻrang.",
  "Срок ссылки истёк — запроси новую.":
    "Havola muddati tugadi — yangisini soʻrang.",
  "Ссылка подтверждения не подходит — запроси новую в профиле.":
    "Tasdiqlash havolasi mos emas — profilda yangisini soʻrang.",
  "Срок ссылки истёк (двое суток) — запроси новую в профиле.":
    "Havola muddati tugadi (ikki kun) — profilda yangisini soʻrang.",
  "Вход истёк — войди снова.": "Kirish muddati tugadi — qayta kiring.",
  "Тебя ещё не пригласили в организацию.":
    "Sizni hali tashkilotga taklif qilishmagan.",
  "Организация заблокирована — обратись к управляющему.":
    "Tashkilot bloklangan — menejerga murojaat qiling.",
  "Организация не найдена — обратись к управляющему.":
    "Tashkilot topilmadi — menejerga murojaat qiling.",
  "Ссылка не подходит — попроси новую у управляющего.":
    "Havola mos emas — menejerdan yangisini soʻrang.",
  "Срок приглашения истёк — попроси новую ссылку.":
    "Taklif muddati tugadi — yangi havola soʻrang.",
  "Этой ссылкой уже воспользовались.": "Bu havoladan allaqachon foydalanishgan.",
  "Приглашение отозвали.": "Taklif bekor qilingan.",
  "Приглашение уже удалено.": "Taklif allaqachon oʻchirilgan.",
  "По этой ссылке уже присоединились.": "Bu havola orqali allaqachon qoʻshilishgan.",
  "Приглашение выписано на другую почту — войди под тем адресом, на который его прислали.":
    "Taklif boshqa pochtaga yozilgan — u yuborilgan manzil bilan kiring.",
  "Слишком много активных приглашений — отзови лишние и попробуй снова.":
    "Faol takliflar juda koʻp — ortiqchalarini bekor qilib, qayta urinib koʻring.",
  "Срок приглашения — от 1 до 30 дней.":
    "Taklif muddati — 1 kundan 30 kungacha.",
  "Это не изображение или формат не поддерживается. Нужен JPEG, PNG или WebP.":
    "Bu rasm emas yoki format qoʻllab-quvvatlanmaydi. JPEG, PNG yoki WebP kerak.",
  "Фото больше 8 МБ — выбери снимок поменьше.":
    "Surat 8 MB dan katta — kichikroq surat tanlang.",
  "Место для фото по тарифу закончилось — удали старые снимки или перейди на тариф выше.":
    "Tarif boʻyicha surat joyi tugadi — eski suratlarni oʻchiring yoki yuqori tarifga oʻting.",
  "Файл пустой — выбери другой снимок.":
    "Fayl boʻsh — boshqa surat tanlang.",
  "Фото не найдено — приложи его заново.":
    "Surat topilmadi — uni qaytadan biriktiring.",
  "У этого поручения нет такого исполнителя.":
    "Bu topshiriqda bunday ijrochi yoʻq.",
  "Сервис временно недоступен. Попробуй через минуту.":
    "Xizmat vaqtincha mavjud emas. Bir daqiqadan soʻng urinib koʻring.",
  "Нет доступа.": "Ruxsat yoʻq.",
  "Сервер ещё не обновился: функция появится после пересборки бэкенда.":
    "Server hali yangilanmagan: funksiya backend qayta yigʻilgandan keyin paydo boʻladi.",
  "Не найдено.": "Topilmadi.",
  "Не получилось. Попробуем ещё раз?": "Ishlamadi. Yana bir marta urinamizmi?",
  "Неизвестная ошибка": "Nomaʼlum xato",
};
