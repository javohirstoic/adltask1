FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt gunicorn
COPY . .
RUN useradd -m -u 10001 app && mkdir -p /srv/data && chown -R app /srv/data
USER app
ENV DEBUG=0
RUN SECRET_KEY=build python manage.py collectstatic --noinput
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi --bind 0.0.0.0:8000 --workers 2 --timeout 60"]
