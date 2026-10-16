FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FASTEMBED_CACHE_PATH=/opt/models

WORKDIR /app
COPY pyproject.toml ./
COPY reliefnet ./reliefnet
RUN pip install ".[embed]"
# Bake the multilingual embedding model into the image so workers start offline and fast.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

EXPOSE 8000
CMD ["uvicorn", "reliefnet.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
