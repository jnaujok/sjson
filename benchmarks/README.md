# SJSON benchmarks

Scripts that compare SJSON with general-purpose compressors, binary JSON
formats, XML and EXI on realistic message streams. Every SJSON packet is
decoded and checked against the original message.

## Data

```shell
benchmarks/fetch_data.sh          # into benchmarks/data, or $SJSON_BENCH_DATA
pip install brotli zstandard msgpack cbor2
```

- **UCI v2.6** (Universal Command and Control Interface, US Air Force Open
  Arsenal public release; its messages carry `uci:version` 006.000): the
  schema drives `uci_gen.py`, which generates realistic message traffic.
- **simdjson-data**: real-world JSON (Twitter API, GitHub events, Amazon
  products, Semantic Scholar papers, and large single documents).

## Scripts

| script | what it measures |
|:--|:--|
| `uci_mixed.py` | A mixed UCI mission stream (six platforms, one sender each: position, navigation, system / service / subsystem status, capability status, entity tracks, signal reports, task and command status, notifications), with smooth or random values. Compares XML, JSON, MessagePack, per-message brotli / zstd, stream-context deflate / brotli / zstd, zstd with a trained dictionary, and SJSON with and without a schema or dictionary, stateless and in stream mode. `--sjson-only` skips the others. |
| `bench.py` | Per-message comparisons on single-type UCI streams and real-world API streams, and whole-document compression of the corpus files. |
| `xml_bench.py` | The UCI streams serialised as UCI XML. |
| `realworld.py OUT.json` | Real-world API streams in stream mode against zstd / brotli stream contexts. |
| `exi/ExiBench.java` | EXI (EXIficient 1.0.7) on the same UCI XML, schema-less and schema-informed, with and without EXI compression and lexical-value preservation. `mvn dependency:copy-dependencies -DoutputDirectory=lib`, then `javac -cp "lib/*" -d build ExiBench.java` and `java -cp "lib/*:build" ExiBench UCI.xsd DIR...` on directories of `.xml` messages (`uci_mixed.py` can write them with `xml_bench.to_xml`). |
| `export_for_cpp.py OUT_DIR` | Exports the streams, with the Python library's sizes and timings per configuration, for the C++ benchmark (IASLib's `BenchSjson`). |

Run from the repository root with the library on the path, for example
`PYTHONPATH=src:benchmarks python3 benchmarks/uci_mixed.py`.

## Results (UCI mission stream, bytes per message; times smaller than XML)

No sample-trained dictionaries:

| format | smooth motion | random values |
|:--|--:|--:|
| XML (compact) | 2,296 (1.0x) | 2,296 (1.0x) |
| JSON (minified) | 1,584 (1.45x) | 1,584 (1.45x) |
| EXI + UCI schema, per message | 326 (7.1x) | 326 (7.1x) |
| JSON + brotli-11, per message | 730 (3.1x) | 731 (3.1x) |
| SJSON + UCI schema, per message | 370 (6.2x) | 370 (6.2x) |
| JSON + zstd-19, shared stream context | 106 (21.7x) | 145 (15.8x) |
| SJSON stream mode, no setup | 102 (22.5x) | 130 (17.6x) |
| **SJSON stream mode + UCI schema** | **90 (25.4x)** | **118 (19.4x)** |

EXI with a schema keeps values but not their exact text (timestamps lose
trailing zeros, numbers are rewritten); with lexical values preserved it
takes 537 bytes. SJSON always returns the exact text.
