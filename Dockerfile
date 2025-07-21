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
ARG  CACHE_BUST=2025-07-19

RUN git clone --depth 1 --branch main \
    https://${GITHUB_TOKEN}@github.com/Guva99/nomix_flutter.git /app && \
    cd /app && \
    git fetch --depth 1 origin main && \
    git reset --hard FETCH_HEAD
WORKDIR /app

RUN flutter pub get && \
    flutter build web \
    --release \
    --base-href="/" \
    --dart-define=BUILD_TIMESTAMP=$(date +%s) \
    --dart-define=APP_VERSION=1.0.4 \
    --pwa-strategy=offline-first \
    --source-maps

# Этап 2: Финальный образ с FastAPI
FROM python:3.11-slim
WORKDIR /app

# Установка Python-зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем backend
COPY . .

# Копируем собранный frontend из flutter-builder этапа
COPY --from=flutter-builder /app/build/web /frontend_build
RUN ls -la /frontend_build && \
    [ -f /frontend_build/index.html ] || { echo "Error: index.html not found"; exit 1; }


# Лог для проверки
RUN ls -la /frontend_build
RUN grep -q "Telegram Web App SDK" /var/www/flutter/index.html || { \
    echo "Telegram scripts missing in index.html"; exit 1; }


# Декларируем volume (тот что nginx использует)
VOLUME ["/frontend_build"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
