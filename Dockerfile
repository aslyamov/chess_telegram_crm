# Используем официальный легкий образ Python
FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Отключаем создание .pyc файлов и включаем буферизацию логов
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Устанавливаем зависимости для сборки (если понадобятся)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Копируем файл зависимостей
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код приложения
COPY app/ ./app/
# Копируем скрипты (опционально)
COPY scripts/ ./scripts/

# Создаем папку для данных (если не используем Secret Manager для ключа)
RUN mkdir -p data

# Открываем порт 8080 (стандарт для Cloud Run)
EXPOSE 8080

# Команда для запуска приложения через uvicorn с поддержкой динамического порта
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
