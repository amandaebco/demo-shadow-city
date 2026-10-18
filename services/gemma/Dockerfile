# Gemma for System One (Layer 5): Ollama serving Gemma 3 on a Cloud Run GPU.
# Models are baked into the image so a cold start does not download them.
FROM ollama/ollama:0.35.1

ENV OLLAMA_HOST=0.0.0.0:8080 \
    OLLAMA_MODELS=/models \
    OLLAMA_KEEP_ALIVE=-1 \
    OLLAMA_NUM_PARALLEL=4 \
    OLLAMA_DEBUG=false

# Smallest instruction-tuned Gemma 3 (CONTRACT.md §10.3) plus 4B for comparison.
RUN ollama serve & sleep 5 && ollama pull gemma3:1b && ollama pull gemma3:4b

ENTRYPOINT ["ollama", "serve"]
