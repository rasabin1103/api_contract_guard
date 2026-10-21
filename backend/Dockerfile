FROM golang:1.27.2-alpine AS oasdiff
RUN CGO_ENABLED=0 GOBIN=/out go install -ldflags="-s -w -X github.com/oasdiff/oasdiff/build.Version=1.34.0" github.com/oasdiff/oasdiff@v1.34.0 \
    && test "$(/out/oasdiff --version)" = "oasdiff version 1.34.0"

FROM python:3.13-slim
WORKDIR /app
COPY --from=oasdiff /out/oasdiff /usr/local/bin/oasdiff
COPY third-party/oasdiff-LICENSE /usr/share/licenses/oasdiff/LICENSE
COPY backend/pyproject.toml ./
COPY backend/requirements.lock ./
COPY backend/app ./app
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-deps . && useradd --create-home guard && mkdir /app/data && chown guard /app/data
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
USER guard
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
