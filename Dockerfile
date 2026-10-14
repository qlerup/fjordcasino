FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --create-home casino \
    && mkdir /data && chown casino:casino /data
COPY --chown=casino:casino app.py hub_email.py db.py games.py wsgi.py poker_engine.py poker_service.py ./
COPY --chown=casino:casino static ./static
COPY --chown=casino:casino templates ./templates
USER casino
EXPOSE 8080
CMD ["python", "wsgi.py"]
