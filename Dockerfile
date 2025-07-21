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

# Копируем исходный код Flutter
COPY ./frontend /app
WORKDIR /app

# Установка зависимостей и сборка
RUN flutter pub get && \
    flutter build web --release \
    --dart-define=FLUTTER_WEB_USE_SKIA=true \
    --no-tree-shake-icons \
    --verbose

# Этап 2: Бэкенд
FROM python:3.11-slim as backend

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY --from=flutter-builder /app/build/web /frontend_build

# Этап 3: Nginx
FROM nginx:1.23-alpine
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=flutter-builder /app/build/web /var/www/flutter
EXPOSE 80 443
CMD ["nginx", "-g", "daemon off;"]