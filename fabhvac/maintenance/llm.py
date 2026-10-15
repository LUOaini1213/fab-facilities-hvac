"""Optional zero-shot labelling of work-order text with a local model served by Ollama.

The model only chooses labels from a fixed list (JSON output constrained by a schema with an
enum); anything else is treated as ABSTAIN. It never produces numbers: every metric is
computed by fabhvac.maintenance.textclass from its labels. Nothing is sent off the machine.

Texts are sent in batches: one request holds up to `batch_size` numbered descriptions and the
reply must be an array of exactly that many labels, in order. A reply of the wrong length
makes the whole batch ABSTAIN. (Batching matters when the server unloads the model after every
request, which makes each request pay the model-load time.) Caution: with 3-4B models a batch
reply of the right length can still drift out of order -- in scripts/maint_llm.py batched answers
were much less accurate than one-per-request answers on the same texts. Use batch_size=1 for
any number that matters.
"""

from __future__ import annotations

import json
import urllib.request

from .textclass import ABSTAIN

DEFAULT_HOST = "http://localhost:11434"


def _codes(labels, definitions):
    return "\n".join(f"- {lab}: {definitions[lab]}" if definitions and lab in definitions else f"- {lab}"
                     for lab in labels)


def build_request(text: str, labels, model: str, definitions: dict | None = None) -> dict:
    """One description -> {"label": <code>}."""
    prompt = ("You are coding facility maintenance work orders. Choose the ONE problem code that "
              "best describes the work-order text.\nCodes:\n" + _codes(labels, definitions) +
              f"\n\nWork-order text: {text!r}\nAnswer with JSON: {{\"label\": <code>}}")
    schema = {"type": "object", "properties": {"label": {"type": "string", "enum": list(labels)}},
              "required": ["label"]}
    return {"model": model, "prompt": prompt, "stream": False, "format": schema, "keep_alive": "2m",
            "options": {"temperature": 0, "seed": 0, "num_predict": 40}}


def build_batch_request(texts, labels, model: str, definitions: dict | None = None) -> dict:
    """Several descriptions -> {"labels": [<code>, ...]} with exactly len(texts) entries."""
    items = "\n".join(f"{i + 1}. {t!r}" for i, t in enumerate(texts))
    prompt = ("You are coding facility maintenance work orders. For EACH numbered work-order text, "
              "choose the ONE problem code that best describes it.\nCodes:\n" + _codes(labels, definitions) +
              f"\n\nWork-order texts:\n{items}\n\nAnswer with JSON: {{\"labels\": [...]}} containing exactly "
              f"{len(texts)} codes, in the same order as the texts.")
    n = len(texts)
    schema = {"type": "object",
              "properties": {"labels": {"type": "array", "items": {"type": "string", "enum": list(labels)},
                                        "minItems": n, "maxItems": n}},
              "required": ["labels"]}
    return {"model": model, "prompt": prompt, "stream": False, "format": schema, "keep_alive": "2m",
            "options": {"temperature": 0, "seed": 0, "num_predict": 24 * n + 40, "num_ctx": 8192}}


def parse_label(raw: str, labels) -> str:
    """Label from the model's JSON reply; ABSTAIN if it is not valid JSON or not a known code."""
    try:
        lab = json.loads(raw).get("label")
    except (ValueError, AttributeError):
        return ABSTAIN
    return lab if isinstance(lab, str) and lab in set(labels) else ABSTAIN


def parse_batch(raw: str, labels, n: int) -> list:
    """n labels from a batch reply; unknown codes -> ABSTAIN; wrong length -> all ABSTAIN."""
    try:
        labs = json.loads(raw).get("labels")
    except (ValueError, AttributeError):
        return [ABSTAIN] * n
    if not isinstance(labs, list) or len(labs) != n:
        return [ABSTAIN] * n
    ok = set(labels)
    return [x if isinstance(x, str) and x in ok else ABSTAIN for x in labs]


def available(host: str = DEFAULT_HOST, timeout: float = 3.0) -> list:
    """Names of locally installed models, or [] if no server answers."""
    try:
        with urllib.request.urlopen(host + "/api/tags", timeout=timeout) as r:
            return [m["name"] for m in json.load(r).get("models", [])]
    except OSError:
        return []


def _post(host: str, body: dict, timeout: float) -> str:
    req = urllib.request.Request(host + "/api/generate", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r).get("response", "")


def classify(texts, labels, model: str, host: str = DEFAULT_HOST, definitions: dict | None = None,
             batch_size: int = 25, timeout: float = 600.0) -> list:
    texts = list(texts)
    out = []
    for i in range(0, len(texts), batch_size):
        chunk = texts[i:i + batch_size]
        if len(chunk) == 1:
            out.append(parse_label(_post(host, build_request(chunk[0], labels, model, definitions), timeout), labels))
        else:
            raw = _post(host, build_batch_request(chunk, labels, model, definitions), timeout)
            out.extend(parse_batch(raw, labels, len(chunk)))
    return out
