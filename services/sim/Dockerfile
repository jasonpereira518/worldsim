FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY worldsim worldsim
# Snapshots and places are mounted read-only (see docker-compose.yml); runs and caches live in volumes.
ENV WORLDSIM_SNAPSHOTS=/data/snapshots WORLDSIM_PLACES=/data/places.json WORLDSIM_RUNS=/state/runs \
    WORLDSIM_LLM_CACHE=/state/llm WORLDSIM_FEEDS_CACHE=/state/feeds WORLDSIM_LLM=off
EXPOSE 8731
USER nobody
CMD ["uvicorn", "worldsim.api:app", "--host", "0.0.0.0", "--port", "8731"]
