# One Parley agent per container (Maritime agent box). Set PARTICIPANT_ID per deployment.
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY core ./core
COPY agent ./agent
COPY scenarios ./scenarios
ENV AGENT_DATA_DIR=/data PORT=8080
CMD ["sh", "-c", "uvicorn agent.service:app --host 0.0.0.0 --port ${PORT}"]
