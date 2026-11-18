"""The UCI streams from bench.py, serialised as UCI XML instead of JSON."""

import json
import sys
import zlib
from xml.sax.saxutils import escape, quoteattr

import brotli
import zstandard

from bench import UCI_XSD, HERE, jbytes, split
from sjson.schema import load_schema
from uci_gen import UciTraffic

NS = "https://www.vdl.afrl.af.mil/programs/oam"


def lexical(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value) if not isinstance(value, float) else repr(value)


def text(value):
    return escape(lexical(value))


def element(name, value, out, root=False):
    if isinstance(value, list):  # repeated element
        for item in value:
            element(name, item, out)
        return
    ns = f' xmlns="{NS}"' if root else ""
    if not isinstance(value, dict):
        out.append(f"<{name}{ns}>{text(value)}</{name}>")
        return
    attrs = "".join(f" {k[1:]}={quoteattr(lexical(v))}" for k, v in value.items() if k.startswith("@"))
    children = [(k, v) for k, v in value.items() if not k.startswith("@") and k != "#text"]
    body = text(value["#text"]) if "#text" in value else ""
    if not children and not body:
        out.append(f"<{name}{ns}{attrs}/>")
        return
    out.append(f"<{name}{ns}{attrs}>{body}")
    for k, v in children:
        element(k, v, out)
    out.append(f"</{name}>")


def to_xml(message):
    (name, value), = message.items()
    out = ['<?xml version="1.0" encoding="UTF-8"?>']
    element(name, value, out, root=True)
    return "".join(out).encode("utf-8")


def main():
    model = load_schema(UCI_XSD)
    traffic = UciTraffic(model)
    streams = {
        "UCI Entity tracks (50 tracks x 40 updates)": traffic.track_stream("Entity", 50, 40),
        "UCI PositionReport (100 platforms x 20 updates)": traffic.track_stream("PositionReport", 100, 20),
        "UCI SystemStatus heartbeat (25 systems x 40)": traffic.track_stream("SystemStatus", 25, 40),
        "UCI mixed traffic (300 message types x 4)": traffic.mixed_stream(300, 4),
    }
    zc = zstandard.ZstdCompressor(level=19)
    rows = []
    for name, messages in streams.items():
        train, test = split(messages)
        xml_test = [to_xml(m) for m in test]
        samples = [to_xml(m) for m in train]
        dictionary = zstandard.train_dictionary(32768, samples)
        zd = zstandard.ZstdCompressor(level=19, dict_data=dictionary)
        rows.append({
            "name": name,
            "messages": len(test),
            "json_bytes": sum(len(jbytes(m)) for m in test),
            "xml_bytes": sum(map(len, xml_test)),
            "xml+deflate-9": sum(len(zlib.compress(x, 9)) for x in xml_test),
            "xml+brotli-11": sum(len(brotli.compress(x, quality=11)) for x in xml_test),
            "xml+zstd-19": sum(len(zc.compress(x)) for x in xml_test),
            "xml+zstd-19+dict": sum(len(zd.compress(x)) for x in xml_test),
            "sample_xml": xml_test[0][:1500].decode(),
        })
        print(name, file=sys.stderr)
    (HERE / "xml_results.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
