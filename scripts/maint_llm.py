"""Part D (optional): zero-shot labelling of a fixed test sample with local models via Ollama.

Reads <NYC_AMPS_DIR>/textclass_test_predictions.parquet (written by scripts/maint_run.py),
draws 50 test orders per label (seed fixed before any LLM output was seen), asks each model
for one label from the fixed list, ONE description per request, and compares with the rule
baseline and the trained model on the same sample. The models return labels only; all
numbers are computed here, with 95 % Wilson intervals because the sample is small.

An earlier version sent 25 descriptions per request; its scores (~0.33) measured answers
drifting out of order rather than the models and are no longer reported.
Skips (exit 0, nothing written) when no Ollama server answers.

Output: results/maintenance_textclass_llm.json
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fabhvac.maintenance import amps, llm, textclass as tc  # noqa: E402
from fabhvac.results_io import write_json  # noqa: E402

RES = Path(os.environ.get("FABHVAC_RESULTS_DIR", ROOT / "results"))
MODELS = ["qwen2.5:3b", "gemma3:4b"]     # chosen before running: small instruction models already installed
PER_LABEL = 50
SEED = 20261002
LABELS = list(amps.MEP_MODES)
DEFINITIONS = {
    "Leaking": "water or another fluid escapes from a pipe, fixture, roof or equipment",
    "Clogged": "a drain, toilet, urinal, sink or pipe is blocked or backs up",
    "No Water": "a fixture, fountain, shower or system delivers no water or too little pressure, or water must be turned on",
    "Will not turn off": "a fixture or device keeps running and cannot be stopped (running toilet, faucet, fountain)",
    "Not working electrical": "an electrical device, outlet, circuit, fan, motor or appliance does not work",
    "No Light": "lights or bulbs are out or lighting does not work",
    "No Heat": "heating, boiler, furnace or radiators do not work or a space is cold",
}


def summarise(y, pred) -> dict:
    r = tc.scores(y, pred, LABELS)
    k = int(np.sum(np.asarray(y, dtype=object) == np.asarray(pred, dtype=object)))
    out = {kk: vv for kk, vv in r.items() if kk != "per_class"}
    out["correct"] = k
    out["accuracy_ci95_wilson"] = list(tc.wilson_ci(k, len(y)))
    out["per_class_f1"] = {c: r["per_class"][c]["f1"] for c in LABELS}
    return out


def main() -> int:
    have = llm.available()
    models = [m for m in MODELS if m in have]
    if not models:
        print("no Ollama server or none of the models installed; nothing written")
        return 0
    p = pd.read_parquet(Path(os.environ["NYC_AMPS_DIR"]) / "textclass_test_predictions.parquet")
    rng = np.random.default_rng(SEED)
    idx = []
    for lab in LABELS:
        cand = np.flatnonzero(p["label"].to_numpy() == lab)
        idx.extend(sorted(rng.choice(cand, size=min(PER_LABEL, cand.size), replace=False).tolist()))
    s = p.iloc[rng.permutation(np.array(idx))].reset_index(drop=True)
    y = s["label"].to_numpy()
    ml = s["ml"].to_numpy()
    out = {"sample": {"per_label": PER_LABEL, "n": int(len(s)), "seed": SEED,
                      "from": "test period (created >= 2024-01-01), stratified by true label"},
           "protocol": "one description per request, temperature 0, label constrained to the 7 codes by a JSON schema",
           "note": "stratified sample: accuracy here weights every label equally and is not comparable with "
                   "the full-test accuracy in maintenance_textclass.json; intervals are 95 % Wilson intervals",
           "rules": summarise(y, s["rules"].to_numpy()),
           "ml": summarise(y, ml), "llm": {}}
    for m in models:
        t0 = time.time()
        labels, errors = [], 0
        for text in s["description"].tolist():
            for attempt in range(3):
                try:
                    labels.extend(llm.classify([text], LABELS, m, definitions=DEFINITIONS, batch_size=1))
                    break
                except OSError:          # server closed the connection / timed out: retry, then give up
                    time.sleep(5)
            else:
                labels.append(tc.ABSTAIN)
                errors += 1
        if errors == len(labels):
            print(f"{m}: every request failed; not reported", flush=True)
            continue
        pred = np.array(labels, dtype=object)
        r = summarise(y, pred)
        r["seconds"] = time.time() - t0
        r["request_errors_counted_as_abstain"] = errors
        r["invalid_or_abstained"] = int(np.sum(pred == tc.ABSTAIN))
        r["agreement_with_ml"] = float(np.mean(pred == ml))
        # paired comparison with the trained model on the same orders: discordant pairs
        r["vs_ml"] = {"llm_right_ml_wrong": int(np.sum((pred == y) & (ml != y))),
                      "ml_right_llm_wrong": int(np.sum((ml == y) & (pred != y)))}
        out["llm"][m] = r
        print(f"{m}: acc {r['accuracy']:.3f} {r['accuracy_ci95_wilson']} macroF1 {r['macro_f1']:.3f} "
              f"errors {errors} ({r['seconds']:.0f}s)", flush=True)
        write_json(RES / "maintenance_textclass_llm.json", out)      # after each model: keep partial results
    if not out["llm"]:
        print("no model produced labels; nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
