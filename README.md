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


The data is encoded in the following format:
| bit numbers | description |
|:-----------:|:-----------:|
| 0-15        | 16 bit sender identifier |
| 40+         | JSON data encoded using dictionary compression |
| n - (n + 31) | 32 bit CRC checksum |

The dictionary data is encoded as follows:

| bit numbers | description |
|:-----------:|:-----------:|
| 0-15        | 16 bit sender identifier |
| 16-31       | 16 bit length in bytes |
| 32-39 or 32-47 | 8 or 16 bit tag id |
| 8 bits |  8 bit tag length |
| ... | tag data in UTF-8 |
| repeat last two | additional tags |
| CRC | 32 bit CRC checksum |

Tags are encoded as follows:
Tag 00: The node is a value-only node and is not named.
Tag 01-7F: 8 bit tag identifier assigned in order tags are seen.
Tag 80xx-FFxx: 16 bit tag identifier assigned in order tags are seen when
                there are more than 127 tags in dictionary.

JSON is chosen as the compression media because it has only 6 data types,
allowing us to use a four bit type code to represent them.
| node type | JSON data type | Additional bits |
|:---------:|:--------------:|:----------------|
| 0 (000) | null field | 0 bits |
| 1 (001)| boolean | 1 bit: 1 = true, 0 = false |
| 2 (010)| number | 4*(n/2) bits where digits are BCD encoded, see below |
| 3 (011)| string | 16 bits + n*8 bits or 8 + LZ4(n) bits where n is the # of chars |
| 4 (100)| array | 16 bits for number of elements |
| 5 (101)| object | 0 bits |
| 6 (110)| End of object | 0 bits |
| 7 (111)| Reserved | 0 bits |

Named Nodes are encoded in the following format:
| bit numbers | description |
|:-----------:|:-----------:|
| 0-7 or 0-15 | Tag ID (1 or 2 bytes) |
| 8-10 or 16-18 | Node identifier (from above) [3 bits] |
| 11+ or 19+ | additional bits |

BCD encoding is extended as follows:
| character | BCD value | Description |
|:---------:|:---------:|:-----------:|
| 0-9 | 0-9 | The numbers 0-9 are encoded as a single nybble 0-9 |
| . | 10 | The decimal point is encoded as 10 |
| E | 11 | The exponent 'E' is encoded as 11 |
| + | 12 | The plus sign is encoded as 12 |
| - | 13 | The minus sign is encoded as 13 |
| Infinity | 14 | Infinity value |
| NaN | 15 | Not a Number code |

This allows us to encode any number, integer, floating point, or scientific
notation, positive or negative, with an efficient binary representation.