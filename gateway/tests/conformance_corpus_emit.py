"""Ticket #390 (rollup #349) — emit FHIR R5 corpus for validator gating.

Scope — what this emitter covers (Rule 15 A narrow, matches
termbank #363 + request.pdhc #377):

  1. `/fhir/metadata` — the CapabilityStatement itself.

Deliberately deferred — Patient / IPS Bundle / clinical resources shape
polish. Those live in gateway/app/fhir/fhir_routes.py + fhir_service.py
and haven't been validator-tested yet; a first-pass would surface real
R4→R5 drift that belongs in a separate design ticket, not this
CI landing.

Boots a self-contained Flask test app on the in-memory SQLite that
`config.TestingConfig` already selects. No external HTTP calls.

Run:  python gateway/tests/conformance_corpus_emit.py [out_dir]
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GATEWAY = os.path.dirname(HERE)
if GATEWAY not in sys.path:
    sys.path.insert(0, GATEWAY)


def _bootstrap_env() -> None:
    # config.TestingConfig uses sqlite://:memory:; nothing else to do.
    os.environ.setdefault("FLASK_ENV", "testing")
    os.environ.setdefault("SECRET_KEY", "corpus-emit-not-secret")


def _write(out_dir: str, name: str, body: dict) -> None:
    path = os.path.join(out_dir, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(body, f, indent=2, ensure_ascii=False, sort_keys=True)
    print(f"  wrote {path}")


def emit_corpus(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    _bootstrap_env()

    from app import create_app
    app = create_app("testing")
    client = app.test_client()

    print(f"Emitting FHIR R5 corpus → {out_dir}")

    # 1. CapabilityStatement.
    cs = client.get("/fhir/metadata").get_json()
    _write(out_dir, "capability_statement", cs)

    n = len([f for f in os.listdir(out_dir) if f.endswith(".json")])
    print(f"Done — {n} JSON files.")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "fhir_corpus")
    emit_corpus(out)
