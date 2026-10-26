FROM python:3.11.14-slim-bookworm@sha256:65a93d69fa75478d554f4ad27c85c1e69fa184956261b4301ebaf6dbb0a3543d
ARG HTTP_PROXY
ARG HTTPS_PROXY
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 && rm -rf /var/lib/apt/lists/*
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock && useradd --uid 10001 --create-home platform && mkdir /data && chown platform:platform /data
COPY --chown=platform:platform backend/ ./
USER platform
CMD ["uvicorn", "talent_platform.api:app", "--host", "0.0.0.0", "--port", "8000"]
