# PROJECT OVERVIEW — Облік Витрат (Центри Надії)

> **Призначення файлу.** Це контекст-документ для швидкого «входження» людини або AI-агента
> у проєкт. Прочитай його ПЕРШИМ перед будь-якими змінами. Він описує архітектуру, модель даних,
> потоки, конвенції та «підводні камені». План розробки ведеться окремо у `TODO.md`
> (єдине джерело правди щодо задач). Схема БД — у `schema.sql`.

> Використовуй multi_edit.
> Не генеруй довгих пояснень своїх дій - лише стисло, що зроблено і причину.

---

## 1. Що це за проєкт

Система обліку витрат для мережі благодійних осередків **«Центри Надії» (ЦН)**.
Користувачі (волонтери/співробітники ЦН) вносять витрати, адміністратор керує центрами,
користувачами, категоріями та бюджетами.

**Три режими роботи (усі мають працювати):**
1. **Бот у Telegram** — надсилання фото чека → AI-розпізнавання (Gemini) → картка підтвердження.
2. **Telegram WebApp** — той самий веб-інтерфейс, відкритий усередині Telegram.
3. **Повноцінний вебдодаток** — у звичайному браузері (вхід за одноразовим кодом).

---

## 2. Технологічний стек

| Шар | Технологія |
|-----|-----------|
| Бот | `aiogram` 3.x (long polling) |
| Веб-бекенд | `FastAPI` + `uvicorn` + `Jinja2` |
| БД | **MySQL** через `aiomysql` (пул з'єднань) |
| AI (OCR чеків) | Google **Gemini** (`google-genai` SDK) |
| Зображення | `Pillow` |
| Конфіг | `python-dotenv` (`.env`) |
| Сесії браузера | підписані кукі (`itsdangerous.URLSafeSerializer`) |

Залежності — `requirements.txt`. Python 3.10+.

---

## 3. Як усе запускається

Точка входу — **`main.py`**. Він:
1. Викликає `database.load_users()` — наповнює in-memory кеш `users_cache`.
2. Підключає всі роутери aiogram.
3. Через `asyncio.gather` **одночасно** запускає:
   - `uvicorn` (FastAPI) на `127.0.0.1:PORT` (за замовчуванням 8000),
   - `dp.start_polling(bot)` (Telegram-бот).

> ⚠️ Бот і веб-сервер живуть в **одному процесі** та **одному event loop**.
> Тому веб-ендпоінти можуть напряму викликати `bot.send_message(...)` (напр. сповіщення
> користувачу при призначенні ЦН). Це навмисна архітектурна особливість — не «ламай» її.

**Розгортання:** продакшн працює на **VPS**, НЕ локально. Локальна машина розробника —
Windows 11 або Ubuntu Linux (уточняй яка ОС на початку сесії) + VS Code + агент Continue. Агент редагує файли й робить git-коміти; команди перевірки/запити до БД/запуск скриптів **передає користувачу** і чекає на результат.

---

## 4. Структура файлів

```
main.py              # Точка входу: піднімає uvicorn + бот одночасно
config.py            # Читання .env (токени, БД, URL, PORT, SECRET_KEY)
bot_setup.py         # Глобальні об'єкти bot та dp (Dispatcher)
database.py          # Уся робота з MySQL + in-memory users_cache
ai_service.py        # Gemini: parse_receipt_image()
webapp.py            # FastAPI: усі HTTP-ендпоінти, auth, шаблони, статика
schema.sql           # DDL усіх таблиць + початкові категорії
requirements.txt     # Залежності
instruction.md       # Текст інструкції для користувачів (виводиться ботом)
TODO.md              # План розробки (SSOT для задач)
PROJECT_OVERVIEW.md  # ← цей файл

handlers/
  registration.py    # /start, реєстрація (ім'я→місто), /login (код для веб)
  receipts.py        # Обробка фото чека, render_summary(), збереження файлу
  receipt_callbacks.py # Кнопки картки: зберегти / скасувати / вибір категорії
  settings.py        # /settings — зміна назви центру (ЗАСТАРІЛЕ, див. §11)
  instructions.py    # /help, /instruction
  keyboards.py       # Reply-клавіатури (webapp_kb)
  states.py          # FSM StatesGroup: UserState, SettingsState, ReceiptState

templates/
  index.html         # Головний SPA-інтерфейс користувача
  admin.html         # Панель адміністратора
  login.html         # Сторінка входу за 6-значним кодом

static/
  js/app.js          # Логіка index.html (витрати, бюджети, налаштування)
  js/admin.js        # Логіка admin.html (users/centers/categories/matrix)
  css/...            # Стилі

receipts/            # Завантажені фото чеків (створюється автоматично, монтується на /receipts)
```

---

## 5. Модель даних (MySQL)

Деталі — у `schema.sql`. Ключові таблиці та зв'язки:

- **`centers`** — Центри Надії (`id`, `name` UNIQUE, `city`, `is_active`).
- **`users`** — `telegram_id` (PK), `name`, `city`, `center_id` (FK→centers, NULLable),
  `role` ENUM(`user`,`admin`), `status` ENUM(`pending`,`active`,`blocked`).
- **`categories`** — глобальний довідник (`id` VARCHAR як `cat_xxx`, `name` UNIQUE, `sort_order`, `is_active`).
- **`center_categories`** — **матриця** «які категорії дозволені якому ЦН» (PK: center_id+category_id).
- **`expenses`** — `id` VARCHAR, `date`, `telegram_id` (FK), `center_id` (FK), `amount` DECIMAL,
  `expense_name`, `category_id` (FK), `receipt_path`, `created_at`.
- **`budgets`** — бюджет на категорію/ЦН/місяць (`month` = `YYYY-MM`, UNIQUE center+category+month).
- **`api_logs`** — логи токенів Gemini (`input_tokens`, `output_tokens`, `estimated_cost`).
- **`auth_codes`** — одноразові 6-значні коди для входу в браузер (`expires_at`, `is_used`).

**Ключові інваріанти:**
- Витрата завжди прив'язана до `center_id` (визначається з центру користувача).
- Категорії, доступні користувачу, = перетин `center_categories` для його ЦН; якщо порожньо —
  fallback на всі активні категорії. «Інше» завжди в кінці списку.
- Бюджети — **тільки по ЦН** (не по користувачу). Старі user-функції — заглушки.

---

## 6. Ролі та доступ

- **`user`** — бачить витрати **свого ЦН** (не лише власні). Може додавати/редагувати/видаляти.
- **`admin`** — бачить усе, керує центрами, користувачами, категоріями, матрицею, бюджетами.
- **`status`**: `pending` (чекає призначення ЦН) → `active` (може вносити витрати) → `blocked`.
- Призначення ЦН користувачу робить **лише адмін** через панель. Після призначення бот шле
  вітальне повідомлення (див. `admin_set_user_center` у `webapp.py`).

`database.is_admin(user_id)` перевіряє роль через `users_cache`.

---

## 7. Автентифікація (3 джерела)

`webapp.get_current_user(request)` визначає `user_id` у такому порядку:
1. **Кукі `session_token`** — підписаний `URLSafeSerializer(SECRET_KEY)`. Основний шлях для браузера.
2. **Query `?user_id=`** — для відкриття з Telegram WebApp.
3. **Заголовок `x-telegram-user-id`**.

Потік входу в браузері:
1. Користувач у боті: `/login` → `create_auth_code()` → 6-значний код (10 хв).
2. На `/login` вводить код → `POST /api/auth/login` → `validate_auth_code()` → ставить кукі на 30 днів.

> ⚠️ **Безпека (відомий борг):** query/header `user_id` не підписані — можлива підміна.
> Ендпоінти з `{user_id}` у шляху НЕ звіряють його з `current_user`. Див. §11.

---

## 8. HTTP API (FastAPI, `webapp.py`)

**Auth:** `POST /api/auth/login`, `POST /api/auth/logout`
**Сторінки:** `GET /`, `GET /login`, `GET /admin` (редірект на /login якщо не адмін)
**Категорії/налаштування:** `GET /api/categories`, `GET /api/categories/{center_id}`,
`GET /api/user/{user_id}/center`, `GET /api/user/{user_id}/role`
**Витрати:** `GET /api/expenses/{user_id}` (підтримує `?center_id=` для адміна; `center_id=0` = усі),
`POST /api/expenses/{user_id}`, `PUT /api/expenses/{user_id}/{expense_id}`,
`DELETE /api/expenses/{user_id}/{expense_id}`
**Завантаження:** `POST /api/upload/{user_id}` (фото чека → `receipts/USER/YYYY/MM/...`)
**Бюджети:** `GET /api/budgets/{user_id}?month=`, `GET /api/budgets/center/{center_id}?month=`,
`POST /api/admin/budgets`
**Адмін:** `GET /api/admin/users`, `PUT /api/admin/users/{id}/center`,
`GET/POST /api/admin/categories`, `PUT /api/admin/categories/{id}`,
`GET /api/admin/matrix`, `POST /api/admin/matrix/toggle`,
`GET /api/admin/centers`, `POST /api/admin/centers`, `PUT /api/admin/centers/{id}`,
`GET /api/admin/centers/summary?month=`

Усі адмін-ендпоінти перевіряють `database.is_admin(current_user)` → інакше 403.

---

## 9. Потік розпізнавання чека (бот)

1. Користувач шле фото → `handlers/receipts.py::process_receipt_photo`.
2. Перевірка: користувач існує, `status == active`, має `center_id`.
3. Завантаження фото → `PIL.Image` → `get_categories(user_id)` (категорії його ЦН).
4. `ai_service.parse_receipt_image(image, valid_categories)` → Gemini повертає JSON
   (`amount`, `expense_name`, `category`, `receipt_date`, `receipt_time`) + `_usage` (токени).
5. Логування токенів у `api_logs` (`log_api_usage`, через `asyncio.create_task`).
6. Файл зберігається у `receipts/USER/YYYY/MM/`. Дані кладуться у FSM.
7. Якщо категорія не підібрана — інлайн-кнопки вибору (`selcat_*`).
8. Інакше `render_summary()` — картка з кнопками:
   - **✅ Зберегти** (`receipt_save`) → `add_expense()`;
   - **✏️ Редагувати у формі** → WebApp з `?draft=1&date=...&amount=...&...`;
   - **❌ Скасувати** (`receipt_cancel`) → видаляє локальний файл.

---

## 10. Конфігурація (`.env`)

Читається у `config.py` через `load_dotenv()`:

| Змінна | Призначення |
|--------|-------------|
| `TELEGRAM_TOKEN` | токен бота |
| `GEMINI_API_KEY` | ключ Google Gemini |
| `WEBAPP_URL` | публічна база URL (для посилань на чеки/WebApp) |
| `PORT` | порт uvicorn (default 8000) |
| `SECRET_KEY` | підпис куків (якщо нема — генерується випадково при старті!) |
| `DEBUG_DIAGNOSTICS` | `true` → показувати трейсбек помилок AI у чаті |
| `DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME` | MySQL |
| `SPREADSHEET_ID` | легасі (Google Sheets), зараз не використовується |

> ⚠️ Якщо `SECRET_KEY` не заданий у `.env`, він генерується заново при кожному рестарті →
> усі сесії інвалідуються. У продакшні **обов'язково** задавати фіксований `SECRET_KEY`.

---

## 11. Відомі проблеми / технічний борг (перевіряй перед роботою)

1. **`ai_service.py`:** модель `'gemini-3.8-flash'` — неіснуюча (має бути напр. `gemini-2.0-flash`).
   `optimize_image_for_ai` видалено (мертвий код; Telegram і так стискає фото).
2. **`static/js/app.js::saveSettings()`** шле POST на `/api/user/{id}/center`, який **видалено**
   з `webapp.py` (призначення ЦН тепер лише адміном) → мертвий код / 404.
3. **`handlers/settings.py`** (`/settings`) досі викликає `update_user_center` — застарілий потік
   (центр тепер призначає адмін). Кандидат на видалення/переробку.
4. **Безпека auth:** непідписані `?user_id=` / `x-telegram-user-id`; ендпоінти не звіряють
   `{user_id}` у шляху з `current_user` (можлива підміна чужого ID).
5. **`database.py`:** є заглушки (`build_category_formula`, `set_user_budget`, `debug_budgets`)
   та легасі-функції (`update_user_center`) — не видаляти наосліп, перевіряти посилання.
6. **`database_old.py`** — легасі (Google Sheets епоха), не використовується в рантаймі.
7. `get_all_users()` повертає лише `user_id/name/center` (без role/status) — для адмін-панелі
   використовується `get_all_users_details()`.

---

## 12. Конвенції та правила роботи з проєктом

- **Мова:** коментарі, повідомлення бота, документація — **українською**. Код/ідентифікатори — англ.
- **`TODO.md` — SSOT** для плану. Після кожного етапу: перевірка працездатності + git-коміт.
- **Не запускай сервер/скрипти локально** — продакшн на VPS. Команди для перевірки передавай
  користувачу і чекай результату. Агент сам лише редагує файли та робить коміти.
- **`users_cache`** — джерело істини про роль/центр у рантаймі. Після змін у `users` викликай
  `load_users()` (або відповідні функції, що це роблять), інакше кеш застаріє.
- **Категорії** завжди фільтруються по ЦН через `center_categories`; «Інше» — у кінці.
- **Бюджети** — по ЦН, не по користувачу.
- **Стиль комітів:** `feat(scope): ...`, `fix(scope): ...` (див. `git log`).
- **Не ламай** спільний event loop бота+веб (див. §3): прямі виклики `bot.*` з ендпоінтів — норма.

---

## 13. Швидкий чекліст для AI-агента перед змінами

1. Прочитай `PROJECT_OVERVIEW.md` (цей файл) + актуальний `TODO.md`.
2. Визнач, які шари зачіпає задача: `database.py` → `webapp.py` → `handlers/*` → `static/js/*` → `templates/*`.
3. Перевір, чи не тягне зміна застарілі функції/ендпоінти (§11).
4. Після редагування — запропонуй користувачу команду перевірки (на VPS) і дочекайся результату.
5. Зроби git-коміт зі змістовним повідомленням.
