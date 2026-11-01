FROM python:3.10-slim

# Отключаем создание .pyc файлов и включаем мгновенный вывод логов в stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Устанавливаем системные зависимости (если понадобятся компиляторы или sqlite3)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Копируем файл зависимостей и устанавливаем библиотеки
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем исходный код проекта
COPY src/ ./src/
COPY main.py .

# Создаем папку для сохранения базы данных
RUN mkdir -p /app/data

# Запуск бота
CMD ["python", "main.py"]
