FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app

# Копируем зависимости первыми для кэширования
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Затем копируем остальные файлы
COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]