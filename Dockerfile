FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY topology ./topology
ENTRYPOINT ["python", "-m", "synthgen"]
