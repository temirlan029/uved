# 📘 Полная документация проекта `uvedom`

Discord-бот для автоматических уведомлений о событиях по расписанию.
Готов к деплою на Railway.

---

## 📁 Структура проекта

```
uvedom/
├── main.py              # Основной код бота (~620 строк)
├── requirements.txt     # discord.py, python-dotenv
├── Procfile             # worker: python main.py
├── .env                 # DISCORD_TOKEN (НЕ в git)
├── .env.example         # Шаблон .env
├── .gitignore           # .env, *.db, __pycache__ исключены
├── bot_config.db        # SQLite, создаётся автоматически (НЕ в git)
├── README.md            # Краткая инструкция
├── DOCS.md              # Этот файл
└── uved.txt             # Оригинальное ТЗ
```

---

## ⚙️ Установка

```bash
pip install -r requirements.txt
cp .env.example .env
# в .env вписать DISCORD_TOKEN=<твой токен>
python main.py
```

### Privileged Intents

В Discord Developer Portal → твоё приложение → Bot:
- ✅ **Server Members Intent** — для подсчёта участников по ролям
- ✅ **Message Content Intent** — для совместимости

### Права бота в канале

- `Send Messages`
- `Embed Links`
- `Mention Everyone` *(чтобы @everyone реально пинговал)*
- `Manage Messages` *(чтобы автоудаление работало в любых сценариях)*

---

## 🎮 Команды

### `/setup`
Настройка события.

| Параметр | Тип | Описание |
|----------|-----|----------|
| `time` | список | МСК, выбор из `12:00`–`22:00` (autocomplete) |
| `channel` | канал | Куда слать уведомление |
| `event_name` | список | Название (`capt`) |
| `admin` | пользователь *(опц.)* | Кому слать ЛС-напоминания. По умолчанию — вызвавший. |

После отправки команды появляется эфемерный **RoleSelect** — там можно выбрать **1–25 ролей** одним кликом. Никаких ID копировать не нужно.

### `/test`
Отправляет тестовое уведомление в текущий канал. Включает `@everyone` + выбранные роли. Удаляется через **5 минут**.

### `/test_dm`
Принудительно рассылает ЛС всем у кого есть упомянутые роли + админу. Эфемерный ответ с количеством отправленных/неотправленных ЛС.

---

## 📅 Расписание

События по умолчанию: **Пн, Ср, Пт, Сб** — изменяется в константе `DEFAULT_DAYS` в `main.py`.

В назначенное время по **Europe/Moscow** бот:

1. **−2 часа** → ЛС админу: `⏰ Напоминание: через 2 часа будет событие. Зайди чтобы не быть в очереди!`
2. **−30 минут** → ЛС админу: `⏰ Напоминание: через 30 минут будет событие. Зайди чтобы не быть в очереди!`
3. **В точное время:**
   - Embed в канал с упоминанием `@everyone` + ролей + кнопкой «Присоединиться»
   - ЛС всем у кого есть любая из упомянутых ролей (один раз на пользователя) + админу: `⏰ Зайди в {event_name}! Событие началось.`
4. **+1 час** → бот удаляет embed-сообщение из канала

---

## 🎯 Кнопка «Присоединиться»

- Toggle: первый клик добавляет пользователя в список, второй — убирает.
- Список и счётчик отображаются в embed и обновляются в реальном времени.
- **Каждый день** список начинается заново (key = `(event_id, event_date, user_id)`).
- View персистентный: переживает рестарт бота (`custom_id` + `client.add_view`).

---

## 🗄️ База данных (SQLite)

### `config`
| Поле | Тип |
|------|-----|
| `key` | TEXT (PK) |
| `value` | TEXT |

Хранит:
- `last_notification` — ISO-дата последнего отправленного уведомления (защита от дубля)
- `last_2h_<date>` / `last_30m_<date>` — пометки о ЛС-напоминаниях, чистятся при отправке нового события

### `events`
| Поле | Тип |
|------|-----|
| `id` | INTEGER (PK, AUTOINCREMENT) |
| `name` | TEXT |
| `channel_id` | INTEGER |
| `time` | TEXT (`HH:MM`) |
| `days` | TEXT (`0,2,4,5`) |
| `role_ids` | TEXT (CSV) |
| `admin_id` | INTEGER |
| `created_at` | TIMESTAMP |

`/setup` → `clear_events()` → `save_event(...)`. Активным считается последний по `created_at`.

### `participants`
| Поле | Тип |
|------|-----|
| `event_id` | INTEGER (PK part) |
| `event_date` | TEXT (PK part, ISO) |
| `user_id` | INTEGER (PK part) |
| `joined_at` | TIMESTAMP |

Дедупликация через PK `(event_id, event_date, user_id)`.

### `pending_deletes`
| Поле | Тип |
|------|-----|
| `message_id` | INTEGER (PK) |
| `channel_id` | INTEGER |
| `delete_at` | TEXT (ISO с TZ) |

Расписание автоудаления. При старте бот вызывает `restore_pending_deletes()` и доделывает все просроченные удаления.

