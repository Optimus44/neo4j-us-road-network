FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Dash runs on port 8050 by default
EXPOSE 8050

CMD ["python", "app.py"]