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

## Wire format (0.3)

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
| 4 bits | packet version (currently 1) |
| 3 bits | flags; bit 0 set means a schema fingerprint follows |
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

Tag 0 means "unnamed"; field names are numbered from 1 in the order they are
first seen.

### Values

Every value starts with a 3-bit type code.

| code | JSON type | payload |
|:----:|:----------|:--------|
| 000 | null | none |
| 001 | boolean | 1 bit |
| 010 | number | see below |
| 011 | string | see below |
| 100 | array | the items, then `110` |
| 101 | object | (NybbleField tag id + value) per member, then `110` |
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
| 0001 | URL | NybbleField id in the tag dictionary |
| 0010 | LZ4 block | NybbleField raw bytes + NybbleField packed bytes + data |
| 0011-0110 | range coded, 4-7 bits | NybbleField length + NybbleField base + (code point - base) per character |
| 0111 | empty string | none |
| 1000 | range coded, N bits | NybbleField width, then as above (non-ASCII text) |
| 1001 | hex | upper-case bit + NybbleField length + 4 bits per character |
| 1010 | ISO-8601 date / date-time | day ordinal, second of day, fraction, zone |
| 1011 | base64 | NybbleField byte count + decoded bytes |
| 11xx | reserved | |
