"""
A realistic mixed UCI mission stream, compressed with and without a
precompiled dictionary.

Six platforms on one network for 90 simulated seconds. Each platform has one
SystemID, fixed security markings (U // USA) and LIVE mode on every message,
and sends at typical rates:

  PositionReport 1 Hz, NavigationReport 0.5 Hz, SystemStatus every 5 s,
  3 x ServiceStatus every 10 s, 4 x SubsystemStatus every 10 s,
  2 capability-status messages every 15 s, StoreManagementReport every 30 s,
  and random TaskStatus / ActionCommandStatus / OperatorNotification /
  ServiceErrorReport events.
  Three sensor platforms also report 8 tracks each as Entity at 1 Hz, and two
  ESM platforms report 3 emitters each as SignalReport every 2 s.

Messages are sent in time order, interleaved across platforms. The first 45 s
train the dictionary-based methods; the last 45 s are measured. Stateful
methods (stream compressors, SJSON's learnt dictionary) start cold at the
start of the measured half, and SJSON's dictionary-update (NAK) traffic is
counted in its totals.
"""

import datetime
import json
import random
import sys
import time
import uuid
import zlib

import brotli
import msgpack
import zstandard

from bench import HERE, UCI_XSD, jbytes
from sjson.compile import compile_dictionary
from sjson.schema import load_schema
from sjson.sjson import SJSON
from uci_gen import EPOCH, Shape
from xml_bench import to_xml

OPTIONAL_P = (1, 0.45, 0.3, 0.2, 0.1, 0.0)
SMOOTH = [True]
MISSION_ID = "6f9619ff-8b86-4011-b42d-00c04fc964ff"
SECURITY = {"Classification": "U", "OwnerProducer": [{"GovernmentIdentifier": "USA"}]}
CAPABILITIES = ["ESM_CapabilityStatus", "SMTI_CapabilityStatus", "AMTI_CapabilityStatus",
                "SAR_CapabilityStatus", "IFF_CapabilityStatus", "NavigationCapabilityStatus",
                "CommTerminalCapabilityStatus", "StoreCarriageCapabilityStatus"]
EVENTS = [("TaskStatus", 0.08), ("ActionCommandStatus", 0.05),
          ("OperatorNotification", 0.01), ("ServiceErrorReport", 0.005)]


class Source:
    """One sender of one message type (e.g. a platform's 2nd service)."""

    def __init__(self, model, message, platform, seed):
        self.message = message
        self.platform = platform
        self.shape = Shape(None, model.root.properties[message].type, seed, OPTIONAL_P)
        self.shape.smooth = SMOOTH[0]

    def render(self, rng, when):
        body = self.shape.render(rng, when)
        if "SecurityInformation" in body:
            body["SecurityInformation"] = SECURITY
        header = body.get("MessageHeader")
        if isinstance(header, dict):
            header["SystemID"] = {"UUID": self.platform["uuid"]}
            header["Mode"] = "LIVE"
            if "MissionID" in header:
                header["MissionID"] = {"UUID": MISSION_ID}
            header["Timestamp"] = when.strftime("%Y-%m-%dT%H:%M:%S.") + \
                f"{when.microsecond // 1000:03d}Z"
        data = body.get("MessageData")
        if isinstance(data, dict) and isinstance(data.get("SystemID"), dict):
            data["SystemID"]["UUID"] = self.platform["uuid"]
        return {self.message: body}


