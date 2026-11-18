# Changelog

All notable changes to sjson are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Packet format versions (the 4-bit
version in every packet) are noted where they changed; peers reject packet
versions they do not know.

## [Unreleased]

### Added

- `CHANGELOG.md`, and a `CLAUDE.md` rule that README.md and CHANGELOG.md are
  updated in the same pull request, before every merge.
- README: a **Known limitations** section (restarted stateless senders, #13;
  the ACK/NAK example's blocking writes, IASLib #3).

### Changed

- The dictionary an instance sends with is `SJSON.own_dictionary`, kept apart
  from those it learns from peers (`get_dictionary(sender_id)`), so nothing a
  peer sends can change it. An instance no longer decodes its own packets
  with it (same-instance loopback); like any receiver it learns the names
  through a NAK. `nak_dictionary()` always answers with the instance's own
  names. (#14)
- Stateless packets that use a compiled text dictionary keep the digested
  dictionary and their zstd compressor and decompressor between packets:
  about 9 us per frame instead of about 370 us. (#12)

## [0.9.0] - 2026-11-18

Packet format version 5.

### Added

- The sender id is optional (flag bit 3). Stream mode leaves it out by
  default; `include_sender_id` overrides either way, and receivers attribute
  packets without one to `to_value(packet, sender_id=...)`.
- `examples/acknak.py`: an ACK/NAK link over a byte stream (dictionary NAKs,
  stream reset, resend of damaged packets, lost ACKs, frame size limits),
  with a demo and tests.
- The benchmark suite in `benchmarks/` (UCI mission stream, real-world API
  streams, XML and EXI comparisons, export for the C++ port).
- README: usage, badges and a compression comparison section.

### Changed

- The packet version leads the packet and the flags are 4 bits.
- Stream-mode zstd contexts use a 128 KiB window: about 3 MB per stream
  instead of about 90 MB, with the same compression.
- Compiled dictionaries use the `.sdj` extension; `sjson.compile` names the
  output after the schema when `-o` is not given.

### Fixed

- `$defs` names holding `/`, `~` or `%` are escaped in their JSON Pointers.
- Review fixes in the ACK/NAK example (frames kept across timeouts,
  recovery paths) and the benchmarks (NAK bytes counted, XML attributes
  escaped once).

## [0.8.0] - 2026-11-18

Packet format version 4.

### Added

- Stream mode (`stateful=True`): per-field caches of recent values, float,
  integer, timestamp and prefix deltas, cached objects and shapes, inline
  name definitions, sequence numbers with `StreamGapError` and
  `reset_stream()`, and a zstd text channel.
- Opt-in zstd text dictionaries trained on sample traffic
  (`text_dictionary_size`).

### Changed

- URLs are interned on their second sighting.

## [0.7.0] - 2026-11-18

Packet format version 3.

### Fixed

- Objects end with tag id 0 instead of a 3-bit marker, so documents with
  more than 255 field names decode.

## [0.6.0] - 2026-11-18

### Added

- Pre-compiled dictionaries (`sjson.compile`, `TagDictionary.save` and
  `load`) in place of a schema, optionally ordered by sample traffic.

## [0.5.0] - 2026-11-18

### Added

- Schema-driven encoding: documents that fit the schema are sent without
  field tags or type codes.

## [0.4.0] - 2026-11-18

Packet format version 2.

### Added

- An interned value dictionary for enumerated strings and URLs.

## [0.3.0] - 2026-11-18

Packet format version 1.

### Added

- Dictionaries pre-loaded from a JSON Schema or XSD, identified in packets
  by a fingerprint.

## [0.2.0] - 2026-11-18

### Fixed

- Decoding bugs; decoding in linear time; tighter encodings.

## [0.1.0] - 2025-11-23

- First release: dictionary-compressed binary JSON with NybbleField lengths,
  string compression forms and the NAK dictionary exchange.
