FROM python:3.11.14-slim-bookworm@sha256:65a93d69fa75478d554f4ad27c85c1e69fa184956261b4301ebaf6dbb0a3543d
ARG HTTP_PROXY
ARG HTTPS_PROXY
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.115.12 uvicorn==0.34.2 httpx==0.28.1 && useradd --uid 10003 --create-home gateway
COPY infra/model_gateway.py ./
USER gateway
CMD ["uvicorn", "model_gateway:app", "--host", "0.0.0.0", "--port", "11434", "--workers", "1", "--no-access-log"]
