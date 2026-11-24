FROM python:3.13-slim-bookworm

# LibreOffice (DOCX -> PDF) + its Python UNO bridge for refreshing the table of contents
RUN apt-get update \
 && apt-get install -y --no-install-recommends libreoffice-writer-nogui python3-uno fonts-crosextra-carlito fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 UNO_PYTHON=/usr/bin/python3 LIBREOFFICE_BINARY=soffice
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN DJANGO_SECRET_KEY=build python manage.py collectstatic --noinput -v0

EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn portal.wsgi -b 0.0.0.0:8000 --workers 2 --threads 4 --timeout 300"]