def mission(model, platforms=6, seconds=90, seed=11, smooth=True):
    SMOOTH[0] = smooth
    rng = random.Random(seed)
    schedule = []  # (period seconds, phase, source)
    seeds = iter(range(seed * 10000, seed * 10000 + 100000))
    fleet = []
    for p in range(platforms):
        platform = {"uuid": str(uuid.UUID(int=rng.getrandbits(128), version=4))}
        fleet.append(platform)

        def add(message, period, phase=0.0):
            schedule.append((period, phase, Source(model, message, platform, next(seeds))))

        add("PositionReport", 1, rng.random())
        add("NavigationReport", 2, rng.random() * 2)
        add("SystemStatus", 5, rng.random() * 5)
        for _ in range(3):
            add("ServiceStatus", 10, rng.random() * 10)
        for _ in range(4):
            add("SubsystemStatus", 10, rng.random() * 10)
        for name in rng.sample(CAPABILITIES, 2):
            add(name, 15, rng.random() * 15)
        add("StoreManagementReport", 30, rng.random() * 30)
        if p < 3:
            for _ in range(8):
                add("Entity", 1, rng.random())
        if p in (1, 4):
            for _ in range(3):
                add("SignalReport", 2, rng.random() * 2)
    event_sources = [(Source(model, name, fleet[p], next(seeds)), rate)
                     for p in range(platforms) for name, rate in EVENTS]

    timeline = []
    for period, phase, source in schedule:
        t = phase
        while t < seconds:
            timeline.append((t, source))
            t += period
    for source, rate in event_sources:
        for second in range(seconds):
            if rng.random() < rate:
                timeline.append((second + rng.random(), source))
    timeline.sort(key=lambda item: item[0])
    values = random.Random(seed + 1)
    messages = []
    for t, source in timeline:
        when = EPOCH + datetime.timedelta(seconds=t)
        messages.append((t, source.platform["uuid"], source.render(values, when)))
    return messages


# ------------------------------------------------------------ measuring ----

def grouped(test, payloads):
    groups = {}
    for (platform, _), payload in zip(test, payloads):
        groups.setdefault(platform, []).append(payload)
    return groups.values()


def stream_deflate(test, payloads):
    """WebSocket permessage-deflate with context takeover, one link per platform."""
    total = 0
    for group in grouped(test, payloads):
        c = zlib.compressobj(9, zlib.DEFLATED, -15, 9)
        total += sum(len(c.compress(p) + c.flush(zlib.Z_SYNC_FLUSH)) - 4 for p in group)
    return total


def stream_zstd(test, payloads, dict_data=None):
    total = 0
    for group in grouped(test, payloads):
        c = zstandard.ZstdCompressor(level=19, dict_data=dict_data).compressobj()
        for p in group:
            total += len(c.compress(p)) + len(c.flush(zstandard.COMPRESSOBJ_FLUSH_BLOCK))
    return total


def stream_brotli(test, payloads):
    total = 0
    for group in grouped(test, payloads):
        c = brotli.Compressor(quality=11)
        total += sum(len(c.process(p) + c.flush()) for p in group)
    return total


def per_message(fn, payloads):
    return sum(len(fn(p)) for p in payloads)


def zstd_dictionary(train_payloads):
    return zstandard.train_dictionary(65536, train_payloads)


def sjson_stream(test, sender_kwargs=None, setup=None):
    """One sender per platform, one receiver; cold start; every packet
    decoded and checked; NAK traffic counted."""
    platforms = {}
    receiver = SJSON(sender_id=0xFFFF)
    if setup:
        setup(receiver)
    packets = nak = encoded = 0
    start = time.perf_counter()
    for platform, message in test:
        if platform not in platforms:
            platforms[platform] = SJSON(sender_id=len(platforms) + 1, **(sender_kwargs or {}))
        sender = platforms[platform]
        sid = sender.get_sender_id()
        packet = sender.to_binary(message)
        packets += len(packet.tobytes())
        encoded += bool(SJSON.read_header(packet).flags & SJSON.FLAG_SCHEMA_ENCODED)
        try:
            value = receiver.to_value(packet)
        except KeyError:
            update = sender.nak_dictionary(sid, receiver.last_known_tag(sid),
                                           receiver.last_known_value(sid))
            nak += len(update.tobytes())
            receiver.load_dictionary(update)
            value = receiver.to_value(packet)
        assert value == message
    return {"packets": packets, "nak": nak, "total": packets + nak,
            "schema_encoded": encoded / len(test),
            "seconds": time.perf_counter() - start}


