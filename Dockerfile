FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /code

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# Apply migrations, optionally load demo data (SEED_ON_START=true, used on hosts without a shell),
# then start the API on $PORT (set by hosts such as Render) or 8000.
# Behind a proxy, set FORWARDED_ALLOW_IPS so the rate limiter sees the real client IP.
CMD ["sh", "-c", "alembic upgrade head && if [ \"$SEED_ON_START\" = true ]; then python -m app.seed; fi && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
