FROM python:3.12-alpine
WORKDIR /app
COPY *.py ./
COPY static ./static
COPY content ./content
RUN addgroup -S app && adduser -S app -G app && mkdir -p /data && chown -R app:app /app /data
USER app
ENV PORT=3000 DB_PATH=/data/cfa.sqlite3 PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/health')" || exit 1
CMD ["python","server.py"]
