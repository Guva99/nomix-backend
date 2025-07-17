# Этап 1: Сборка Flutter-проекта
FROM ubuntu:22.04 as flutter-builder

# Установка зависимостей для Flutter
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

# Настройка окружения Flutter
RUN git config --global --add safe.directory /opt/flutter && \
    flutter config --no-analytics && \
    flutter precache --web

# Клонирование репозитория с Flutter-проектом
ARG GITHUB_TOKEN
RUN git clone https://${GITHUB_TOKEN}@github.com/Guva99/nomix_flutter.git /app && \
    cd /app && \
    git fetch --all && \
    git reset --hard origin/main
WORKDIR /app

# Сборка Flutter-проекта
RUN flutter pub get && \
    flutter build web --release \
    --dart-define=FLUTTER_WEB_USE_SKIA=true \
    --no-tree-shake-icons \
    --verbose

# Этап 2: Финальный образ с FastAPI
FROM python:3.11-slim
WORKDIR /app

# Копируем собранный Flutter-проект
COPY --from=flutter-builder /app/build/web /app/frontend/build/web

# Установка Python-зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальные файлы проекта
COPY . .

# Создаем директорию, если не существует (для надежности)
RUN mkdir -p /app/frontend/build/web

RUN ls -la /app/frontend/build/web

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]