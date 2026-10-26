FROM python:3.11.14-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MINERU_HOME=/models MINERU_CONFIG=/app/config.yaml MINERU_MODEL_SOURCE=local MINERU_MODEL_SMALL_BACKEND=onnx HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1 OMP_NUM_THREADS=4
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 fonts-noto-cjk && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY infra/mineru/requirements.txt infra/mineru/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10002 --create-home mineru && mkdir /models && chown mineru:mineru /models
COPY --chown=mineru:mineru infra/mineru/app.py infra/mineru/config.yaml ./
USER mineru
# The stateless parser SDK and mineru-kit do not use doclib telemetry.
CMD ["sh", "-c", "mineru-kit models verify --tier basic --small-backend onnx && exec uvicorn app:app --host 0.0.0.0 --port 8001 --workers 1"]
