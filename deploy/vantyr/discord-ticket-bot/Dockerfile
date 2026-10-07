FROM python:3.12-slim
RUN pip install --no-cache-dir "discord.py>=2.4,<3"
WORKDIR /app
COPY bot.py bot.py
CMD ["python", "-u", "bot.py"]
