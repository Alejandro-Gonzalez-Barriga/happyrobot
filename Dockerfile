FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY data/ ./data/

RUN mkdir -p /app/data

EXPOSE 8000

ENV API_KEY=hr-secret-key-2026
ENV FMCSA_API_KEY=""
ENV DB_PATH=/app/data/happyrobot.db

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
