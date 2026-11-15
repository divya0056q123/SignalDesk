FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/app/data/logs.db

WORKDIR /app
COPY backend/requirements.txt backend/requirements-postgres.txt /app/backend/
RUN pip install --no-cache-dir -r /app/backend/requirements.txt -r /app/backend/requirements-postgres.txt
COPY backend/app /app/backend/app
COPY sample-data /app/sample-data
RUN mkdir -p /app/data
WORKDIR /app/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
