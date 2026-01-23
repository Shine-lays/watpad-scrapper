FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for curl_cffi
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Use 1 worker to ensure we stay under 512MB RAM
CMD ["gunicorn", "--worker-class", "sync", "-w", "1", "-b", "0.0.0.0:5000", "--timeout", "120", "app:app"]
