# Distillation job (Layer 5): LoRA-tunes Gemma on Gemini's logged decisions on a Cloud Run L4 GPU.
FROM pytorch/pytorch:2.14.0-cuda12.6-cudnn9-runtime

# The image's Python is marked externally managed (PEP 668); installing into it is fine in a container.
ENV PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PIP_BREAK_SYSTEM_PACKAGES=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY train.py .
COPY data ./data

ENTRYPOINT ["python", "train.py"]
