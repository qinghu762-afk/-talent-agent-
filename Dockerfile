FROM python:3.11.14-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY pyproject.toml ./
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock && useradd --uid 10001 --create-home talent && mkdir /data && chown talent:talent /data
COPY backend ./backend
RUN pip install --no-cache-dir --no-deps --no-build-isolation .
USER talent
CMD ["uvicorn", "talent.api:app", "--host", "0.0.0.0", "--port", "8000"]
