FROM python:3.12-slim
RUN apt-get update && apt-get install -y libpq-dev gcc
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Flask defaults to 5000, we'll keep it that way internally
CMD ["python", "app.py"]