# Use the official Playwright image (this includes the OS libraries you were missing)
FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

WORKDIR /app

# Copy and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install the browser binaries
RUN playwright install chromium

COPY . .

# Match your Flask port
EXPOSE 5000

# Run with Gunicorn
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "app:app"]
