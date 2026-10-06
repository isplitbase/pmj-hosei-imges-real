FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

# Cloud Run は $PORT を注入する。シェル形式で展開させる。
# 画像生成は時間がかかるためタイムアウトを長めに取る。
CMD exec gunicorn -b :$PORT -w 2 -t 900 main:app
