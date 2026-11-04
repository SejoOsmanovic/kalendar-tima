FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN SECRET_KEY=build-only POSTGRES_PASSWORD=build-only python manage.py collectstatic --noinput
USER 65534:65534
CMD ["sh","-c","python manage.py migrate --noinput && exec gunicorn tim.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --access-logfile -"]
