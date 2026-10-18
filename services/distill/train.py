"""Distil Gemini into Gemma (Layer 5): LoRA fine-tuning on logged System One decisions.

Runs as a Cloud Run Job on one NVIDIA L4. The base model is read from the public Vertex Model
Garden bucket mounted at MODEL_DIR. The job measures agreement with Gemini on held-out decisions
before and after tuning, with the same metrics as ml/distillation/eval_agreement.py, and prints
one JSON line per result (read them from Cloud Logging).
"""

import json
import math
import os
import random
import re
import shutil
import time

import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_DIR = os.environ.get("MODEL_DIR", "/models/gemma4/gemma-4-E2B-it")
DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
EPOCHS = float(os.environ.get("EPOCHS", "1"))
LR = float(os.environ.get("LR", "2e-4"))
GRAD_ACCUM = int(os.environ.get("GRAD_ACCUM", "8"))
MAX_TRAIN = int(os.environ.get("MAX_TRAIN", "0"))  # 0 = all
EVAL_N = int(os.environ.get("EVAL_N", "300"))
LORA_R = int(os.environ.get("LORA_R", "16"))
SEED = 42


def log(event: str, **fields) -> None:
    print(json.dumps({"event": event, **fields}), flush=True)


def load(path: str) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f]


def messages(example: dict) -> list[dict]:
    return [{"role": "system", "content": example["system"]}, {"role": "user", "content": example["prompt"]}]


def target_text(example: dict) -> str:
    return json.dumps(example["answer"], ensure_ascii=False)


def prompt_text(tokenizer, example: dict) -> str:
    kwargs = {"tokenize": False, "add_generation_prompt": True}
    try:
        return tokenizer.apply_chat_template(messages(example), enable_thinking=False, **kwargs)
    except TypeError:
        return tokenizer.apply_chat_template(messages(example), **kwargs)


def favourite(probs: dict) -> str:
    return max(sorted(probs), key=lambda k: probs[k])


def normalize(raw: dict, options: list[str]) -> dict:
    clean = {}
    for o in options:
        try:
            v = float(raw.get(o, 0))
        except (TypeError, ValueError):
            v = 0.0
        clean[o] = v if math.isfinite(v) and v > 0 else 0.0
    total = sum(clean.values())
    return {o: (v / total if total else 1 / len(options)) for o, v in clean.items()}


def parse(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data.get("probabilities"), dict) else None
    except json.JSONDecodeError:
        return None


@torch.no_grad()
def evaluate(model, tokenizer, examples: list[dict], label: str) -> dict:
    model.eval()
    tokenizer.padding_side = "left"
    valid = top1 = top2 = 0
    tv = []
    started = time.time()
    for start in range(0, len(examples), 8):
        batch = examples[start:start + 8]
        enc = tokenizer([prompt_text(tokenizer, e) for e in batch], return_tensors="pt", padding=True,
                        add_special_tokens=False).to(model.device)
        out = model.generate(**enc, max_new_tokens=160, do_sample=False, pad_token_id=tokenizer.pad_token_id)
        texts = tokenizer.batch_decode(out[:, enc["input_ids"].shape[1]:], skip_special_tokens=True)
        for e, text in zip(batch, texts):
            parsed = parse(text)
            if not parsed:
                continue
            valid += 1
            mine = normalize(parsed["probabilities"], e["options"])
            teacher = normalize(e["answer"]["probabilities"], e["options"])
            top1 += favourite(mine) == favourite(teacher)
            top2 += favourite(teacher) in sorted(mine, key=lambda k: mine[k], reverse=True)[:2]
            tv.append(0.5 * sum(abs(mine[o] - teacher[o]) for o in e["options"]))
    n = len(examples)
    result = {
        "label": label, "n": n, "valid_json_rate": round(valid / n, 3),
        "top1_agreement": round(top1 / max(1, valid), 3),
        "top2_contains_gemini_favourite": round(top2 / max(1, valid), 3),
        "mean_tv_distance": round(sum(tv) / max(1, len(tv)), 3),
        "seconds": round(time.time() - started, 1),
    }
    log("eval", **result)
    return result


