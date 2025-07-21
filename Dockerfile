# Этап 1: Сборка Flutter-проекта
FROM ubuntu:22.04 as flutter-builder

RUN apt-get update && apt-get install -y \
    curl \
    git \
    unzip \
    xz-utils \
    clang \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_3.32.6-stable.tar.xz | tar -xJ -C /opt
ENV PATH="/opt/flutter/bin:${PATH}"

RUN git config --global --add safe.directory /opt/flutter && \
    flutter config --no-analytics && \
    flutter precache --web

ARG GITHUB_TOKEN
ARG CACHE_BUST=2025-07-19

RUN git clone --depth 1 --branch main \
    https://${GITHUB_TOKEN}@github.com/Guva99/nomix_flutter.git /app && \
    cd /app && \
    git fetch --depth 1 origin main && \
    git reset --hard FETCH_HEAD
WORKDIR /app

# Увеличиваем кэш для зависимостей
ENV PUB_CACHE="/tmp/flutter/.pub-cache"
RUN mkdir -p ${PUB_CACHE} && \
    flutter pub get && \
    flutter build web --release \
    --dart-define=FLUTTER_WEB_USE_SKIA=true \
    --no-tree-shake-icons \
    --dart-define=FLUTTER_WEB_CANVASKIT_URL=/canvaskit/ \
    --verbose

# Оптимизация ассетов
RUN find /app/build/web -type f -name "*.js" -exec gzip -k {} \; && \
    find /app/build/web -type f -name "*.css" -exec gzip -k {} \; && \
    find /app/build/web -type f -name "*.html" -exec gzip -k {} \;

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

# Копируем собранный frontend из flutter-builder этапа
COPY --from=flutter-builder /app/build/web /frontend_build

# Этап 3: Финальная сборка
FROM nginx:1.23-alpine

# Копируем конфиг nginx
COPY nginx.conf /etc/nginx/nginx.conf

# Копируем статику из бэкенда
COPY --from=backend /frontend_build /var/www/flutter

# Создаем директорию для кэша nginx
RUN mkdir -p /var/cache/nginx

EXPOSE 80 443

CMD ["nginx", "-g", "daemon off;"]