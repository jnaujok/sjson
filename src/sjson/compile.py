# Copyright (C) 2025 HarvestWave, LLC.
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA

"""
Compile a dictionary ahead of time.

A compiled dictionary is a small JSON file holding the field names and
interned values (in id order) and, when built from a schema, the compiled
schema itself. Both peers load the file instead of parsing the schema, and
schema-driven encoding still works.

Sample documents improve the result: names are numbered by how often they
occur, so the most frequent fields get the 5-bit ids, and strings that repeat
often can be interned.

Command line::

    python -m sjson.compile --schema order.schema.json -o order.dict.json
    python -m sjson.compile --sample traffic.jsonl --intern-min-count 5 -o d.json
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence

from sjson.tag_dictionary import TagDictionary


def _count(
    document: Any, names: Counter[str], strings: Counter[str], first: dict[str, int]
) -> None:
    stack = [document]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                names[key] += 1
                first.setdefault(key, len(first))
                stack.append(child)
        elif isinstance(value, list):
            stack.extend(value)
        elif isinstance(value, str):
            strings[value] += 1
            first.setdefault("\0" + value, len(first))


def compile_dictionary(
    schema: Any = None,
    samples: Iterable[Any] = (),
    intern_min_count: int | None = None,
    max_value_length: int = 64,
    text_dictionary_size: int = 0,
    **schema_options: Any,
) -> TagDictionary:
    """
    Build a dictionary from a schema and/or sample documents.

    Args:
        schema: Optional JSON Schema / XSD path, parsed JSON Schema, or
            ``SchemaModel``. Its names, enumerated values and type model are
            included.
        samples: Representative documents. Field names are ordered by how
            often they occur in them (most frequent first); names only the
            schema knows follow in schema order.
        intern_min_count: If given, sample strings that occur at least this
            many times (and are at most ``max_value_length`` characters long)
            are added to the interned values.
        text_dictionary_size: Opt-in. With samples, also train a zstd
            dictionary of about this many bytes (e.g. 16384) on the samples'
            longer strings, used by the text channel. It only helps traffic
            that resembles the samples, so it is off (0) by default.
        schema_options: Passed to the XSD loader.
    """
    from sjson.schema import load_schema

    model = None if schema is None else load_schema(schema, **schema_options)
    schema_names = [] if model is None else model.field_names()
    schema_values = [] if model is None else model.enum_strings()

    names: Counter[str] = Counter()
    strings: Counter[str] = Counter()
    first: dict[str, int] = {}
    samples = list(samples)
    for document in samples:
        _count(document, names, strings, first)

    def ranked(candidates: Iterable[str], counts: Counter[str], key: Any) -> list[str]:
        order = {name: index for index, name in enumerate(dict.fromkeys(candidates))}
        return sorted(order, key=lambda n: (-counts[n], key(n, order[n])))

    schema_rank = {name: index for index, name in enumerate(schema_names)}
    tag_list = ranked(
        [*schema_names, *names],
        names,
        lambda n, i: (0, schema_rank[n]) if n in schema_rank else (1, first[n]),
    )

    value_candidates = list(schema_values)
    if intern_min_count is not None:
        value_candidates += [
            value
            for value, count in strings.items()
            if count >= intern_min_count and len(value) <= max_value_length
        ]
    value_rank = {value: index for index, value in enumerate(schema_values)}
    value_list = ranked(
        value_candidates,
        strings,
        lambda v, i: ((0, value_rank[v]) if v in value_rank else (1, first["\0" + v])),
    )
    text_dictionary = None
    if text_dictionary_size and samples:
        text_dictionary = _train_text_dictionary(samples, text_dictionary_size)
    return TagDictionary.from_names(tag_list, value_list, model, text_dictionary)


def _packet_text(document: Any) -> bytes:
    """The strings of a document that would travel in the text channel."""
    from sjson.string_node import StringNode

    parts: list[bytes] = []
    stack = [document]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            stack.extend(reversed(list(value.values())))
        elif isinstance(value, list):
            stack.extend(reversed(value))
        elif isinstance(value, str):
            data = value.encode("utf-8")
            if len(data) >= StringNode.TEXT_MIN_BYTES:
                parts.append(data)
    return b"".join(parts)


def _train_text_dictionary(samples: list[Any], size: int) -> bytes | None:
    import zstandard

    texts = [t for t in map(_packet_text, samples) if t]
    total = sum(map(len, texts))
    if len(texts) < 8 or total < 1024:
        return None
    try:
        trained = zstandard.train_dictionary(min(size, max(1024, total // 2)), texts)
    except zstandard.ZstdError:
        return None
    return trained.as_bytes()


def _read_samples(paths: Sequence[str], each: bool) -> list[Any]:
    documents: list[Any] = []
    for name in paths:
        path = Path(name)
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() in (".jsonl", ".ndjson"):
            documents += [
                json.loads(line) for line in text.splitlines() if line.strip()
            ]
        else:
            document = json.loads(text)
            if each and isinstance(document, list):
                documents += document
            else:
                documents.append(document)
    return documents


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sjson.compile",
        description="Compile an SJSON dictionary from a schema and/or samples.",
    )
    parser.add_argument("--schema", help="JSON Schema or XSD file")
    parser.add_argument(
        "--sample",
        action="append",
        default=[],
        help="sample document (.json) or documents (.jsonl); repeatable",
    )
    parser.add_argument(
        "--each",
        action="store_true",
        help="treat a top-level array in a .json sample as a list of documents",
    )
    parser.add_argument(
        "--intern-min-count",
        type=int,
        help="intern sample strings seen at least this many times",
    )
    parser.add_argument("--max-value-length", type=int, default=64)
    parser.add_argument(
        "--text-dictionary-size",
        type=int,
        default=0,
        help="opt-in: train a zstd text dictionary of about this many bytes "
        "on the samples (default 0: none)",
    )
    parser.add_argument(
        "--xsd-string-values",
        action="store_true",
        help="XSD only: every simple value is a JSON string (plain xmltodict)",
    )
    parser.add_argument("-o", "--output", required=True, help="output file")
    args = parser.parse_args(argv)
    if args.schema is None and not args.sample:
        parser.error("give --schema, --sample, or both")

    options = {}
    if args.schema and args.schema.lower().endswith(".xsd"):
        options["typed_values"] = not args.xsd_string_values
    try:
        dictionary = compile_dictionary(
            schema=args.schema,
            samples=_read_samples(args.sample, args.each),
            intern_min_count=args.intern_min_count,
            max_value_length=args.max_value_length,
            text_dictionary_size=args.text_dictionary_size,
            **options,
        )
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    dictionary.save(args.output)
    print(
        f"{args.output}: {dictionary.base_size} names, "
        f"{len(dictionary.base_values())} values, "
        f"fingerprint {dictionary.fingerprint:#010x}"
        + (", with schema" if dictionary.schema is not None else "")
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
