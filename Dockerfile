# Assistant API image (stdlib only). Runs as a non-root user on port 8080.
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY harrowgate/ harrowgate/
COPY data/faq.json data/faq.json
RUN useradd --create-home --uid 10001 app
USER 10001
EXPOSE 8080
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz')"
CMD ["python", "-m", "harrowgate", "serve", "--port", "8080"]
