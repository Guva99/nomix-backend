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
RUN git clone https://${GITHUB_TOKEN}@github.com/Guva99/nomix_flutter.git /app && \
    cd /app && \
    git fetch --all && \
    git reset --hard origin/main
WORKDIR /app

RUN flutter pub get && \
    flutter build web --release \
    --dart-define=FLUTTER_WEB_USE_SKIA=true \
    --no-tree-shake-icons \
    --verbose

# Этап 2: Финальный образ с FastAPI
FROM python:3.11-slim
WORKDIR /app

# Установка Python-зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальной бэкенд
COPY . .

# ⚠️ Копируем Flutter билд В ОБЩИЙ VOLUME (тот, который nginx использует)
RUN mkdir -p /frontend_build && \
    cp -r /app/frontend/build/web/* /frontend_build/

# Декларируем volume
VOLUME ["/frontend_build"]

# Лог (для отладки)
RUN ls -la /frontend_build

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
