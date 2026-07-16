FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

COPY pyproject.toml ./
COPY src ./src

RUN python -m pip install --no-cache-dir .

EXPOSE 8765

CMD ["python", "-m", "agent_scheduler.main", "--host", "0.0.0.0", "--port", "8765"]
