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

from pathlib import Path

from sjson.node import Node
from sjson.sjson import SJSON
from sjson.string_node import StringNode
from sjson.tag_dictionary import TagDictionary

FIXTURES = Path(__file__).parent / "fixtures"
ORDER_JSON = FIXTURES / "order.schema.json"


def string_bits(value: str, dictionary: TagDictionary) -> str:
    return StringNode(value).to_binary(dictionary).bin


class TestValueDictionary:
    def test_enum_values_are_preloaded(self) -> None:
        dictionary = TagDictionary.from_schema(ORDER_JSON)
        values = dictionary.values
        assert values is not None
        assert [v for _, v in values.get_tags(0)] == [
            "PENDING",
            "PAID",
            "SHIPPED",
            "CANCELLED",
            "US",
            "CA",
            "MX",
        ]
        assert values.base_size == 7

    def test_enum_value_is_sent_as_an_id(self) -> None:
        dictionary = TagDictionary.from_schema(ORDER_JSON)
        bits = string_bits("SHIPPED", dictionary)
        # type + special flag + INTERNED code + NybbleField(3)
        assert bits == Node.NODE_STRING + "1" + "0001" + "00011"
        decoded = Node.from_bits(
            StringNode("SHIPPED").to_binary(dictionary), dictionary
        )
        assert decoded.get_value() == "SHIPPED"

    def test_values_do_not_take_field_ids(self) -> None:
        dictionary = TagDictionary()
        StringNode("https://example.com/").to_binary(dictionary)
        assert dictionary.last_index == 0
        assert dictionary.values is not None
        assert dictionary.values.get("https://example.com/") == 1

    def test_repeated_url_uses_the_same_id(self) -> None:
        dictionary = TagDictionary()
        first = StringNode("https://example.com/").to_binary(dictionary)
        second = StringNode("https://example.com/").to_binary(dictionary)
        assert first == second

    def test_strings_outside_the_enum_are_not_interned(self) -> None:
        dictionary = TagDictionary.from_schema(ORDER_JSON)
        bits = StringNode("RETURNED").to_binary(dictionary)
        assert bits[4:8].bin != StringNode.SPECIAL_HANDLING_INTERNED.bin
        assert dictionary.values is not None
        assert not dictionary.values.has_tag("RETURNED")


class TestValueNak:
    def test_values_travel_in_the_nak(self) -> None:
        sender = SJSON()
        receiver = SJSON()
        document = {"home": "https://example.com/", "next": "https://example.com/2"}
        packet = sender.to_binary(document)
        receiver.load_dictionary(sender.nak_dictionary(sender.get_sender_id(), 0, 0))
        assert receiver.to_value(packet) == document
        assert receiver.last_known_value(sender.get_sender_id()) == 2

    def test_incremental_values(self) -> None:
        sender = SJSON()
        receiver = SJSON()
        receiver.load_dictionary(sender.nak_dictionary(sender.get_sender_id(), 0, 0))
        sender.to_binary({"a": "https://example.com/1"})
        packet = sender.to_binary({"a": "https://example.com/2"})
        sid = sender.get_sender_id()
        update = sender.nak_dictionary(
            sid, receiver.last_known_tag(sid), receiver.last_known_value(sid)
        )
        receiver.load_dictionary(update)
        assert receiver.to_value(packet) == {"a": "https://example.com/2"}

    def test_schema_enums_need_no_nak(self) -> None:
        sender = SJSON(schema=ORDER_JSON)
        receiver = SJSON()
        receiver.register_schema(ORDER_JSON)
        document = {
            "orderId": "x",
            "status": "CANCELLED",
            "items": [],
            "customer": {"id": 1, "address": {"country": "MX"}},
        }
        assert receiver.to_value(sender.to_binary(document)) == document
        sid = sender.get_sender_id()
        assert receiver.last_known_value(sid) == 7


class TestInternedBeforeSpecialForms:
    def test_enumerated_uuid_uses_its_value_id(self) -> None:
        enum_uuid = "12345678-1234-a2f7-1234-123456789012"
        dictionary = TagDictionary.from_schema(
            {"properties": {"id": {"enum": [enum_uuid]}}}
        )
        bits = StringNode(enum_uuid).to_binary(dictionary)
        assert bits[4:8].bin == StringNode.SPECIAL_HANDLING_INTERNED.bin
        assert len(bits) == 13
        assert Node.from_bits(bits, dictionary).get_value() == enum_uuid


class TestPacketVersion:
    def test_older_versions_are_rejected(self) -> None:
        packet = SJSON().to_binary({"a": "https://example.com/"})
        assert SJSON.read_header(packet).version == SJSON.VERSION == 2
        packet.overwrite("0b0001", 16)
        try:
            SJSON().to_value(packet)
        except ValueError as error:
            assert "version" in str(error)
        else:  # pragma: no cover
            raise AssertionError("a version-1 packet was accepted")
