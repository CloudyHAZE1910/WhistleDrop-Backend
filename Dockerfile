FROM python:3.12-slim

WORKDIR /app

# Only copy the requirements file first so Docker can cache the pip install layer
# and doesn't reinstall everything every time application code changes.
COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY . .

ENV WHISTLEDROP_ENV=production
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
