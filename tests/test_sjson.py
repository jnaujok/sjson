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

import uuid
import json

from bitstring import BitArray
from sjson.node import Node
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
        assert isinstance(ba, BitArray)
        assert ba[16:19].bin == Node.NODE_OBJECT
        assert ba[-35:-32].bin == Node.END_OF_OBJECT
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
