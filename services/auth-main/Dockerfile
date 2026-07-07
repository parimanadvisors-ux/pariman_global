FROM python:3.12-slim

WORKDIR /app

# Prevent Python from writing pyc files and keep stdout unbuffered for Docker logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Expose the port Nginx is routing to
EXPOSE 8000

# Use Gunicorn as the production server
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--forwarded-allow-ips", "*", "app:app"]