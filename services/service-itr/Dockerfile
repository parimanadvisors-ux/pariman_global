FROM python:3.12-slim
# We need these for Postgres
RUN apt-get update && apt-get install -y libpq-dev gcc
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "app.py"]