FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONFAULTHANDLER=1
ENV PORT=8000

RUN useradd --create-home --uid 10001 appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt

COPY main.py .
COPY maintenance.py .
COPY selftest.py .
COPY favicon.png .

RUN python selftest.py
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${Port:-${PORT:-8000}} --workers ${WebConcurrency:-${WEB_CONCURRENCY:-1}} --proxy-headers --forwarded-allow-ips \"${ForwardedAllowIps:-${FORWARDED_ALLOW_IPS:-*}}\" --timeout-keep-alive ${UvicornKeepAlive:-${UVICORN_KEEP_ALIVE:-5}} --limit-concurrency ${UvicornLimitConcurrency:-128} --backlog ${UvicornBacklog:-2048} --no-access-log --no-server-header"]