SJSON_CONFIGS = {}  # label -> (needs, kwargs builder); extended by later rounds


def run(model, smooth, sjson_only=False, extra=None):
    messages = mission(model, smooth=smooth)
    half = 45.0
    train = [m for t, p, m in messages if t < half]
    test = [(p, m) for t, p, m in messages if t >= half]
    plain = [m for _, m in test]
    rows = {}
    j_test = [jbytes(m) for m in plain]
    rows["JSON (minified)"] = sum(map(len, j_test))
    if not sjson_only:
        j_train = [jbytes(m) for m in train]
        x_test = [to_xml(m) for m in plain]
        x_train = [to_xml(m) for m in train]
        zc = zstandard.ZstdCompressor(level=19)
        jd, xd = zstd_dictionary(j_train), zstd_dictionary(x_train)
        zj = zstandard.ZstdCompressor(level=19, dict_data=jd)
        zx = zstandard.ZstdCompressor(level=19, dict_data=xd)
        rows["XML"] = sum(map(len, x_test))
        rows["MessagePack"] = per_message(msgpack.packb, plain)
        for label, payloads in (("XML", x_test), ("JSON", j_test)):
            rows[f"{label} + brotli-11 per message"] = per_message(lambda p: brotli.compress(p, quality=11), payloads)
            rows[f"{label} + zstd-19 per message"] = per_message(zc.compress, payloads)
            rows[f"{label} + deflate stream (WebSocket)"] = stream_deflate(test, payloads)
            rows[f"{label} + brotli stream"] = stream_brotli(test, payloads)
            rows[f"{label} + zstd-19 stream"] = stream_zstd(test, payloads)
        rows["XML + zstd-19 + 64 KB dict, per message"] = per_message(zx.compress, x_test)
        rows["JSON + zstd-19 + 64 KB dict, per message"] = per_message(zj.compress, j_test)
        rows["JSON + zstd-19 + 64 KB dict, stream"] = stream_zstd(test, j_test, jd)
    detail = {}
    configs = {
        "SJSON, learnt dictionary": ({}, None),
        "SJSON + UCI schema": ({"schema": model}, lambda r: r.register_schema(model)),
    }
    compiled = compile_dictionary(samples=train, intern_min_count=3)
    configs["SJSON + dict from samples"] = ({"dictionary": compiled}, lambda r: r.register_dictionary(compiled))
    tuned = compile_dictionary(model, samples=train, intern_min_count=3, **(extra or {}).get("compile", {}))
    configs["SJSON + dict from schema + samples"] = ({"dictionary": tuned}, lambda r: r.register_dictionary(tuned))
    for label, (kwargs, setup) in list(configs.items()):
        for variant, more in (extra or {}).get("variants", {}).items():
            configs[f"{label}, {variant}"] = ({**kwargs, **more}, setup)
    for label, (kwargs, setup) in configs.items():
        result = sjson_stream(test, kwargs, setup)
        rows[label] = result["total"]
        detail[label] = result
        print(f"  {label}: {result['total'] / len(test):.0f} B/msg", file=sys.stderr, flush=True)
    sizes = {"SJSON samples dict (gz)": len(zlib.compress(json.dumps(compiled.to_dict()).encode(), 9)),
             "SJSON schema+samples dict (gz)": len(zlib.compress(json.dumps(tuned.to_dict()).encode(), 9))}
    return {"test_messages": len(test), "rows": rows, "detail": detail, "sizes": sizes}


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sjson-only", action="store_true")
    parser.add_argument("--out", default="uci_mixed_results.json")
    parser.add_argument("--extra", default="{}", help="JSON: compile options and variants")
    args = parser.parse_args()
    model = load_schema(UCI_XSD)
    extra = json.loads(args.extra)
    out = {}
    for smooth in (True, False):
        label = "smooth kinematics" if smooth else "random values"
        print(label, file=sys.stderr)
        out[label] = run(model, smooth, args.sjson_only, extra)
    (HERE / args.out).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
