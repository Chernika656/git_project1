# Развёртывание Facet на одном сервере

Эта конфигурация рассчитана на MVP с одним экземпляром приложения: Docker Compose,
SQLite на постоянном томе и Nginx с HTTPS. Порт Python-сервера доступен только
локально на VPS; внешний трафик принимает Nginx.

## 1. Подготовить сервер и домен

Установите Docker Engine, Docker Compose plugin, Nginx и Certbot. Направьте A/AAAA
запись домена на сервер, скопируйте каталог проекта и перейдите в него.

```bash
cp .env.production.example .env.production
chmod 600 .env.production
```

Заполните в `.env.production` публичный HTTPS-адрес, SMTP и ключ OpenAI. SMTP нужен
для подтверждения почты, приглашений и восстановления пароля. Секретный файл не
нужно добавлять в Git или отдавать веб-сервером.

Если нужно перенести существующую локальную базу, сначала остановите локальный
Facet, скопируйте каталог `data` на сервер и до первого запуска выполните:

```bash
docker volume create facet_data
docker run --rm -v facet_data:/target -v "$PWD/data:/source:ro" alpine sh -c 'cp /source/workspace.sqlite3 /target/workspace.sqlite3 && chown 10001:10001 /target/workspace.sqlite3 && chmod 600 /target/workspace.sqlite3'
```

## 2. Запустить приложение

```bash
docker compose -f deploy/compose.yaml up -d --build
docker compose -f deploy/compose.yaml ps
curl --fail http://127.0.0.1:8765/api/health
```

Данные хранятся в Docker volume `facet_data` и переживают пересборку контейнера.

## 3. Подключить HTTPS

Сначала получите сертификат Certbot для домена. Затем скопируйте
`deploy/nginx-facet.conf.example` в `/etc/nginx/sites-available/facet`, замените
`facet.example.com` на свой домен, включите конфигурацию и проверьте её:

```bash
sudo ln -s /etc/nginx/sites-available/facet /etc/nginx/sites-enabled/facet
sudo nginx -t
sudo systemctl reload nginx
```

После запуска проверьте `https://ваш-домен/api/health`, регистрацию, вход, письмо,
сохранение проекта и один запрос агента.

## 4. Резервные копии и обновление

Создать согласованную резервную копию работающей SQLite:

```bash
docker compose -f deploy/compose.yaml exec -T facet python deploy/backup.py
```

Скрипт хранит 14 последних копий в `/data/backups`. Перед обновлением сначала
сделайте копию, затем пересоберите приложение:

```bash
docker compose -f deploy/compose.yaml exec -T facet python deploy/backup.py
docker compose -f deploy/compose.yaml up -d --build
docker compose -f deploy/compose.yaml ps
```

Для восстановления остановите контейнер, замените `workspace.sqlite3` выбранной
копией внутри тома и снова запустите Compose. Не запускайте несколько контейнеров
Facet на одной SQLite-базе. Для горизонтального масштабирования сначала перенесите
данные и блокировки в PostgreSQL и внешнее хранилище файлов.

## Диагностика

```bash
docker compose -f deploy/compose.yaml logs --tail=200 facet
docker compose -f deploy/compose.yaml exec -T facet python -c "import sqlite3; print(sqlite3.connect('/data/workspace.sqlite3').execute('PRAGMA integrity_check').fetchone()[0])"
```

Ожидаемый результат проверки базы: `ok`.
