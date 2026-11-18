import json, sys, zlib, brotli, zstandard
import bench, uci_mixed
from sjson.compile import compile_dictionary
C = bench.CORPUS
def streams():
    tw = json.loads((C / "twitter.json").read_text())["statuses"]
    ev = json.loads((C / "github_events.json").read_text())
    rows = [json.loads(l) for l in (C / "amazon_cellphones.ndjson").read_text().splitlines() if l.strip()]
    am = [dict(zip(rows[0], r)) for r in rows[1:]]
    pa = json.loads((C / "semanticscholar-corpus.json").read_text())[:2000]
    return {"Twitter statuses": tw, "GitHub events": ev, "Amazon products": am, "Semantic Scholar papers": pa}
out = {}
for name, data in streams().items():
    train, test_m = data[: len(data) // 2], data[len(data) // 2 :]
    test = [("a", m) for m in test_m]
    j = [bench.jbytes(m) for m in test_m]; jt = [bench.jbytes(m) for m in train]
    n = len(j)
    try:
        d = zstandard.train_dictionary(min(65536, max(4096, sum(map(len, jt)) // 4)), jt)
    except zstandard.ZstdError:
        d = None
    row = {"JSON": sum(map(len, j)),
           "brotli-11 per message": sum(len(brotli.compress(x, quality=11)) for x in j),
           "zstd-19 stream": uci_mixed.stream_zstd(test, j),
           "brotli stream": uci_mixed.stream_brotli(test, j)}
    if d is not None:
        zd = zstandard.ZstdCompressor(level=19, dict_data=d)
        row["zstd-19 + dict per message"] = sum(len(zd.compress(x)) for x in j)
        row["zstd-19 + dict stream"] = uci_mixed.stream_zstd(test, j, d)
    comp = compile_dictionary(samples=train, intern_min_count=3)
    for label, kw, setup in (("SJSON learnt", {}, None),
                             ("SJSON learnt, stream", {"stateful": True}, None),
                             ("SJSON + samples dict", {"dictionary": comp}, lambda r: r.register_dictionary(comp)),
                             ("SJSON + samples dict, stream", {"dictionary": comp, "stateful": True}, lambda r: r.register_dictionary(comp))):
        row[label] = uci_mixed.sjson_stream(test, kw, setup)["total"]
    out[name] = {"n": n, "rows": row}
    print(name, n, file=sys.stderr)
    for k, v in row.items():
        print(f"  {k:32s} {v / n:8.0f} B/msg {100 * v / row['JSON']:6.1f}%", file=sys.stderr)
(bench.HERE / sys.argv[1]).write_text(json.dumps(out, indent=1))