def local_copy(src: str, dst: str = "/tmp/model") -> str:
    """Copy the model files sequentially to local disk: reading tensors one by one through the
    bucket mount took ~30 minutes, a sequential copy takes a few."""
    started = time.time()
    os.makedirs(dst, exist_ok=True)
    for name in sorted(os.listdir(src)):
        path = os.path.join(src, name)
        if os.path.isfile(path):
            with open(path, "rb") as fin, open(os.path.join(dst, name), "wb") as fout:
                shutil.copyfileobj(fin, fout, length=64 * 1024 * 1024)
    log("model_copied", seconds=round(time.time() - started, 1))
    return dst


def load_model(model_dir: str):
    kwargs = {"dtype": torch.bfloat16, "device_map": "cuda"}
    try:
        return AutoModelForCausalLM.from_pretrained(model_dir, **kwargs)
    except (ValueError, KeyError) as exc:
        log("fallback_model_class", error=str(exc)[:200])
        from transformers import AutoModelForImageTextToText
        return AutoModelForImageTextToText.from_pretrained(model_dir, **kwargs)


def main() -> None:
    random.seed(SEED)
    torch.manual_seed(SEED)
    train = load(f"{DATA_DIR}/train.jsonl")
    test = load(f"{DATA_DIR}/test.jsonl")[:EVAL_N]
    if MAX_TRAIN:
        train = train[:MAX_TRAIN]
    log("start", model=MODEL_DIR, train=len(train), test=len(test), epochs=EPOCHS, lr=LR, lora_r=LORA_R)

    model_dir = local_copy(MODEL_DIR)
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = load_model(model_dir)
    log("model_loaded", seconds=round(time.time() - START, 1), gpu_mem_gb=round(torch.cuda.memory_allocated() / 1e9, 1))

    before = evaluate(model, tokenizer, test, "before_tuning")

    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(
        r=LORA_R, lora_alpha=2 * LORA_R, lora_dropout=0.05, task_type="CAUSAL_LM",
        # Language model attention only; the vision/audio towers are untouched.
        target_modules=r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj)",
    ))
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    log("lora_ready", trainable_params=trainable)

    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=LR)
    steps_total = math.ceil(len(train) * EPOCHS / GRAD_ACCUM)
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda s: max(0.0, 1 - s / max(1, steps_total)))
    model.train()
    tokenizer.padding_side = "right"
    order = list(range(len(train)))
    seen, step, running = 0, 0, 0.0
    end_of_turn = tokenizer.eos_token or ""
    while seen < len(train) * EPOCHS:
        random.shuffle(order)
        for idx in order:
            if seen >= len(train) * EPOCHS:
                break
            e = train[idx]
            prompt_ids = tokenizer(prompt_text(tokenizer, e), add_special_tokens=False)["input_ids"]
            answer_ids = tokenizer(target_text(e) + end_of_turn, add_special_tokens=False)["input_ids"]
            ids = torch.tensor([prompt_ids + answer_ids], device=model.device)
            labels = torch.tensor([[-100] * len(prompt_ids) + answer_ids], device=model.device)
            loss = model(input_ids=ids, labels=labels).loss / GRAD_ACCUM
            loss.backward()
            running += loss.item()
            seen += 1
            if seen % GRAD_ACCUM == 0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()
                step += 1
                if step % 25 == 0:
                    log("train", step=step, of=steps_total, loss=round(running / 25, 4),
                        elapsed_min=round((time.time() - START) / 60, 1))
                    running = 0.0

    after = evaluate(model, tokenizer, test, "after_tuning")
    log("done", before=before, after=after, total_min=round((time.time() - START) / 60, 1))


START = time.time()
if __name__ == "__main__":
    main()
