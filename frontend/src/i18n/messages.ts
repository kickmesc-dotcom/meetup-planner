/**
 * Тексты интерфейса на двух языках (B2B_PLATFORM_PLAN, шаг 2.5).
 *
 * Почему не библиотека. Приложению нужны ровно две локали, подстановка
 * `{name}` и переключение без перезагрузки. i18next с плагинами весит больше,
 * чем весь экран входа, и требует провайдера в каждом тесте. Здесь словари —
 * обычные объекты, а `en` типизирован как `Record<MessageKey, string>`: забыть
 * перевод нельзя, это ошибка компиляции.
 *
 * Почему плоские ключи, а не вложенность. `auth.login.title` читается в коде
 * целиком, поиск по нему находит все места, а `t("...")` не падает на
 * недозаполненном объекте.
 *
 * Правки от управляющего (`app.texts` из админки) живут отдельно и перекрывают
 * русские значения на сервере; словарь — база, без которой экран не останется
 * пустым.
 */

export const ru = {
  // --- Общее ---
  "locale.label": "Язык",
  "locale.ru": "Русский",
  "locale.en": "English",
  "locale.uz": "Oʻzbekcha",

  // --- Вход, регистрация, сброс ---
  "auth.login.title": "Вход",
  "auth.register.title": "Новый аккаунт",
  "auth.forgot.title": "Сброс пароля",
  "auth.login.submit": "Войти",
  "auth.register.submit": "Создать аккаунт",
  "auth.forgot.submit": "Отправить ссылку",
  "auth.invited": "Тебя пригласили в команду. Войди или создай аккаунт — и сразу присоединишься к организации по ссылке.",
  "auth.login.hint": "Рабочее приложение смены: задачи, чек-листы и график.",
  "auth.register.hint": "Аккаунт нужен, чтобы работать с компьютера и без Telegram.",
  "auth.forgot.hint": "Пришлём ссылку на почту — она живёт час и срабатывает один раз.",
  "auth.sent": "Если адрес зарегистрирован, письмо уже в пути. Открой ссылку из него и задай новый пароль.",
  "auth.backToLogin": "Вернуться ко входу",
  "auth.name.label": "Как тебя зовут",
  "auth.name.placeholder": "Необязательно",
  "auth.email.label": "Почта",
  "auth.password.label": "Пароль",
  "auth.password.placeholder": "Не короче 8 символов",
  "auth.emailRequired": "Введи адрес почты.",
  "auth.pending": "Секунду…",
  "auth.forgot": "Забыл пароль",
  "auth.create": "Создать аккаунт",
  "auth.haveAccount": "У меня уже есть аккаунт",
  "auth.telegramNote": "Внутри Telegram вход не нужен: приложение открывается из бота и уже знает, кто ты.",
  "auth.noorg.title": "Аккаунт готов",
  "auth.noorg.text": "Осталось попасть в организацию: попроси управляющего прислать приглашение на эту почту. После этого данные появятся сами.",
  "auth.noorg.leaving": "Выходим…",
  "auth.noorg.logout": "Выйти",

  // --- Приглашение ---
  "invite.joined.title": "Ты в организации",
  "invite.joined.text": "{org} · {role}. Данные смены появятся сразу после входа.",
  "invite.error.title": "Приглашение не открылось",
  "invite.error.go": "Перейти в приложение",
  "invite.title": "Приглашение в команду",
  "invite.role": "Тебе открывают доступ с ролью «{role}». Присоединиться можно до {until}.",
  "invite.emailNote": "Приглашение выписано на {email} — оно сработает только под этим адресом.",
  "invite.joining": "Присоединяемся…",
  "invite.join": "Присоединиться",
  "invite.later": "Не сейчас",
  "invite.switchAccount": "Войти под другой почтой",
  "invite.openApp": "Открыть приложение",
  "role.owner": "Владелец",
  "role.manager": "Управляющий",
  "role.staff": "Сотрудник",

  // --- Сброс пароля ---
  "reset.done.title": "Пароль обновлён",
  "reset.done.text": "Все прежние входы закрыты — это защита на случай, если ссылку увидел кто-то ещё.",
  "reset.done.button": "Войти с новым паролем",
  "reset.title": "Новый пароль",
  "reset.hint": "Придумай пароль не короче 8 символов. После сохранения все устройства выйдут из аккаунта.",
  "reset.password": "Пароль",
  "reset.password.placeholder": "Не короче 8 символов",
  "reset.repeat": "Ещё раз",
  "reset.save": "Сохранить пароль",
  "reset.saving": "Сохраняем…",
  "reset.short": "Пароль короче 8 символов.",
  "reset.mismatch": "Пароли не совпадают.",
  "reset.needNew": "Ссылка не подходит? Запросить новую",

  // --- Подтверждение почты ---
  "verify.title": "Подтверждаем почту…",
  "verify.hint": "Один момент — проверяем ссылку из письма.",
  "verify.done.title": "Почта подтверждена",
  "verify.done.text": "Теперь на этот адрес придут вход, сброс пароля и важные уведомления. Ничего больше делать не нужно.",
  "verify.done.button": "Перейти в приложение",
  "verify.error.title": "Ссылка не подошла",
  "verify.error.hint": "Ссылка живёт двое суток и работает один раз. Попроси новую в профиле: «Подтвердить почту» — и открой свежее письмо.",
  "verify.error.button": "В приложение",

  // --- Навигация ---
  "nav.feed": "События",
  "nav.tasks": "Задачи",
  "nav.shift": "Смена",
  // Экран — расписание смен, а не сводка часов: подпись говорит, что внутри.
  "nav.table": "График",
  "nav.team": "Команда",
  "nav.admin": "Админ",
  "nav.profile": "Профиль",
  "nav.tasksOpen": "{label}, открытых: {count}",

  // --- Шапки экранов оболочки ---
  "app.profile.title": "Профиль",
  "app.profile.hint": "Подразделение, опыт и обратная связь.",

  // --- Тема ---
  "theme.toDark": "Включить тёмную тему",
  "theme.toLight": "Включить светлую тему",

  // --- Ошибки сервера, которые видит человек на входе ---
  "error.bad_email": "Похоже, в адресе опечатка.",
  "error.invalid_credentials": "Неверная почта или пароль.",
  "error.email_taken": "Этот адрес уже зарегистрирован — попробуй войти.",
  "error.password_too_short": "Пароль короче 8 символов.",
  "error.password_too_long": "Пароль длиннее 128 символов.",
  "error.password_has_spaces": "Пароль не должен начинаться или заканчиваться пробелом.",
  "error.password_not_set": "У этого аккаунта нет пароля: войди через Telegram или запроси сброс по почте.",
  "error.session_invalid": "Вход истёк — войди снова.",
  "error.reset_invalid": "Ссылка сброса не подходит — запроси новую.",
  "error.reset_expired": "Срок ссылки истёк — запроси новую.",
  "error.verify_invalid": "Ссылка подтверждения не подходит — запроси новую в профиле.",
  "error.verify_expired": "Срок ссылки истёк (двое суток) — запроси новую в профиле.",
  "error.org_required": "Тебя ещё не пригласили в организацию.",
  "error.org_inactive": "Организация заблокирована — обратись к управляющему.",
  "error.org_missing": "Организация не найдена — обратись к управляющему.",
  "error.invite_invalid": "Ссылка не подходит — попроси новую у управляющего.",
  "error.invite_expired": "Срок приглашения истёк — попроси новую ссылку.",
  "error.invite_used": "Этой ссылкой уже воспользовались.",
  "error.invite_revoked": "Приглашение отозвали.",
  "error.invite_not_found": "Приглашение уже удалено.",
  "error.invite_already_accepted": "По этой ссылке уже присоединились.",
  "error.invite_email_mismatch": "Приглашение выписано на другую почту — войди под тем адресом, на который его прислали.",
  "error.invite_limit": "Слишком много активных приглашений — отзови лишние и попробуй снова.",
  "error.bad_invite_ttl": "Срок приглашения — от 1 до 30 дней.",
  "error.org_not_found":
    "Такой компании нет. Проверь код или название — регистр не важен, но слова должны совпадать.",
  "error.join_rate_limited":
    "Слишком много попыток. Подожди десять минут или попроси ссылку-приглашение.",
  "error.bad_name": "Название компании слишком короткое.",
  "error.bad_slug":
    "Короткий адрес — только латиница, цифры и дефис.",
} as const;

