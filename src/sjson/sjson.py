from random import randint
from typing import Any

from bitstring import BitArray

from sjson.node import Node
from sjson.tag_dictionary import TagDictionary


class SJSON:
    """
    This class encodes and decodes JSON documents into a compact bitstream using
    a dictionary compression scheme and tight binary encoding. The dictionary is
    unique per-sender, and must be exchanged at least once with the receiver,
    although after the initial exchange, differential updates are possible with
    the receiver requesting explicit tag identifiers from the sender. The
    receiver must maintain a dictionary for each sender it is communicating with.

    The data is encoded in the following format:
    | bit numbers | description |
    |:-----------:|:-----------:|
    | 0-15        | 16 bit sender identifier |
    | 40+         | JSON data encoded using dictionary compression |
    | n - (n + 31) | 32 bit CRC checksum |

    The dictionary data is encoded as follows:
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
    | 0 | null field | 0 bits |
    | 1 | boolean | 1 bit: 1 = true, 0 = false |
    | 2 | number | 4*(n/2) bits where digits are BCD encoded, see below |
    | 3 | string | 16 bits + n*8 bits or 8 + LZ4(n) bits where n is the # of chars |
    | 4 | array | 16 bits for number of elements |
    | 5 | object | 0 bits |
    | 6 | End of object | 0 bits |
    | 7 | Reserved | 0 bits |

    Nodes are encoded in the following format:
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
    """

    def __init__(self) -> None:
        self.sender_dictionaries: dict[int, TagDictionary] = {}
        # TODO: Get the sender id from the config file
        self.sender_id = randint(0, 0xFFFF)

    def to_binary(self, json_object: Any) -> BitArray:
        data_node = Node.from_value(json_object, self.get_dictionary(self.sender_id))
        ret_val = BitArray(uint=self.sender_id, length=16) + data_node.to_binary(
            tag_dictionary=self.get_dictionary(self.sender_id)
        )
        ret_val.crc

    def to_value(self, bits: BitArray) -> Any:
        sender_id = int(str(bits[0:16]), 2)
        bits = bits[16:]
        data_node = Node.from_bits(bits, self.get_dictionary(sender_id))
        return data_node.get_value()

    def get_dictionary(self, sender_id: int) -> TagDictionary:
        if sender_id not in self.sender_dictionaries:
            self.sender_dictionaries[sender_id] = TagDictionary()
        return self.sender_dictionaries[sender_id]
