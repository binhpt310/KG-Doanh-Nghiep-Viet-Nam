# Base PyTorch CUDA - image nhe (~8GB)
FROM pytorch/pytorch:2.9.0-cuda12.6-cudnn9-runtime

WORKDIR /app/kg_from_scratch

# Layer caching: install dependencies first (requirements change less often than code)
COPY kg_from_scratch/requirements-docker.txt ./requirements-docker.txt
RUN pip install --no-cache-dir -r requirements-docker.txt

# Copy application code and config files
COPY kg_from_scratch/*.py ./
COPY kg_from_scratch/templates/ ./templates/
COPY kg_from_scratch/data/ ./data/

# Use .env.docker as default .env inside the container
COPY kg_from_scratch/.env.docker ./.env

# Healthcheck: verify the Flask app is responding
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5001/')" || exit 1

EXPOSE 5001

CMD ["python", "script.py"]
