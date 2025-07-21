# Этап 1: Сборка Flutter-проекта
FROM ubuntu:22.04 as flutter-builder

# Установка зависимостей с очисткой кэша
RUN apt-get update && apt-get install -y \
    curl \
    git \
    unzip \
    xz-utils \
    clang \
    && rm -rf /var/lib/apt/lists/*

# Установка Flutter
RUN curl -fsSL https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_3.32.6-stable.tar.xz | tar -xJ -C /opt
ENV PATH="/opt/flutter/bin:${PATH}"

# Настройка Flutter
RUN flutter config --no-analytics && \
    flutter precache --web

# Клонирование репозитория с кэшированием
ARG GITHUB_TOKEN
ARG CACHE_BUST=2025-07-21
RUN git clone --depth 1 --branch main \
    https://${GITHUB_TOKEN}@github.com/Guva99/nomix_flutter.git /app && \
    cd /app && \
    git fetch --depth 1 origin main && \
    git reset --hard FETCH_HEAD

WORKDIR /app

# Сборка с версионированием
RUN flutter pub get && \
    flutter build web \
    --release \
    --base-href="/" \
    --dart-define=BUILD_TIMESTAMP=$(date +%s) \
    --dart-define=APP_VERSION=1.0.4 \
    --pwa-strategy=offline-first \
    --source-maps

# Этап 2: Финальный образ с FastAPI
FROM python:3.11-slim as backend

WORKDIR /app

# Установка зависимостей с кэшированием
COPY requirements.txt .
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем только нужные файлы для бэкенда
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini .

# Копируем собранный frontend
COPY --from=flutter-builder /app/build/web /frontend_build

# Проверка содержимого frontend
RUN ls -la /frontend_build && \
    [ -f /frontend_build/index.html ] || { echo "Error: index.html not found"; exit 1; }

# Этап 3: Финальная сборка Nginx
FROM nginx:1.23-alpine

# Копируем конфиг nginx
COPY nginx.conf /etc/nginx/nginx.conf

# Копируем статику из бэкенда
COPY --from=backend /frontend_build /var/www/flutter

# Создаем директорию для кэша nginx
RUN mkdir -p /var/cache/nginx && \
    chown -R nginx:nginx /var/www/flutter && \
    chmod -R 755 /var/www/flutter

# Проверка версии frontend
RUN grep -q "Telegram Web App SDK" /var/www/flutter/index.html || { \
    echo "Telegram scripts missing in index.html"; exit 1; }

EXPOSE 80 443

CMD ["nginx", "-g", "daemon off;"]