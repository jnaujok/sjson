"""
Exports the benchmark streams as JSON for the C++ benchmark, with the Python
library's results for each configuration (bytes and time), so the two can be
compared side by side.

    python3 export_for_cpp.py OUT_DIR
"""
import json, sys, time
from pathlib import Path

import bench, uci_mixed
from sjson.compile import compile_dictionary
from sjson.schema import load_schema
from sjson.sjson import SJSON

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)


def python_run(test, kwargs, setup):
    """Same as uci_mixed.sjson_stream, timing encode and decode separately."""
    platforms, receiver = {}, SJSON(sender_id=0xFFFF)
    if setup:
        setup(receiver)
    packets = nak = 0
    encode_s = decode_s = 0.0
    for platform, message in test:
        if platform not in platforms:
            platforms[platform] = SJSON(sender_id=len(platforms) + 1, **kwargs)
        sender = platforms[platform]
        sid = sender.get_sender_id()
        t = time.perf_counter(); packet = sender.to_binary(message); encode_s += time.perf_counter() - t
        packets += len(packet.tobytes())
        t = time.perf_counter()
        try:
            value = receiver.to_value(packet, sender_id=sid)
        except KeyError:
            update = sender.nak_dictionary(sid, receiver.last_known_tag(sid), receiver.last_known_value(sid))
            nak += len(update.tobytes())
            receiver.load_dictionary(update)
            value = receiver.to_value(packet, sender_id=sid)
        decode_s += time.perf_counter() - t
        assert value == message
    return {"bytes": packets + nak, "nak": nak, "encode_s": encode_s, "decode_s": decode_s}


def export(name, test, configs, extra_files=None):
    results = {}
    for label, (kwargs, setup) in configs.items():
        results[label] = python_run(test, kwargs, setup)
        r = results[label]
        print(f"  {label:40s} {r['bytes'] / len(test):8.1f} B/msg  enc {1e6 * r['encode_s'] / len(test):8.0f} us  dec {1e6 * r['decode_s'] / len(test):8.0f} us", flush=True)
    data = {"name": name, "messages": [[p, m] for p, m in test], "python": results,
            "json_bytes": sum(len(bench.jbytes(m)) for _, m in test)}
    data.update(extra_files or {})
    (OUT / f"{name}.json").write_text(json.dumps(data))


model = load_schema(bench.UCI_XSD)
for smooth in (True, False):
    label = "uci_smooth" if smooth else "uci_random"
    print(label, flush=True)
    msgs = uci_mixed.mission(model, smooth=smooth)
    train = [m for t, p, m in msgs if t < 45]
    test = [(p, m) for t, p, m in msgs if t >= 45]
    samples = compile_dictionary(samples=train, intern_min_count=3)
    samples.save(OUT / f"{label}_samples.sdj")
    reg = lambda r: r.register_schema(model)
    configs = {
        "learnt": ({}, None),
        "learnt, stream": ({"stateful": True}, None),
        "schema": ({"schema": model}, reg),
        "schema, stream": ({"schema": model, "stateful": True}, reg),
        "samples dict": ({"dictionary": samples}, lambda r: r.register_dictionary(samples)),
        "samples dict, stream": ({"dictionary": samples, "stateful": True}, lambda r: r.register_dictionary(samples)),
    }
    export(label, test, configs, {"samples_dictionary": f"{label}_samples.sdj"})

C = bench.CORPUS
rows = [json.loads(l) for l in (C / "amazon_cellphones.ndjson").read_text().splitlines() if l.strip()]
real = {
    "twitter": json.loads((C / "twitter.json").read_text())["statuses"],
    "github": json.loads((C / "github_events.json").read_text()),
    "amazon": [dict(zip(rows[0], r)) for r in rows[1:]],
    "papers": json.loads((C / "semanticscholar-corpus.json").read_text())[:2000],
}
for name, data in real.items():
    print(name, flush=True)
    test = [("a", m) for m in data[len(data) // 2:]]
    export(name, test, {"learnt": ({}, None), "learnt, stream": ({"stateful": True}, None)})
