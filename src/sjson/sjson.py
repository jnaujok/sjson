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

from random import randint
from typing import Any
from zlib import crc32

from bitstring import BitArray

from sjson.node import Node
from sjson.nybble_field import NybbleField
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

    def get_sender_id(self) -> int:
        return self.sender_id

    @classmethod
    def get_sender_id_and_length(cls, bits: BitArray) -> tuple[int, int]:
        """
        Given at least the first 8 bytes of the bitstream, extract the sender ID
        and the length of the message.

        Args:
            bits (BitArray): The raw bitstream being decoded.

        Returns:
            tuple[int, int]: The sender ID and the length of the message.
        """
        # Create a copy so we don't modify the bitstream
        temp: BitArray = BitArray(bits[0 : min(64, bits.length)])  # noqa E501
        init_length = temp.length
        sender_id = int(temp[0:16].bin, 2)
        del temp[0:16]
        length = NybbleField.to_value(temp)
        final_length = temp.length
        length += init_length - final_length  # Add back on the length of the header
        del temp
        return sender_id, length

    def to_binary(self, json_object: Any) -> BitArray:
        """
        Encode the JSON object into a bitstream.

        The bitstream is encoded with the sender_id and the length
        of the encoded data (in bits) at the front, and a 32 bit CRC tacked
        on at the back end. Note that this may not be an even number of bytes,
        but will be back-padded by zeros if necessary when sent as a byte array.

        Args:
            json_object (Any): The JSON object to encode.

        Returns:
            BitArray: The encoded bitstream
        """
        data_node = Node.from_value(json_object, self.get_dictionary(self.sender_id))
        data_bits = data_node.to_binary(
            tag_dictionary=self.get_dictionary(self.sender_id)
        )
        ret_val = (
            BitArray(uint=self.sender_id, length=16)
            + NybbleField.to_binary(data_bits.length)
            + data_bits
        )
        val = crc32(ret_val.tobytes())
        ret_val += BitArray(uint=val, length=32)
        return ret_val

    def to_value(self, bits: BitArray) -> Any:
        """
        This method decodes a raw bitstream into the JSON object it represents.

        Args:
            bits (BitArray): The raw bitstream to decode.

        Raises:
            ValueError: If the CRC does not match.
            KeyError: If the tag ID is not known for this sender.
        Returns:
            Any: The decoded JSON object.
        """
        crc = int(bits[-32:].bin, 2)
        del bits[-32:]
        if crc != crc32(bits.tobytes()):
            raise ValueError("CRC mismatch")

        sender_id = int(bits[0:16].bin, 2)
        del bits[:16]

        _ = NybbleField.to_value(bits)  # Extract the data length (not used)

        data_node = Node.from_bits(bits, self.get_dictionary(sender_id))

        return data_node.get_value()

    def get_dictionary(self, sender_id: int) -> TagDictionary:
        """
        Given a sender ID, this method returns the associated dictionary of tags.
        If the sender ID is not in the known set of senders, adds a new dictionary
        assigned to that sender and returns the empty dictionary.

        Args:
            sender_id (int): The sender ID to look up.

        Returns:
            TagDictionary: The dictionary of tags for the given sender.
        """
        if sender_id not in self.sender_dictionaries:
            self.sender_dictionaries[sender_id] = TagDictionary()
        return self.sender_dictionaries[sender_id]

    def nak_dictionary(self, sender_id: int, last_tag_id: int) -> BitArray:
        """
        When used in a streaming situation, the receiver mak NAK a request for a
        dictionary update, with the highest numbered tag they know. If they've
        never seen this sender before, then the NAK will be for a zero tag, and
        the whole dictionary is sent.

        Args:
            last_tag_id (int): The highest numbered tag the receiver knows.

        Returns:
            BitArray: A bitstream containing the response to the NAK.
            | bit numbers | description |
            |:-----------:|:-----------:|
            | 0-15 | Sender ID |
            | 16-31 | Number of tags being returned |
            | 32+ | tag id (8/16) + tag length (8) + tag value (variable) |
        """
        if sender_id not in self.sender_dictionaries:
            return BitArray(uint=sender_id, length=16) + BitArray(uint=0, length=16)
        sender_dict = self.sender_dictionaries[sender_id]
        tag_list: list[tuple[int, str]] = sender_dict.get_tags(last_tag_id)

        ret_val = BitArray(uint=sender_id, length=16) + BitArray(
            uint=len(tag_list), length=16
        )
        for tag_id, tag_name in tag_list:
            if tag_id < 128:
                ret_val.append(BitArray(uint=tag_id, length=8))
            else:
                low = tag_id % 255
                high = (tag_id // 255) + 128
                ret_val.append(BitArray(uint=high, length=8))
                ret_val.append(BitArray(uint=low, length=8))
            str_bytes = tag_name.encode("utf-8")
            ret_val.append(BitArray(uint=len(str_bytes), length=8))
            ret_val.append(BitArray(str_bytes))

        return ret_val

    def load_dictionary(self, ba: BitArray) -> None:
        """
        Loads a dictionary from a bitstream.

        Args:
            ba (BitArray): The bitstream to load the dictionary from.
        """
        sender_id = int(ba[0:16].bin, 2)
        tag_count = int(ba[16:32].bin, 2)
        del ba[0:32]
        for _ in range(tag_count):
            if ba[0:1].bin == "1":
                high = int(ba[1:8].bin, 2)
                low = int(ba[8:16].bin, 2)
                tag_id = high * 255 + low
                del ba[0:16]
            else:
                tag_id = int(ba[1:8].bin, 2)
                del ba[0:8]
            name_length = int(ba[0:8].bin, 2)
            del ba[0:8]
            tag_name = ba[: name_length * 8].tobytes().decode("utf-8")
            del ba[: name_length * 8]

            if sender_id != self.get_sender_id():
                self.get_dictionary(sender_id).set(tag_name, tag_id)
