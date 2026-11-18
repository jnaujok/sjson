"""SJSON vs general-purpose compressors on real and UCI message streams."""

import json
import logging
import os
import statistics
import sys
import time
import zlib
from pathlib import Path

import brotli
import cbor2
import msgpack
import zstandard

from sjson.compile import compile_dictionary
from sjson.schema import load_schema
from sjson.sjson import SJSON
from uci_gen import UciTraffic

logging.disable(logging.CRITICAL)
HERE = Path(__file__).resolve().parent
# Downloaded data (see fetch_data.sh); override with SJSON_BENCH_DATA.
EXT = Path(os.environ.get("SJSON_BENCH_DATA", HERE / "data"))
CORPUS = EXT / "simdjson-data" / "jsonexamples"
UCI_XSD = EXT / "uci-schema" / "UCI_MessageDefinitions_v2_6_0.xsd"


def jbytes(doc):
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# ---------------------------------------------------------------- codecs ----

def per_message(fn, test):
    return sum(len(fn(m)) for m in test)


def zstd_dict(train, test, size=32768):
    samples = [jbytes(m) for m in train]
    try:
        dictionary = zstandard.train_dictionary(min(size, max(1024, sum(map(len, samples)) // 4)), samples)
    except zstandard.ZstdError:
        return None, 0
    compressor = zstandard.ZstdCompressor(level=19, dict_data=dictionary)
    total = sum(len(compressor.compress(jbytes(m))) for m in test)
    return total, len(dictionary.as_bytes())


def sjson_run(test, train=(), sender_kwargs=None, receiver_setup=None):
    """Total packet bytes for ``test`` (after warming on ``train``), verified."""
    sender = SJSON(sender_id=1, **(sender_kwargs or {}))
    receiver = SJSON(sender_id=2)
    if receiver_setup:
        receiver_setup(receiver)
    for message in train:  # steady state: sender's dictionary is warm
        sender.to_binary(message)
    receiver.load_dictionary(sender.nak_dictionary(1, receiver.last_known_tag(1),
                                                   receiver.last_known_value(1)))
    total = 0
    schema_encoded = 0
    start = time.perf_counter()
    packets = [sender.to_binary(m) for m in test]
    encode_seconds = time.perf_counter() - start
    nak_bytes = 0
    for message, packet in zip(test, packets):
        total += len(packet.tobytes())
        schema_encoded += bool(SJSON.read_header(packet).flags & SJSON.FLAG_SCHEMA_ENCODED)
        try:
            decoded = receiver.to_value(packet)
        except KeyError:
            update = sender.nak_dictionary(1, receiver.last_known_tag(1),
                                           receiver.last_known_value(1))
            nak_bytes += len(update.tobytes())
            receiver.load_dictionary(update)
            decoded = receiver.to_value(packet)
        assert decoded == message, "round trip failed"
    return {
        "bytes": total,
        "nak_bytes": nak_bytes,
        "schema_encoded": schema_encoded,
        "msgs_per_s": len(test) / encode_seconds if encode_seconds else 0,
        "dictionary_bytes": len(sender.nak_dictionary(1, 0, 0).tobytes()),
    }


def compressed_dictionary_size(dictionary):
    return len(zlib.compress(json.dumps(dictionary.to_dict()).encode(), 9))


# -------------------------------------------------------------- datasets ----

def load_streams(uci_model):
    traffic = UciTraffic(uci_model)
    streams = {}
    streams["UCI Entity tracks (50 tracks x 40 updates)"] = (
        traffic.track_stream("Entity", 50, 40), "uci")
    streams["UCI PositionReport (100 platforms x 20 updates)"] = (
        traffic.track_stream("PositionReport", 100, 20), "uci")
    streams["UCI SystemStatus heartbeat (25 systems x 40)"] = (
        traffic.track_stream("SystemStatus", 25, 40), "uci")
    streams["UCI mixed traffic (300 message types x 4)"] = (
        traffic.mixed_stream(300, 4), "uci")

    twitter = json.loads((CORPUS / "twitter.json").read_text())["statuses"]
    streams["Twitter API statuses (real, 100)"] = (twitter, None)
    events = json.loads((CORPUS / "github_events.json").read_text())
    streams["GitHub events API (real, 30)"] = (events, None)
    rows = [json.loads(line) for line in (CORPUS / "amazon_cellphones.ndjson").read_text().splitlines() if line.strip()]
    header, rows = rows[0], rows[1:]
    streams["Amazon product records (real, 792)"] = ([dict(zip(header, r)) for r in rows], None)
    papers = json.loads((CORPUS / "semanticscholar-corpus.json").read_text())[:2000]
    streams["Semantic Scholar papers (real, 2000)"] = (papers, None)
    return streams


def split(messages):
    half = len(messages) // 2
    return messages[:half], messages[half:]


# ------------------------------------------------------------------ main ----

def bench_stream(name, messages, kind, uci_model):
    train, test = split(messages)
    raw = per_message(jbytes, test)
    row = {"name": name, "messages": len(test), "json_bytes": raw,
           "avg_json": raw / len(test)}
    row["deflate-9"] = per_message(lambda m: zlib.compress(jbytes(m), 9), test)
    row["brotli-11"] = per_message(lambda m: brotli.compress(jbytes(m), quality=11), test)
    zc = zstandard.ZstdCompressor(level=19)
    row["zstd-19"] = per_message(lambda m: zc.compress(jbytes(m)), test)
    row["zstd-19+dict"], row["zstd_dict_size"] = zstd_dict(train, test)
    row["msgpack"] = per_message(msgpack.packb, test)
    row["cbor"] = per_message(cbor2.dumps, test)

    dyn = sjson_run(test, train)
    row["sjson-dynamic"] = dyn["bytes"]
    row["sjson_dynamic_dict"] = dyn["dictionary_bytes"]
    row["sjson_speed"] = dyn["msgs_per_s"]

    compiled = compile_dictionary(samples=train, intern_min_count=3)
    res = sjson_run(test, (), {"dictionary": compiled},
                    lambda r: r.register_dictionary(compiled))
    row["sjson-compiled"] = res["bytes"]
    row["sjson_compiled_dict"] = compressed_dictionary_size(compiled)

    if kind == "uci":
        res = sjson_run(test, (), {"schema": uci_model, "schema_encoding": False},
                        lambda r: r.register_schema(uci_model))
        row["sjson-schema-dict"] = res["bytes"]
        res = sjson_run(test, (), {"schema": uci_model},
                        lambda r: r.register_schema(uci_model))
        row["sjson-schema-encoded"] = res["bytes"]
        row["schema_encoded_share"] = res["schema_encoded"] / len(test)
        tuned = compile_dictionary(uci_model, samples=train, intern_min_count=3)
        res = sjson_run(test, (), {"dictionary": tuned},
                        lambda r: r.register_dictionary(tuned))
        row["sjson-schema+samples"] = res["bytes"]
        row["schema_samples_share"] = res["schema_encoded"] / len(test)
    return row


def bench_document(path):
    doc = json.loads(path.read_text())
    raw = jbytes(doc)
    row = {"name": path.name, "json_bytes": len(raw)}
    row["deflate-9"] = len(zlib.compress(raw, 9))
    row["brotli-11"] = len(brotli.compress(raw, quality=11))
    row["zstd-19"] = len(zstandard.ZstdCompressor(level=19).compress(raw))
    row["msgpack"] = len(msgpack.packb(doc))
    sender = SJSON(sender_id=1)
    start = time.perf_counter()
    packet = sender.to_binary(doc)
    row["sjson_seconds"] = time.perf_counter() - start
    assert sender.to_value(packet) == doc
    row["sjson"] = len(packet.tobytes())
    row["sjson_dict"] = len(sender.nak_dictionary(1, 0, 0).tobytes())
    sj = packet.tobytes()
    row["sjson+zstd"] = len(zstandard.ZstdCompressor(level=19).compress(sj))
    return row


def main():
    start = time.time()
    uci_model = load_schema(UCI_XSD)
    print(f"UCI schema loaded: {len(uci_model.root.properties)} messages, "
          f"{len(uci_model.field_names())} names, {len(uci_model.enum_strings())} enum strings",
          file=sys.stderr)
    results = {"streams": [], "documents": []}
    for name, (messages, kind) in load_streams(uci_model).items():
        t = time.time()
        results["streams"].append(bench_stream(name, messages, kind, uci_model))
        print(f"{name}: {time.time() - t:.0f}s", file=sys.stderr)
    for doc in ["twitter.json", "github_events.json", "citm_catalog.json", "canada.json",
                "update-center.json", "instruments.json", "apache_builds.json", "mesh.json"]:
        t = time.time()
        results["documents"].append(bench_document(CORPUS / doc))
        print(f"{doc}: {time.time() - t:.0f}s", file=sys.stderr)
    out = HERE / "results.json"
    out.write_text(json.dumps(results, indent=1))
    print(f"done in {time.time() - start:.0f}s -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