export type MessageKey = keyof typeof ru;

/**
 * Английский словарь. `Record<MessageKey, string>` — гарантия, что новый ключ
 * без перевода не соберётся, а лишний ключ подсветится ошибкой.
 */
export const en: Record<MessageKey, string> = {
  "locale.label": "Language",
  "locale.ru": "Русский",
  "locale.en": "English",
  "locale.uz": "Oʻzbekcha",

  "auth.login.title": "Sign in",
  "auth.register.title": "New account",
  "auth.forgot.title": "Reset password",
  "auth.login.submit": "Sign in",
  "auth.register.submit": "Create account",
  "auth.forgot.submit": "Send link",
  "auth.invited": "You've been invited to the team. Sign in or create an account and you'll join the organization right away.",
  "auth.login.hint": "The shift app: tasks, checklists and schedule.",
  "auth.register.hint": "An account lets you work from a computer without Telegram.",
  "auth.forgot.hint": "We'll email you a link — it works once and expires in an hour.",
  "auth.sent": "If the address is registered, the email is on its way. Open the link and set a new password.",
  "auth.backToLogin": "Back to sign in",
  "auth.name.label": "Your name",
  "auth.name.placeholder": "Optional",
  "auth.email.label": "Email",
  "auth.password.label": "Password",
  "auth.password.placeholder": "At least 8 characters",
  "auth.emailRequired": "Enter your email address.",
  "auth.pending": "One moment…",
  "auth.forgot": "Forgot password",
  "auth.create": "Create account",
  "auth.haveAccount": "I already have an account",
  "auth.telegramNote": "No need to sign in inside Telegram: the app opens from the bot and already knows who you are.",
  "auth.noorg.title": "Account is ready",
  "auth.noorg.text": "You just need to join an organization: ask your manager to send an invitation to this email. The data will appear automatically.",
  "auth.noorg.leaving": "Signing out…",
  "auth.noorg.logout": "Sign out",

  "invite.joined.title": "You're in",
  "invite.joined.text": "{org} · {role}. Shift data will appear right after you sign in.",
  "invite.error.title": "Invitation didn't open",
  "invite.error.go": "Go to the app",
  "invite.title": "Team invitation",
  "invite.role": "You're getting access with the role “{role}”. You can join until {until}.",
  "invite.emailNote": "This invitation was issued for {email} — it only works under that address.",
  "invite.joining": "Joining…",
  "invite.join": "Join",
  "invite.later": "Not now",
  "invite.switchAccount": "Sign in with another email",
  "invite.openApp": "Open the app",
  "role.owner": "Owner",
  "role.manager": "Manager",
  "role.staff": "Employee",

  "reset.done.title": "Password updated",
  "reset.done.text": "All previous sessions are closed — that protects you if someone else saw the link.",
  "reset.done.button": "Sign in with the new password",
  "reset.title": "New password",
  "reset.hint": "Use at least 8 characters. After saving, every device will be signed out.",
  "reset.password": "Password",
  "reset.password.placeholder": "At least 8 characters",
  "reset.repeat": "Repeat",
  "reset.save": "Save password",
  "reset.saving": "Saving…",
  "reset.short": "Password is shorter than 8 characters.",
  "reset.mismatch": "Passwords don't match.",
  "reset.needNew": "Link doesn't work? Request a new one",

  "verify.title": "Confirming your email…",
  "verify.hint": "One moment — checking the link from the email.",
  "verify.done.title": "Email confirmed",
  "verify.done.text": "This address will now receive sign-in, password reset and important notifications. Nothing else to do.",
  "verify.done.button": "Go to the app",
  "verify.error.title": "Link didn't work",
  "verify.error.hint": "The link lives for two days and works once. Request a new one in your profile — and open the fresh email.",
  "verify.error.button": "Go to the app",

  "nav.feed": "Events",
  "nav.tasks": "Tasks",
  "nav.shift": "Shift",
  "nav.table": "Schedule",
  "nav.team": "Team",
  "nav.admin": "Admin",
  "nav.profile": "Profile",
  "nav.tasksOpen": "{label}, open: {count}",

  "app.profile.title": "Profile",
  "app.profile.hint": "Department, experience and feedback.",

  "theme.toDark": "Switch to dark theme",
  "theme.toLight": "Switch to light theme",

  "error.bad_email": "The address looks mistyped.",
  "error.invalid_credentials": "Wrong email or password.",
  "error.email_taken": "This address is already registered — try signing in.",
  "error.password_too_short": "Password is shorter than 8 characters.",
  "error.password_too_long": "Password is longer than 128 characters.",
  "error.password_has_spaces": "Password can't start or end with a space.",
  "error.password_not_set": "This account has no password: sign in via Telegram or reset it by email.",
  "error.session_invalid": "Session expired — sign in again.",
  "error.reset_invalid": "Reset link is not valid — request a new one.",
  "error.reset_expired": "The link has expired — request a new one.",
  "error.verify_invalid": "Confirmation link is not valid — request a new one in your profile.",
  "error.verify_expired": "The link has expired (two days) — request a new one in your profile.",
  "error.org_required": "You haven't been invited to an organization yet.",
  "error.org_inactive": "The organization is suspended — contact your manager.",
  "error.org_missing": "Organization not found — contact your manager.",
  "error.invite_invalid": "The link is not valid — ask your manager for a new one.",
  "error.invite_expired": "The invitation has expired — ask for a new link.",
  "error.invite_used": "This link has already been used.",
  "error.invite_revoked": "The invitation was revoked.",
  "error.invite_not_found": "The invitation was deleted.",
  "error.invite_already_accepted": "Someone has already joined with this link.",
  "error.invite_email_mismatch": "The invitation was issued for another email — sign in with the address it was sent to.",
  "error.invite_limit": "Too many active invitations — revoke some and try again.",
  "error.bad_invite_ttl": "Invitation lifetime is 1 to 30 days.",
  "error.org_not_found":
    "No such company. Check the code or name — case doesn't matter, but the words must match.",
  "error.join_rate_limited":
    "Too many attempts. Wait ten minutes or ask for an invitation link.",
  "error.bad_name": "The company name is too short.",
  "error.bad_slug": "The short address allows only latin letters, digits and hyphens.",
};

