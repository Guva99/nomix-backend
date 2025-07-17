FROM ubuntu:22.04 as flutter-builder

# Установка только необходимых зависимостей для web-сборки
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

# Настройка окружения и предварительное кэширование web-зависимостей
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

# Установка переменной окружения для увеличения памяти dart2js
ENV DART2JS_OPTIONS="--max-old-space-size=4096"

# Сборка с оптимизациями
RUN flutter pub get && \
    flutter build web --release \
    --dart-define=FLUTTER_WEB_USE_SKIA=true \
    --no-tree-shake-icons \
    --verbose \

RUN ls -la /app/build/web/

# Основной образ
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONPATH=/app
COPY --from=flutter-builder /app/build/web /app/frontend/build/web
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]