# syntax=docker/dockerfile:1

FROM docker:27.5.1-cli

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN apk upgrade --no-cache && \
    apk add --no-cache python3 py3-pip

COPY bot/requirements.txt /app/bot/requirements.txt
RUN python3 -m pip install --break-system-packages --root-user-action=ignore --no-cache-dir \
    -r /app/bot/requirements.txt

COPY bot /app/bot

ENTRYPOINT ["python3", "/app/bot/telegram_bot.py"]
