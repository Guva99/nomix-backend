# ───────── Этап 1: Сборка Flutter Web ─────────
FROM ubuntu:22.04 AS flutter-builder

# Системные зависимости
RUN apt-get update && apt-get install -y \
    curl git unzip xz-utils clang \
    && rm -rf /var/lib/apt/lists/*

# Установка Flutter SDK
RUN curl -fsSL https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_3.32.6-stable.tar.xz \
    | tar -xJ -C /opt
ENV PATH="/opt/flutter/bin:/opt/flutter/bin/cache/dart-sdk/bin:${PATH}"

# Подготовка web-пакета
RUN flutter config --no-analytics && flutter precache --web

# Клонирование и сборка вашего проекта
ARG GITHUB_TOKEN
ARG BUILD_VERSION=dev
RUN git clone --depth 1 --branch main \
    https://${GITHUB_TOKEN}@github.com/Guva99/nomix_flutter.git /app
WORKDIR /app
RUN flutter pub get && \
    flutter build web --release \
      --dart-define=FLUTTER_WEB_USE_SKIA=true \
      --no-tree-shake-icons

# ───────── Этап 2: Backend + FastAPI ─────────
FROM python:3.11-slim

WORKDIR /app

# Прокидываем версию и базовый URL в окружение
ARG BUILD_VERSION
ENV BUILD_VERSION=${BUILD_VERSION}
ENV WEBAPP_BASE_URL="https://mixfom2025.fvds.ru/"
ENV FLUTTER_WEB_DIR="/frontend_build"

# Устанавливаем Python-зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем backend-код
COPY . .

# Копируем собранный frontend из flutter-builder
COPY --from=flutter-builder /app/build/web ${FLUTTER_WEB_DIR}

# Открываем порт
EXPOSE 8000

# Запуск приложения
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
