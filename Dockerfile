FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD sh -c 'echo "RAILWAY_PORT=$PORT" && gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --timeout 120 --access-logfile - --error-logfile - app:app'