---

## 🔧 Константы (в начале `main.py`)

```python
TZ = ZoneInfo("Europe/Moscow")
DB_PATH = "bot_config.db"
JOIN_BUTTON_ID = "uvedom_join_button"
DEFAULT_DAYS = "0,2,4,5"        # Пн, Ср, Пт, Сб
ROLE_SLOT_LIMIT = 5             # отображение [N/5] в embed
EVENT_DELETE_AFTER = 3600       # 1 час — для боевого embed
TEST_DELETE_AFTER = 300         # 5 минут — для /test
TIME_CHOICES = [f"{h:02d}:00" for h in range(12, 23)]  # 12:00…22:00
EVENT_NAME_CHOICES = ["capt"]
```

Дни недели: `0=Пн, 1=Вт, 2=Ср, 3=Чт, 4=Пт, 5=Сб, 6=Вс`.

---

## 🚀 Деплой на Railway

1. New Project → Deploy from GitHub → выбрать `temirlan029/uved`.
2. **Variables** → добавить `DISCORD_TOKEN` со значением твоего токена.
3. Railway сам прочитает `Procfile` и запустит `worker: python main.py`.
4. **⚠️ Volume.** SQLite-файл лежит в контейнере, который пересоздаётся при редеплое. Чтобы не терять `bot_config.db` (события, участники, расписание удалений) — примонтировать **Railway Volume** к директории, где лежит БД.
5. В Discord Developer Portal — **Server Members Intent** обязательно.
6. Не запускать одновременно локально и на Railway — Discord не пускает 2 сессии с одним токеном.

---

## 🐛 Troubleshooting

| Симптом | Причина / Решение |
|---------|-------------------|
| `/setup` не появляется в Discord | Бот должен синхронизировать команды (`tree.sync()` в `on_ready`). Глобальные команды могут идти до часа; перезайти в Discord помогает. |
| `MAIN [0/5]` — счётчик всегда 0 | Не включён **Server Members Intent** в Developer Portal или нет `intents.members = True` в коде. |
| Кнопка не работает после рестарта | View должен быть с `custom_id` и `timeout=None`, плюс `client.add_view(JoinButtonView())` в `on_ready`. Уже сделано. |
| `@everyone` не пингует (просто текст) | У бота нет права **Mention Everyone** в канале. |
| Сообщение не удалилось через час | У бота нет `Manage Messages` или сообщение удалили вручную (бот ловит `discord.NotFound` молча). |
| ЛС не приходит | У пользователя закрыты ЛС от незнакомцев → `discord.Forbidden`, бот логирует и идёт дальше. |
| Двойной пинг | Запущено больше одной копии бота. Убить лишние процессы. |
| После редеплоя на Railway пропали участники | Не подключён Volume → база пересоздалась. |

---

## 📜 История изменений

### Initial → готовый прод

**Найдено и пофикшено в исходном коде:**
1. ❌ `tree.sync()` не вызывался → slash-команды не появлялись в Discord. **✅ Добавлено в `on_ready`.**
2. ❌ `intents.members` не включён → `[N/5]` всегда 0. **✅ Включено + инструкция в README.**
3. ❌ `import asyncio` в самом низу файла. **✅ Перенесён в шапку.**
4. ❌ Кнопка теряла работоспособность после рестарта. **✅ `custom_id` + персистентный view.**
5. ❌ `datetime.now()` без таймзоны → расписание плыло на Railway (UTC). **✅ `ZoneInfo("Europe/Moscow")`.**
6. ❌ Кнопка только показывала эфемерное сообщение, не считала никого. **✅ Toggle + список в embed + обновление в реальном времени.**
7. ❌ Ключи `last_2h_DATE`/`last_30m_DATE` копились в БД навсегда. **✅ `cleanup_old_keys` чистит прошлые.**
8. ❌ `int(admin_id)` мог упасть на нечисловом вводе. **✅ Валидация в `/setup`.**
9. ❌ Embed и кнопка слались разными сообщениями → нельзя было отредактировать embed после клика. **✅ Объединены.**

**Новые фичи поверх ТЗ:**
- 🆕 ЛС-рассылка в точное время события — всем уникальным пользователям с упомянутыми ролями (дедупликация по `user_id`)
- 🆕 Команда `/test_dm` для проверки ЛС без ожидания
- 🆕 Автоудаление сообщений (1 час для события, 5 минут для `/test`) с таблицей `pending_deletes` и восстановлением после рестарта
- 🆕 `/setup` через UI: выпадающий список времени и event_name + RoleSelect для ролей (1–25 одним кликом)
- 🆕 `@everyone` автоматически добавляется в пинг события и `/test`

---

## 📦 Зависимости

```
discord.py        # >=2.4 для RoleSelect и autocomplete
python-dotenv     # чтение .env
```

`zoneinfo` — стандартная библиотека Python 3.9+.

---

## 🔗 Ссылки

- Репозиторий: https://github.com/temirlan029/uved
- Discord Developer Portal: https://discord.com/developers/applications
- Railway: https://railway.app
