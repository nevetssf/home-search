FROM python:3.12-slim

WORKDIR /app

# System deps kept minimal; Pillow needs zlib/jpeg at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libjpeg62-turbo zlib1g sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# /app/data holds the SQLite db + media volume (see docker-compose).
RUN mkdir -p /app/data/media

EXPOSE 8000

# Apply migrations, then serve.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
