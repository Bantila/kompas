# Деплой «Компаса»

Два сценария: чистый сервер с нуля и обновление уже поднятого стенда.
Специфика MAX — регистрация мини-приложения и подписка на вебхук — общая для
обоих и вынесена в конец.

Подробности каждой команды (флаги, почему именно так) — в README.md,
раздел «Деплой на сервер». Здесь только последовательность действий.

---

## Сценарий А: чистый сервер

Проверялось на Ubuntu 22.04, VPS без предустановленного софта.

### 1. Подготовка

```bash
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh
```

Веб-сервер и Certbot на хост не ставятся: HTTPS обслуживает Caddy в Docker Compose.

### 2. Защита сервера

```bash
adduser deployer
usermod -aG sudo deployer
# на локальной машине: ssh-copy-id deployer@ваш_сервер
```

В `/etc/ssh/sshd_config`:

```
PermitRootLogin no
PasswordAuthentication no
```

```bash
systemctl restart ssh
apt install ufw -y
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw enable
apt install fail2ban -y && systemctl enable --now fail2ban
apt install unattended-upgrades -y && dpkg-reconfigure --priority=low unattended-upgrades
```

Не закрывайте текущую SSH-сессию, пока не убедитесь, что вход под `deployer`
работает — иначе можно остаться без доступа к серверу.

### 3. Исходники и переменные окружения

```bash
mkdir -p /opt && cd /opt
git clone https://github.com/Bantila/kompas.git
cd kompas
cp .env.example .env
```

Сгенерировать секреты:

```bash
openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c 32   # POSTGRES_PASSWORD
openssl rand -hex 64                                        # JWT_SECRET
openssl rand -hex 32                                        # MAX_WEBHOOK_SECRET
```

Заполнить `.env`:

| Переменная | Что вставить |
|---|---|
| `POSTGRES_PASSWORD` | сгенерированный пароль базы |
| `JWT_SECRET` | сгенерированная строка для подписи токенов |
| `GIGACHAT_CREDENTIALS` | Authorization key из личного кабинета developers.sber.ru (необязательно — без него подбор идёт rule-based) |
| `MAX_BOT_TOKEN` | токен бота MAX |
| `MAX_BOT_USERNAME` | имя бота без `@` |
| `MAX_WEBHOOK_SECRET` | сгенерированный секрет вебхука |
| `APP_PUBLIC_URL` | адрес мини-приложения, с `https://` |

### 4. Запуск с HTTPS

Направьте DNS домена на IP сервера, затем:

```bash
echo "DOMAIN=example.ru" >> .env
docker compose -f docker-compose.yml -f docker-compose.ssl.yml up -d --build
```

Caddy сам получит сертификат и будет его продлевать. Миграции Django
накатываются автоматически при старте контейнера.

Доступ в панель администрирования `/admin/` — задайте в `.env`
`DJANGO_SUPERUSER_PASSWORD` до первого запуска (администратор заведётся сам)
или выполните `docker compose exec backend python manage.py createsuperuser`.

Проверить:

```bash
docker compose ps
docker compose logs -f
curl https://example.ru/health
# {"status":"ok","database":"ok"}
```

Дальше — общий для обоих сценариев раздел «Специфика MAX» ниже.

---

## Сценарий Б: обновление стенда

Для уже поднятого сервера, где нужно подтянуть свежую версию из `main`.

> **Стенд на версии до перехода на Django.** Схема базы у Django-версии создаётся
> заново и со старой базой не совместима: поднимите новую базу (новый том
> PostgreSQL или отдельную базу). Не удаляйте том с данными, пока не
> убедились, что они больше не нужны, — `docker compose down -v` стирает
> их безвозвратно.

```bash
cd /opt/kompas   # путь к исходникам на сервере
git fetch origin
git checkout main
git pull origin main
```

Дописать в `.env` новые переменные, если их там ещё нет
(`MAX_BOT_TOKEN`, `MAX_BOT_USERNAME` — секция «Чат-бот» в `.env.example`
показывает актуальный список; `TELEGRAM_*` можно оставить пустыми или убрать):

```bash
grep -q '^MAX_BOT_TOKEN=' .env || echo 'MAX_BOT_TOKEN=' >> .env
grep -q '^MAX_BOT_USERNAME=' .env || echo 'MAX_BOT_USERNAME=' >> .env
# впишите значения руками — токен в чат не годится, редактируйте .env на сервере
```

Пересобрать и перезапустить:

```bash
docker compose -f docker-compose.yml -f docker-compose.ssl.yml up -d --build
```

Миграции Django (если появились новые) накатятся сами при старте контейнера.
Проверить:

```bash
docker compose ps
docker compose logs -f backend
curl https://<домен>/health
# {"status":"ok","database":"ok"}
```

Дальше — раздел «Специфика MAX» ниже; для уже настроенного Telegram-бота
ничего менять не нужно, он продолжит работать как отладочный адаптер, если
его токен остался в `.env`.

---

## Специфика MAX (общее для обоих сценариев)

### 1. Мини-приложение — вручную в кабинете

MAX не даёт прописать URL мини-приложения через API. Впишите его один раз:

1. Откройте **MAX для партнёров** → Чат-боты → ваш бот → **⋮ → Настройки**.
2. В поле URL мини-приложения вставьте `https://<ваш домен>`.
3. Выберите вид кнопки открытия — Открыть, Старт, Играть или без названия.
4. Сохраните.

Требования к URL: только `https://`, латиница/цифры/точка/дефис, до 1024
символов, без пробелов.

> Платформа MAX (боты, мини-приложения) доступна юрлицам, ИП и самозанятым —
> резидентам РФ. Верификация профиля в кабинете партнёра нужна до того, как
> мини-приложением смогут пользоваться посторонние.

### 2. Подписка на вебхук

```bash
docker compose exec backend python -m app.setup_bot --webhook https://<ваш домен>
```

Команда подписывает MAX на `POST /api/bot/max` (и, если задан
`TELEGRAM_BOT_TOKEN`, заодно настраивает вебхук Telegram) и печатает
результат каждой подписки.

### 3. Проверка

```bash
curl https://<ваш домен>/health
# {"status":"ok","database":"ok"}
```

Затем откройте чат с ботом в MAX и нажмите «Начать» — должно прийти
приветствие с кнопкой мини-приложения. Открытие кнопки должно сразу
авторизовать (без запроса кода привязки) — это проверяет, что initData
дошла и подпись сошлась.

Если бот не отвечает: `docker compose logs -f backend` — вебхук MAX всегда
отвечает 200 и гасит ошибки внутри себя, поэтому по HTTP-статусу проблему не
увидеть, только по логам.

### 4. Локальная отладка без вебхука

Если нужно проверить бота без публичного адреса — см. README.md, раздел
«Отладка бота на своей машине» (`cloudflared` + `python -m app.poll_bot
--platform max`).
