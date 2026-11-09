FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/

ENV ADMIN_PASSWORD=admin123
# Порт 7860 — стандарт Hugging Face Spaces; локально можно переопределить: -e PORT=8000
ENV PORT=7860
EXPOSE 7860

WORKDIR /app/backend
CMD ["python", "app.py"]
