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

import pytest

from sjson.sjson import SJSON, UnknownSchemaError

FIXTURES = Path(__file__).parent / "fixtures"

ORDER = {
    "orderId": "A1B2C3D4",
    "created": "2026-11-18T10:20:30Z",
    "status": "SHIPPED",
    "total": 129.99,
    "items": [
        {"sku": "X-100", "price": 19.99, "count": 2},
        {"sku": "Y-200", "price": 90.01, "count": 1},
    ],
    "customer": {"id": 48213, "email": "pat@example.com", "vip": False},
    "notes": None,
}

XML_ORDER = {
    "order": {
        "@id": "A1",
        "created": "2026-11-18T10:20:30Z",
        "status": "PAID",
        "item": [{"sku": "X", "count": 2, "price": {"#text": 1.5, "@currency": "USD"}}],
        "customer": {"@partyId": 7, "name": "Pat", "vip": True},
    }
}


class TestSchemaPreloadedSJSON:
    @pytest.mark.parametrize(
        "schema,document",
        [(FIXTURES / "order.schema.json", ORDER), (FIXTURES / "order.xsd", XML_ORDER)],
    )
    def test_first_message_needs_no_nak(self, schema: Path, document: dict) -> None:
        sender = SJSON(schema=schema)
        receiver = SJSON()
        receiver.register_schema(schema)
        packet = sender.to_binary(document)
        assert receiver.to_value(packet) == document
        assert (
            SJSON.read_header(packet).fingerprint
            == sender.get_dictionary(sender.get_sender_id()).fingerprint
        )

    def test_unknown_fields_still_use_nak(self) -> None:
        schema = FIXTURES / "order.schema.json"
        sender = SJSON(schema=schema)
        receiver = SJSON()
        receiver.register_schema(schema)
        document = dict(ORDER, extraField=1, link="https://example.com/a")
        sender.to_binary(document)  # the URL is interned on its second sighting
        packet = sender.to_binary(document)
        with pytest.raises(KeyError):
            receiver.to_value(packet)
        known = receiver.last_known_tag(sender.get_sender_id())
        base = sender.get_dictionary(sender.get_sender_id()).base_size
        assert known == base
        known_value = receiver.last_known_value(sender.get_sender_id())
        update = sender.nak_dictionary(sender.get_sender_id(), known, known_value)
        receiver.load_dictionary(update)
        assert receiver.to_value(packet) == document
        # Only the names and values outside the schema were sent.
        dictionary = sender.get_dictionary(sender.get_sender_id())
        assert [name for _, name in dictionary.get_tags(known)] == [
            "extraField",
            "link",
        ]
        assert dictionary.values is not None
        assert [v for _, v in dictionary.values.get_tags(known_value)] == [
            "https://example.com/a"
        ]

    def test_unregistered_schema(self) -> None:
        sender = SJSON(schema=FIXTURES / "order.schema.json")
        with pytest.raises(UnknownSchemaError):
            SJSON().to_value(sender.to_binary(ORDER))

    def test_sender_switching_schema(self) -> None:
        first = SJSON(schema=FIXTURES / "order.schema.json", sender_id=42)
        second = SJSON(schema=FIXTURES / "order.xsd", sender_id=42)
        receiver = SJSON()
        receiver.register_schema(FIXTURES / "order.schema.json")
        receiver.register_schema(FIXTURES / "order.xsd")
        assert receiver.to_value(first.to_binary(ORDER)) == ORDER
        assert receiver.to_value(second.to_binary(XML_ORDER)) == XML_ORDER

    def test_schema_makes_packets_smaller(self) -> None:
        schema = FIXTURES / "order.schema.json"
        with_schema = len(SJSON(schema=schema).to_binary(ORDER))
        without = len(SJSON().to_binary(ORDER))
        # The fingerprint costs 32 bits; earlier tag ids make up for it.
        assert with_schema <= without + 32

    def test_invalid_sender_id(self) -> None:
        with pytest.raises(ValueError):
            SJSON(sender_id=70000)

    def test_bad_version(self) -> None:
        packet = SJSON().to_binary({"a": 1})
        packet.overwrite("0b1111", 0)
        with pytest.raises(ValueError):
            SJSON().to_value(packet)