/**
 * Узбекский словарь (план, 8.3). Латинская графика — официальная в Узбекистане.
 *
 * Почему это отдельный пакет, а не «ещё два словаря рядом». Узбекский нужен
 * части команды, но не всем и не всегда: в одной сети смены говорят
 * по-русски, в другой половина зала — узбеки. Поэтому его включает
 * организация (флаг `uz_pack` в настройках, по умолчанию включён), а тарифное
 * будущее этой опции — отдельный вопрос, который к самой архитектуре перевода
 * отношения не имеет.
 *
 * Тип `Record<MessageKey, string>` здесь так же строг, как у `en`: новый
 * ключ без перевода не соберётся. Это важно именно для узбекского —
 * полупереведённая навигация хуже непереведённой.
 */
export const uz: Record<MessageKey, string> = {
  "locale.label": "Til",
  "locale.ru": "Русский",
  "locale.en": "English",
  "locale.uz": "Oʻzbekcha",

  "auth.login.title": "Kirish",
  "auth.register.title": "Yangi akkaunt",
  "auth.forgot.title": "Parolni tiklash",
  "auth.login.submit": "Kirish",
  "auth.register.submit": "Akkaunt ochish",
  "auth.forgot.submit": "Havolani yuborish",
  "auth.invited": "Sizni jamoaga taklif qilishdi. Kiring yoki akkaunt oching — va darhol tashkilotga qoʻshilasiz.",
  "auth.login.hint": "Smena ilovasi: vazifalar, chek-listlar va jadval.",
  "auth.register.hint": "Akkaunt kompyuterdan va Telegramʼsiz ishlash uchun kerak.",
  "auth.forgot.hint": "Pochtaga havola yuboramiz — u bir soat yashaydi va bir marta ishlaydi.",
  "auth.sent": "Manzil roʻyxatdan oʻtgan boʻlsa, xat yoʻlda. Havolani oching va yangi parol qoʻying.",
  "auth.backToLogin": "Kirishga qaytish",
  "auth.name.label": "Ismingiz",
  "auth.name.placeholder": "Majburiy emas",
  "auth.email.label": "Pochta",
  "auth.password.label": "Parol",
  "auth.password.placeholder": "Kamida 8 belgi",
  "auth.emailRequired": "Pochta manzilini kiriting.",
  "auth.pending": "Bir soniya…",
  "auth.forgot": "Parolni esdan chiqardim",
  "auth.create": "Akkaunt ochish",
  "auth.haveAccount": "Akkauntim bor",
  "auth.telegramNote": "Telegram ichida kirish shart emas: ilova botdan ochiladi va kim ekaningizni biladi.",
  "auth.noorg.title": "Akkaunt tayyor",
  "auth.noorg.text": "Tashkilotga qoʻshilish qoldi: rahbardan shu pochtaga taklif yuborishni soʻrang. Shundan keyin maʼlumotlar oʻzi paydo boʻladi.",
  "auth.noorg.leaving": "Chiqamiz…",
  "auth.noorg.logout": "Chiqish",

  "invite.joined.title": "Siz tashkilotdasiz",
  "invite.joined.text": "{org} · {role}. Smena maʼlumotlari kirgandan keyin darhol paydo boʻladi.",
  "invite.error.title": "Taklif ochilmadi",
  "invite.error.go": "Ilovaga oʻtish",
  "invite.title": "Jamoaga taklif",
  "invite.role": "Sizga «{role}» roli bilan kirish ochiladi. {until} gacha qoʻshilish mumkin.",
  "invite.emailNote": "Taklif {email} uchun yozilgan — faqat shu manzil orqali ishlaydi.",
  "invite.joining": "Qoʻshilamiz…",
  "invite.join": "Qoʻshilish",
  "invite.later": "Hozir emas",
  "invite.switchAccount": "Boshqa pochta bilan kirish",
  "invite.openApp": "Ilovani ochish",
  "role.owner": "Egasi",
  "role.manager": "Boshqaruvchi",
  "role.staff": "Xodim",

  "reset.done.title": "Parol yangilandi",
  "reset.done.text": "Barcha oldingi kirishlar yopildi — bu havolani boshqa birov koʻrgan boʻlsa, himoya.",
  "reset.done.button": "Yangi parol bilan kirish",
  "reset.title": "Yangi parol",
  "reset.hint": "Kamida 8 belgidan iborat parol oʻylab toping. Saqlangandan keyin barcha qurilmalar akkauntdan chiqadi.",
  "reset.password": "Parol",
  "reset.password.placeholder": "Kamida 8 belgi",
  "reset.repeat": "Yana bir marta",
  "reset.save": "Parolni saqlash",
  "reset.saving": "Saqlayapmiz…",
  "reset.short": "Parol 8 belgidan qisqa.",
  "reset.mismatch": "Parollar mos kelmadi.",
  "reset.needNew": "Havola toʻgʻri kelmadimi? Yangisini soʻrang",

  "verify.title": "Pochtani tasdiqlayapmiz…",
  "verify.hint": "Bir soniya — xatdagi havolani tekshiramiz.",
  "verify.done.title": "Pochta tasdiqlandi",
  "verify.done.text": "Endi bu manzilga kirish, parolni tiklash va muhim xabarlar keladi. Boshqa hech narsa qilish shart emas.",
  "verify.done.button": "Ilovaga oʻtish",
  "verify.error.title": "Havola toʻgʻri kelmadi",
  "verify.error.hint": "Havola ikki kun yashaydi va bir marta ishlaydi. Profilda yangisini soʻrang: «Pochtani tasdiqlash» — va yangi xatni oching.",
  "verify.error.button": "Ilovaga",

  "nav.feed": "Voqealar",
  "nav.tasks": "Vazifalar",
  "nav.shift": "Smena",
  "nav.table": "Jadval",
  "nav.team": "Jamoa",
  "nav.admin": "Admin",
  "nav.profile": "Profil",
  "nav.tasksOpen": "{label}, ochiq: {count}",

  "app.profile.title": "Profil",
  "app.profile.hint": "Boʻlim, tajriba va fikr-mulohaza.",

  "theme.toDark": "Tungi mavzuni yoqish",
  "theme.toLight": "Kunduzgi mavzuni yoqish",

  "error.bad_email": "Manzilda xato borga oʻxshaydi.",
  "error.invalid_credentials": "Pochta yoki parol xato.",
  "error.email_taken": "Bu manzil allaqachon roʻyxatdan oʻtgan — kirishga urinib koʻring.",
  "error.password_too_short": "Parol 8 belgidan qisqa.",
  "error.password_too_long": "Parol 128 belgidan uzun.",
  "error.password_has_spaces": "Parol boʻsh joy bilan boshlanmasligi yoki tugamasligi kerak.",
  "error.password_not_set": "Bu akkauntda parol yoʻq: Telegram orqali kiring yoki pochta orqali tiklang.",
  "error.session_invalid": "Kirish muddati tugadi — qaytadan kiring.",
  "error.reset_invalid": "Tiklash havolasi toʻgʻri kelmadi — yangisini soʻrang.",
  "error.reset_expired": "Havola muddati tugadi — yangisini soʻrang.",
  "error.verify_invalid": "Tasdiqlash havolasi toʻgʻri kelmadi — profilda yangisini soʻrang.",
  "error.verify_expired": "Havola muddati tugadi (ikki kun) — profilda yangisini soʻrang.",
  "error.org_required": "Sizni hali tashkilotga taklif qilishmagan.",
  "error.org_inactive": "Tashkilot bloklangan — rahbarga murojaat qiling.",
  "error.org_missing": "Tashkilot topilmadi — rahbarga murojaat qiling.",
  "error.invite_invalid": "Havola toʻgʻri kelmadi — rahbardan yangisini soʻrang.",
  "error.invite_expired": "Taklif muddati tugadi — yangi havola soʻrang.",
  "error.invite_used": "Bu havoladan allaqachon foydalanishgan.",
  "error.invite_revoked": "Taklif bekor qilindi.",
  "error.invite_not_found": "Taklif allaqachon oʻchirilgan.",
  "error.invite_already_accepted": "Bu havola orqali allaqachon qoʻshilishgan.",
  "error.invite_email_mismatch": "Taklif boshqa pochtaga yozilgan — u yuborilgan manzil bilan kiring.",
  "error.invite_limit": "Faol takliflar juda koʻp — ortiqchalarini bekor qilib, qayta urinib koʻring.",
  "error.bad_invite_ttl": "Taklif muddati — 1 kundan 30 kungacha.",
  "error.org_not_found":
    "Bunday kompaniya yoʻq. Kod yoki nomni tekshiring — registr muhim emas, lekin soʻzlar mos kelishi kerak.",
  "error.join_rate_limited":
    "Urinishlar juda koʻp. Oʻn daqiqa kuting yoki taklif havolasini soʻrang.",
  "error.bad_name": "Kompaniya nomi juda qisqa.",
  "error.bad_slug": "Qisqa manzil — faqat lotin harflari, raqamlar va chiziqcha.",
};
