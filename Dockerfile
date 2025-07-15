FROM ubuntu:22.04 as flutter-builder

RUN apt-get update && apt-get install -y \
    curl \
    git \
    unzip \
    xz-utils \
    zip \
    clang \
    cmake \
    ninja-build \
    pkg-config \
    libgtk-3-dev \
    && rm -rf /var/lib/apt/lists/*

# Установка конкретной версии Flutter с нужным Dart SDK
RUN curl -fsSL https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_3.32.6-stable.tar.xz | tar -xJ -C /opt
ENV PATH="/opt/flutter/bin:${PATH}"

# Настройка окружения
RUN git config --global --add safe.directory /opt/flutter && \
    flutter config --no-analytics && \
    flutter precache

# Проверка версий
RUN flutter --version && dart --version

# Клонирование репозитория
ARG GITHUB_TOKEN
RUN git clone https://${GITHUB_TOKEN}@github.com/Guva99/nomix_flutter.git /app
WORKDIR /app

# Очистка возможных кэшей
RUN rm -rf .dart_tool/

# Установка зависимостей
RUN flutter pub get && \
    flutter build web --release --no-sound-null-safety

# Основной образ
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app

COPY --from=flutter-builder /app/build/web /app/frontend/build/web
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]