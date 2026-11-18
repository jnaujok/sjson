# Streaming JSON Library

[![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![PyPI Version](https://img.shields.io/pypi/v/sjson.svg)](https://pypi.org/project/sjson/)
[![Poetry](https://img.shields.io/badge/poetry-managed-blue.svg)](https://python-poetry.org/)
[![License: LGPL-2.1](https://img.shields.io/badge/License-LGPL--2.1-blue.svg)](https://opensource.org/licenses/LGPL-2.1)

This library is meant to compress JSON into a binary representation that is likely as compressed as possible without prior knowledge of the library.

## Current State
Currently still in a pre-alpha state, the library can compress a JSON dictionary into a tight binary representation, with the caveat that currently the dictionary of names is not yet transferred to a listening party.

To truly use this library, there must be an "ACK/NAK" mechanism over the top of it, where the receiver can NAK a message with a request for library fields in return. The library fields will then be sent (LZ4 compressed) to the receiver where they can build a sender dictionary.

Since this is a totally dynamic protocol, each receiver will need a dictionary stored for each sender.


## Preloading the dictionary from a schema

Normally the receiver learns field names by NAKing the first message it cannot
decode. When both sides have the same JSON Schema or XSD, the dictionary can be
built from it before anything is sent:

```python
from sjson.sjson import SJSON

sender = SJSON(schema="order.schema.json")      # or "order.xsd"
receiver = SJSON()
receiver.register_schema("order.schema.json")

packet = sender.to_binary(document)
receiver.to_value(packet)   # decodes the first message, no NAK needed
```

Every property name in the schema is given an id, breadth first with required
members before optional ones, so the most common fields get the smallest
(5-bit) ids. Names the schema does not list are numbered after the schema's
names and still travel through the normal NAK; a receiver NAKs with
`receiver.last_known_tag(sender_id)`, so only those extra names are sent.

String values listed in `enum` / `const` (JSON Schema) or `xs:enumeration`
(XSD) are preloaded into the value dictionary the same way, so a value such as
`"SHIPPED"` is sent as a 5- or 10-bit id.

Packets from a sender with a schema carry the schema's 32-bit fingerprint, a
CRC of the whole loaded schema. A receiver that has not registered that schema
raises `UnknownSchemaError` instead of decoding garbage.

**JSON Schema** (drafts 4 to 2020-12): `properties`, `required`, `$ref`
(local pointers and relative files, recursion included), `$defs` /
`definitions`, `allOf`, `anyOf` / `oneOf`, `if` / `then` / `else`,
`dependentSchemas`, `items` / `prefixItems`, `enum` / `const`, numeric bounds,
`format`, and OpenAPI `nullable`. Remote `http(s)` references are not fetched.

**XSD**: elements, attributes, named and anonymous types, `complexContent` and
`simpleContent` extension and restriction, `group`, `attributeGroup`,
`include` / `import` / `redefine` of local files, enumeration and range facets.
XSD describes XML, so the JSON is expected to follow the `xmltodict`
convention: the document is `{"rootElement": {...}}`, attributes are
`"@name"`, element text next to attributes is `"#text"`, and repeated elements
are arrays. The prefixes can be changed with `attribute_prefix` and
`text_key`; pass `typed_values=False` if every value is a string.

## Pre-compiled dictionaries

Instead of shipping and parsing the schema on every peer, compile the
dictionary once and distribute the result, a small JSON file:

```shell
python -m sjson.compile --schema order.schema.json -o order.dict.json
# or, once installed:
sjson-compile --schema order.xsd -o order.dict.json
```

```python
sender = SJSON(dictionary="order.dict.json")
receiver = SJSON()
receiver.register_dictionary("order.dict.json")
```

The file lists the field names and interned values in id order, plus the
compiled schema model when there was one, so schema-driven encoding (below)
still works. A dictionary compiled from a schema alone has the schema's
fingerprint, so peers using the schema file and peers using the compiled file
can talk to each other.

Compiling from sample traffic gives better results. Field names are numbered
by how often they occur, so the most frequent fields get the 5-bit ids, and
strings that repeat can be interned:

```shell
python -m sjson.compile --schema order.schema.json \
    --sample traffic.jsonl --intern-min-count 5 -o order.dict.json
```

Samples work without a schema as well. A `.jsonl` file holds one document per
line; `--each` treats a top-level array in a `.json` file as a list of
documents. The same is available in Python as
`sjson.compile.compile_dictionary(schema=..., samples=..., intern_min_count=...)`,
and as `TagDictionary.save()` / `TagDictionary.load()`. A plain JSON list of
names, or `{"tags": [...], "values": [...]}`, is also accepted as a dictionary.
Only the pre-loaded entries are saved; names a sender learns later still travel
through the NAK. A dictionary without a schema is identified in packets by its
own fingerprint, just like a schema.

## Schema-driven encoding

With a schema on both sides, SJSON also skips everything the schema already
says. Field tags and type codes are left out, and the members of an object are
written in schema order:

| schema type | encoding |
|:------------|:---------|
| `enum` / `const` | index into the list, ceil(log2 n) bits (a `const` takes 0 bits) |
| boolean | 1 bit |
| integer with `minimum` and `maximum` | `value - minimum` in just enough bits |
| integer with `minimum` >= 0 | NybbleField of `value - minimum` |
| other numbers | the number payload without its type code |
| string | the string payload without its type code |
| array with `items` | NybbleField count, then each item |
| object | one presence bit per optional member, then the members; if other members are allowed, one more bit and, when set, the extra members tagged as usual |
| `anyOf`, mixed types, tuples, untyped | the ordinary tagged encoding |

A nullable type (`["string", "null"]`, OpenAPI `nullable`) costs one extra bit.

This is on by default whenever the sender has a schema. Each document is
checked as it is encoded. A document that does not fit the schema (a wrong
type, a missing required member, a value outside the `enum` or its bounds, or
an unexpected member in a closed object) is sent with the tagged encoding
instead, so nothing is ever lost. Pass `SJSON(schema=..., schema_encoding=False)`
to always use the tagged encoding. Decoded objects list their members in
schema order, which can differ from the order in the original document.

The sample order in the tests goes from 254 bytes of JSON to 89 bytes tagged
and 71 bytes schema-encoded (packet header and CRC included).

## Stream mode

On a link that delivers packets in order (TCP, WebSocket, a reliable message
bus), turn on stream mode and both sides remember recent values:

```python
sender = SJSON(schema="order.schema.json", stateful=True)
```

- Every field keeps its 8 most recent values (`cache_width=3` bits). A value
  seen recently costs 4 bits; whole objects, object shapes and the pattern of
  optional members are cached the same way.
- A changed value can be sent as a delta from a recent one: floats as the
  difference (or XOR) of their bit patterns, integers and ISO-8601 timestamps
  as a signed difference, other strings as a shared prefix plus a new suffix.
  The encoder always picks the shortest form, and values stay exact.
- Longer strings travel in a text channel: one zstd block per packet whose
  compression context lasts for the whole stream.
- New field names are defined inline, so a receiver never needs a NAK.
- Each packet carries an 8-bit sequence number. A receiver that misses a packet
  raises `StreamGapError`; the sender calls `reset_stream()` and the next
  packet (sequence 0) starts both sides afresh. Only that first packet carries
  the schema fingerprint.

Opt-in: `compile_dictionary(..., text_dictionary_size=16384)` (or
`--text-dictionary-size 16384`) also trains a small zstd dictionary on the
samples' text. It warms the text channel in stream mode and gives
per-message (non-stream) packets a text channel of their own, but it only
helps traffic that resembles the samples, so it is off by default.

On a realistic mixed UCI mission stream (six platforms, one sender each),
stream mode with just the UCI schema and no sample data averages about 90
bytes per message with smoothly moving kinematics and 118 with random values,
against 106 and 145 for zstd-19 with a persistent stream context.

## Wire format (0.8)

All variable-length integers use a **NybbleField**: a unary prefix that says how
many nybbles follow.

| prefix | data bits | values | total bits |
|:-------|:---------:|:-------|:----------:|
| 0 | 4 | 0 - 15 | 5 |
| 10 | 8 | 16 - 255 | 10 |
| 110 | 12 | 256 - 4,095 | 15 |
| 1110 | 16 | up to 65,535 | 20 |
| 11110 | 20 | up to 1,048,575 | 25 |
| 111110 | 24 | up to 16,777,215 | 30 |
| 1111110 | 28 | up to 268,435,455 | 35 |
| 1111111 | 32 | up to 4,294,967,295 | 39 |

### Packet

| field | description |
|:------|:------------|
| 16 bits | sender identifier |
| 4 bits | packet version (currently 4); peers reject versions they do not know |
| 3 bits | flags; bit 0: a schema fingerprint follows; bit 1: the data uses the schema-driven encoding; bit 2: stream mode |
| 8 + 3 bits | stream mode only: sequence number and cache width |
| 32 bits | schema fingerprint, only when flagged |
| NybbleField | length of the encoded data in bits |
| ... | the encoded JSON value |
| 32 bits | CRC32 of the zero-padded bytes of everything above |

Receivers locate the CRC with the length field, so a packet that was padded to
whole bytes in transit still decodes.

### Dictionary update (response to a NAK)

| field | description |
|:------|:------------|
| 16 bits | sender identifier |
| NybbleField | number of tags |
| per tag | NybbleField tag id, NybbleField UTF-8 byte length, UTF-8 bytes |
| NybbleField | number of interned values |
| per value | NybbleField value id, NybbleField UTF-8 byte length, UTF-8 bytes |

Tag 0 means "unnamed"; field names are numbered from 1 in the order they are
first seen. Interned string values (URLs, and strings a schema enumerates) have
their own id space, also starting at 1, so they never push field names onto
longer ids. A receiver NAKs with `last_known_tag(sender_id)` and
`last_known_value(sender_id)` and receives only what it is missing.

### Values

Every value starts with a 3-bit type code.

| code | JSON type | payload |
|:----:|:----------|:--------|
| 000 | null | none |
| 001 | boolean | 1 bit |
| 010 | number | see below |
| 011 | string | see below |
| 100 | array | the items, then `110` |
| 101 | object | (NybbleField tag id + value) per member, then tag id 0 (`00000`) |
| 110 | end of array / object | none |
| 111 | reserved | |

**Numbers** carry a 2-bit sub-type and the encoder keeps the shortest form:

| sub-type | form | payload |
|:--------:|:-----|:--------|
| 00 | integer | sign bit + NybbleField magnitude (below 2^32) |
| 01 | float32 | 32-bit IEEE-754, used only when it round-trips exactly |
| 10 | float64 | 64-bit IEEE-754 |
| 11 | decimal | int/float bit + NybbleField count + BCD nybbles |

The decimal form codes `0-9` as themselves, `.` as 10, `E` as 11, `+` as 12,
`-` as 13, `Infinity` as 14 and `NaN` as 15.

**Strings** start with a flag bit: `0` is plain UTF-8 (NybbleField byte count +
bytes); `1` is followed by a 4-bit code. Every form that applies is tried and the
shortest is kept.

| code | form | payload |
|:----:|:-----|:--------|
| 0000 | UUID | hyphen bit + upper-case bit + 128 bits |
| 0001 | interned | NybbleField id in the value dictionary (URLs, enumerated values) |
| 0010 | LZ4 block | NybbleField raw bytes + NybbleField packed bytes + data |
| 0011-0110 | range coded, 4-7 bits | NybbleField length + NybbleField base + (code point - base) per character |
| 0111 | empty string | none |
| 1000 | range coded, N bits | NybbleField width, then as above (non-ASCII text) |
| 1001 | hex | upper-case bit + NybbleField length + 4 bits per character |
| 1010 | ISO-8601 date / date-time | day ordinal, second of day, fraction, zone |
| 1011 | base64 | NybbleField byte count + decoded bytes |
| 1100 | text channel | none; the NUL-terminated bytes are in the packet's zstd text block |
| 1101-1111 | reserved | |
