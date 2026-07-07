FROM python:3.12-slim

# Prevent Python from writing pyc files and keep stdout unbuffered for Docker logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install Postgres dependencies and immediately clean up apt cache
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Expose the port Nginx is routing to
EXPOSE 5000

# Use Gunicorn as the production server
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--forwarded-allow-ips", "*", "app:app"]