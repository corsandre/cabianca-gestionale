FROM python:3.11-slim

WORKDIR /app

# pango/harfbuzz/fonts-dejavu: per WeasyPrint (PDF delle etichette del modulo Prodotti)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev openssl tzdata \
    tesseract-ocr tesseract-ocr-ita poppler-utils \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 fonts-dejavu-core && \
    rm -rf /var/lib/apt/lists/*

ENV TZ=Europe/Rome

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data /app/backups /app/app/static/uploads

EXPOSE 8080

# Il comando cambia per container (docker-compose.yml): web = gunicorn, servizi = python -m app.servizi,
# impianto = python -m app.services.impianto.servizio. Cosa fa ciascuno lo decide RUOLO (app/ruoli.py).
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:create_app()"]
