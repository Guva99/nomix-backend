# Шаг 1: Строим Flutter
FROM ubuntu:22.04 as flutter-builder

# Установка зависимостей
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

# Настройка окружения
RUN git config --global --add safe.directory /opt/flutter && \
    flutter config --no-analytics && \
    flutter precache --web

# Проверка версий
RUN flutter --version && dart --version

# Клонирование репозитория
ARG GITHUB_TOKEN
RUN git clone https://${GITHUB_TOKEN}@github.com/Guva99/nomix_flutter.git /app
WORKDIR /app

# Очистка кэшей
RUN rm -rf .dart_tool/ && \
    flutter clean

# Установка зависимостей и сборка
RUN flutter pub get
RUN flutter build web --release \
    --dart-define=FLUTTER_WEB_USE_SKIA=true \
    --no-tree-shake-icons \
    --verbose
RUN ls -la /app/build/web/

# Шаг 2: Основной образ для Backend (FastAPI)
FROM python:3.11-slim
WORKDIR /app

# Копируем из предыдущего контейнера с билдом Flutter
COPY --from=flutter-builder /app/build/web /app/frontend/build/web

# Установка зависимостей для Backend
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
