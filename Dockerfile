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

# Установка Flutter
RUN curl -fsSL https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_3.22.0-stable.tar.xz | tar -xJ -C /opt
ENV PATH="/opt/flutter/bin:${PATH}"

# Решаем проблему с безопасностью Git
RUN git config --global --add safe.directory /opt/flutter

# Клонирование приватного репозитория
ARG GITHUB_TOKEN
RUN git clone https://${GITHUB_TOKEN}@github.com/Guva99/nomix_flutter.git /app
WORKDIR /app
RUN flutter pub get
RUN flutter build web --release --no-sound-null-safety

# Основной образ
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app

# Копируем собранный фронтенд
COPY --from=flutter-builder /app/build/web /app/frontend/build/web

# Устанавливаем зависимости бекенда
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальные файлы
COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]