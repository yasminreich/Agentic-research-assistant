# Container image for the Research Assistant web app.
# Works on Render, Railway, Fly, or any host that injects a $PORT (run.py honors it).
FROM python:3.11-slim

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code.
COPY app/ ./app/
COPY run.py .

# Render/Railway set $PORT; default to 8000 for local `docker run`.
ENV HOST=0.0.0.0 PORT=8000
EXPOSE 8000

CMD ["python", "run.py"]
