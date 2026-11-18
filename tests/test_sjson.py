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

import json
import uuid

import pytest

from bitstring import BitArray
from sjson.node import Node
from sjson.object_node import ObjectNode
from sjson.sjson import SJSON


class TestSJson:
    def setup_method(self) -> None:
        self.json = {
            "name": "Standard_test_for_streaming_json",
            "description": (
                "A really long description that is long enough to ensure "
                "that compression occurs and the string gets shrunk down."
            ),
            "uuid": str(uuid.uuid4()),
            "an_array": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            "object_array": [{"name": "item1"}, {"name": "item2"}],
            "an_object": {"name": "Standard_test_for_streaming_json_inner"},
            "a_number": 123,
            "a_big_number": 1234567890,
            "a_float": 123.456,
            "a_boolean": True,
            "a_null": None,
        }
        self.sjson = SJSON()

    def test_from_json(self) -> None:
        json_length = len(json.dumps(self.json).encode("utf-8"))
        ba = self.sjson.to_binary(self.json)
        node_start = SJSON.read_header(ba).header_length
        assert isinstance(ba, BitArray)
        assert ba[node_start : node_start + 3].bin == Node.NODE_OBJECT  # noqa E501
        assert ba[-37:-32].bin == ObjectNode.END_OF_MEMBERS
        bs_len = len(ba.tobytes())
        assert json_length > bs_len

    def test_to_value(self) -> None:
        ba = self.sjson.to_binary(self.json)
        ba_len = len(ba.tobytes())
        val = self.sjson.to_value(ba)
        assert isinstance(val, dict)

        val_length = len(json.dumps(val).encode("utf-8"))
        json_length = len(json.dumps(self.json).encode("utf-8"))
        assert val_length == json_length
        assert ba_len < json_length
        assert val == self.json

    def test_to_value_does_not_modify_input(self) -> None:
        ba = self.sjson.to_binary(self.json)
        copy = ba.copy()
        self.sjson.to_value(ba)
        assert ba == copy

    def test_byte_padded_packet(self) -> None:
        """A packet sent as bytes gets zero padding after the CRC."""
        for document in ({"a": True}, self.json, [1, "two", None]):
            ba = self.sjson.to_binary(document)
            padded = BitArray(bytes=ba.tobytes())
            assert self.sjson.to_value(padded) == document

    def test_crc_mismatch(self) -> None:
        ba = self.sjson.to_binary(self.json)
        ba.invert(20)
        with pytest.raises(ValueError):
            self.sjson.to_value(ba)

    def test_sender_id_and_length(self) -> None:
        ba = self.sjson.to_binary(self.json)
        sender_id, length = SJSON.get_sender_id_and_length(ba)
        assert sender_id == self.sjson.get_sender_id()
        assert length + 32 == len(ba)

    def test_incremental_nak(self) -> None:
        receiver = SJSON()
        first = self.sjson.to_binary({"alpha": 1})
        receiver.load_dictionary(
            self.sjson.nak_dictionary(self.sjson.get_sender_id(), 0)
        )
        assert receiver.to_value(first) == {"alpha": 1}
        known = receiver.get_dictionary(self.sjson.get_sender_id()).last_index
        second = self.sjson.to_binary({"alpha": 2, "beta": "https://example.com/x"})
        with pytest.raises(KeyError):
            receiver.to_value(second)
        update = self.sjson.nak_dictionary(self.sjson.get_sender_id(), known)
        receiver.load_dictionary(update)
        assert receiver.to_value(second) == {
            "alpha": 2,
            "beta": "https://example.com/x",
        }

    def test_long_tag_names(self) -> None:
        """Tag names (and interned URLs) longer than 255 bytes survive a NAK."""
        url = "https://example.com/" + "p" * 400
        ba = self.sjson.to_binary({"link": url})
        receiver = SJSON()
        receiver.load_dictionary(
            self.sjson.nak_dictionary(self.sjson.get_sender_id(), 0)
        )
        assert receiver.to_value(ba) == {"link": url}

    def test_nak_dict(self) -> None:
        ba = self.sjson.to_binary(self.json)
        dict_ba = self.sjson.nak_dictionary(self.sjson.get_sender_id(), 0)
        assert isinstance(ba, BitArray)
        assert isinstance(dict_ba, BitArray)
        receiver = SJSON()
        receiver.load_dictionary(dict_ba)
        assert receiver.to_value(ba) == self.json
