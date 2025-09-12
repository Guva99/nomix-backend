FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir -r requirements.txt \
    && rm -rf /root/.cache/pip

COPY app ./app
COPY alembic.ini /app/alembic.ini

# >>> добавь эти строки
RUN mkdir -p /app/static/receipts /app/static/tmp \
    && adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app
# <<<

USER appuser

CMD ["gunicorn","-k","uvicorn.workers.UvicornWorker","app.main:app","-b","0.0.0.0:8000","-w","3","--timeout","60","--graceful-timeout","30"]
