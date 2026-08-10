FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
# Install base package + snmp optional group (provides snmpsim-command-responder
# used by the snmpsim Deployment; other generator pods pay a small install cost
# but the image stays a single artifact).
RUN pip install --no-cache-dir ".[snmp]"
COPY topology ./topology
# Pre-rendered snmpsim data files (one .snmprec per device, translate.yaml).
# Re-generate with: .venv/bin/python snmp/generator/render.py
COPY snmp/data ./snmp/data
ENTRYPOINT ["python", "-m", "synthgen"]
