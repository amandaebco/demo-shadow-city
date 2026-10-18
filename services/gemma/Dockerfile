# Gemma for System One (Layer 5): Ollama serving Gemma on a Cloud Run GPU.
# Models are baked into the image so a cold start does not download them.
FROM ollama/ollama:0.35.1

ENV OLLAMA_HOST=0.0.0.0:8080 \
    OLLAMA_MODELS=/models \
    OLLAMA_KEEP_ALIVE=-1 \
    OLLAMA_NUM_PARALLEL=4 \
    OLLAMA_DEBUG=false

# Gemma 4 edge models (e2b is the smallest, CONTRACT.md §10.3; e4b the main candidate),
# plus Gemma 3 4B for comparison. The one used is chosen by measured agreement with Gemini.
RUN ollama serve & sleep 5 && ollama pull gemma4:e2b && ollama pull gemma4:e4b && ollama pull gemma3:4b

ENTRYPOINT ["ollama", "serve"]
