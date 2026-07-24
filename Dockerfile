FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_NO_CACHE_DIR=1
ENV PORT=8000

RUN useradd --create-home --uid 10001 appuser

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install -r requirements.txt && python -m pip check

COPY --chown=appuser:appuser main.py maintenance.py selftest.py entrypoint.py favicon.png ./

USER appuser

RUN python selftest.py

EXPOSE 8000

CMD ["python", "entrypoint.py"]
