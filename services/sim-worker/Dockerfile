FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GCP_PROJECT_ID=ebc-cloud-dev-03 \
    GCP_REGION=asia-southeast2 \
    FIRESTORE_DATABASE=shadow-city

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

COPY sim_worker/ ./sim_worker/

ENTRYPOINT ["python", "-m", "sim_worker.main"]

