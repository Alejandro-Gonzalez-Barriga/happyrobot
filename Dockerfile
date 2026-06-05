FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app and data
COPY app/ ./app/
COPY data/ ./data/

# Expose port
EXPOSE 8000

# Environment defaults (override at runtime)
ENV API_KEY=hr-secret-key-2026
ENV FMCSA_API_KEY=""

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
