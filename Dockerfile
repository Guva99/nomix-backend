FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app

# Устанавливаем необходимые зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Клонируем репозиторий с фронтендом
RUN git clone https://github.com/Guva99/nomix_flutter /app/frontend

# Устанавливаем зависимости для Flutter
RUN apt-get update && apt-get install -y \
    curl \
    git \
    unzip \
    xz-utils \
    zip

# Устанавливаем Flutter
RUN curl -fsSL https://storage.googleapis.com/download.flutter.io/flutter_linux_v3.7.9-stable.tar.xz | tar -xzC /opt
ENV PATH="/opt/flutter/bin:${PATH}"

# Собираем Flutter проект
WORKDIR /app/frontend
RUN flutter doctor
RUN flutter build web --release

# Копируем собранные файлы в папку для статики
WORKDIR /app
COPY --from=flutter-build /app/frontend/build/web /app/frontend/static

# Копируем основной бэкенд код
COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
