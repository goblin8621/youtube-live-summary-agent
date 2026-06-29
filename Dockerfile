FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.12-slim

WORKDIR /app

# non-root 사용자
RUN groupadd -r agent && useradd -r -g agent agent

# 패키지 복사
COPY --from=builder /install /usr/local

# 앱 소스 복사
COPY --chown=agent:agent . .

# 데이터·리포트 디렉터리 (볼륨 마운트 대상)
RUN mkdir -p data reports && chown -R agent:agent data reports

USER agent

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/channels')" || exit 1

CMD ["python", "main.py"]
