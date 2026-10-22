FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY puls ./puls
COPY web ./web
COPY run.py .
RUN useradd -m -u 10001 app && mkdir -p /srv/data && chown -R app /srv/data
USER app
EXPOSE 8000
CMD ["python", "-u", "run.py"]
