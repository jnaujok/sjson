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

"""
Builds a :class:`SchemaModel` from an XML Schema (XSD).

SJSON compresses JSON, so an XSD describes the JSON produced from the XML.
The mapping follows the common ``xmltodict`` convention:

- the document is an object whose members are the schema's global elements
  (``{"order": {...}}``);
- child elements become members named after the element;
- attributes become members named ``@`` + attribute name;
- the text of an element that also has attributes (simple content) or mixed
  content becomes a member named ``#text``;
- an element that may repeat (``maxOccurs`` > 1) becomes an array.

The prefixes are configurable. Namespace prefixes are dropped (local names
are used). ``xs:include``, ``xs:import`` and ``xs:redefine`` are followed
for local ``schemaLocation`` files.

With ``typed_values=True`` (the default) simple types map to JSON numbers and
booleans, as produced by converters that type their output. Use
``typed_values=False`` when every value is a string (plain ``xmltodict``).
"""

import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any, Callable

from sjson.schema.json_schema_loader import SchemaLoadError
from sjson.schema.model import (
    KIND_ARRAY,
    KIND_BOOLEAN,
    KIND_INTEGER,
    KIND_NULL,
    KIND_NUMBER,
    KIND_OBJECT,
    KIND_STRING,
    SchemaModel,
    SchemaType,
)

XS = "{http://www.w3.org/2001/XMLSchema}"

_INTEGER_BOUNDS: dict[str, tuple[int | None, int | None]] = {
    "integer": (None, None),
    "long": (-(2**63), 2**63 - 1),
    "int": (-(2**31), 2**31 - 1),
    "short": (-(2**15), 2**15 - 1),
    "byte": (-128, 127),
    "nonNegativeInteger": (0, None),
    "positiveInteger": (1, None),
    "nonPositiveInteger": (None, 0),
    "negativeInteger": (None, -1),
    "unsignedLong": (0, 2**64 - 1),
    "unsignedInt": (0, 2**32 - 1),
    "unsignedShort": (0, 2**16 - 1),
    "unsignedByte": (0, 255),
}
_NUMBER_TYPES = {"decimal", "float", "double"}
_STRING_FORMATS = {
    "date": "date",
    "dateTime": "date-time",
    "time": "time",
    "anyURI": "uri",
    "base64Binary": "base64",
    "hexBinary": "hex",
}


def _local(name: str) -> str:
    """Strip a namespace prefix (``xs:string`` -> ``string``)."""
    return name.rsplit(":", 1)[-1]


def _occurs(node: ElementTree.Element, attribute: str, default: int) -> float:
    value = node.get(attribute)
    if value is None:
        return default
    return float("inf") if value == "unbounded" else int(value)


class XsdLoader:
    def __init__(
        self,
        path: str | Path,
        attribute_prefix: str = "@",
        text_key: str = "#text",
        typed_values: bool = True,
    ) -> None:
        self.path = Path(path)
        self.attribute_prefix = attribute_prefix
        self.text_key = text_key
        self.typed_values = typed_values
        self._elements: dict[str, ElementTree.Element] = {}
        self._complex: dict[str, ElementTree.Element] = {}
        self._simple: dict[str, ElementTree.Element] = {}
        self._groups: dict[str, ElementTree.Element] = {}
        self._attribute_groups: dict[str, ElementTree.Element] = {}
        self._attributes: dict[str, ElementTree.Element] = {}
        self._global_order: list[str] = []
        self._loaded: set[Path] = set()
        self._cache: dict[tuple[str, str], SchemaType] = {}

    def load(self) -> SchemaModel:
        self._read(self.path)
        root = SchemaType(kinds={KIND_OBJECT}, additional_properties=False)
        for name in self._global_order:
            element = self._elements[name]
            root.add_property(name, self._element_type(element, 1, 1), False)
        extras = [self._named_type(name) for name in self._complex]
        return SchemaModel(root=root, extra_types=extras, source=str(self.path))

    # -- reading ----------------------------------------------------------

    def _read(self, path: Path) -> None:
        path = path.resolve()
        if path in self._loaded:
            return
        self._loaded.add(path)
        try:
            tree = ElementTree.parse(path)
        except (OSError, ElementTree.ParseError) as error:
            raise SchemaLoadError(f"Cannot read XSD {path}: {error}")
        schema = tree.getroot()
        if schema.tag != XS + "schema":
            raise SchemaLoadError(f"{path} is not an XML Schema document")
        for child in schema:
            tag = child.tag.replace(XS, "")
            name = child.get("name")
            if tag in ("include", "import", "redefine"):
                location = child.get("schemaLocation")
                if location and "://" not in location:
                    self._read(path.parent / location)
                if tag == "redefine":
                    for redefined in child:
                        self._register(redefined)
            elif name is not None:
                self._register(child)

    def _register(self, child: ElementTree.Element) -> None:
        tag = child.tag.replace(XS, "")
        name = child.get("name")
        if name is None:
            return
        table = {
            "element": self._elements,
            "complexType": self._complex,
            "simpleType": self._simple,
            "group": self._groups,
            "attributeGroup": self._attribute_groups,
            "attribute": self._attributes,
        }.get(tag)
        if table is None:
            return
        if tag == "element" and name not in self._elements:
            self._global_order.append(name)
        table[name] = child

    # -- types ------------------------------------------------------------

    def _cached(
        self, key: tuple[str, str], build: Callable[[SchemaType], None]
    ) -> SchemaType:
        if key in self._cache:
            return self._cache[key]
        result = SchemaType()
        self._cache[key] = result  # placed first so recursive types terminate
        build(result)
        return result

    def _named_type(self, qname: str) -> SchemaType:
        name = _local(qname)
        if name in self._complex:
            return self._cached(
                ("complex", name),
                lambda t: self._complex_type(t, self._complex[name]),
            )
        if name in self._simple:
            return self._cached(
                ("simple", name), lambda t: self._simple_type(t, self._simple[name])
            )
        return self._builtin(name)

    def _builtin(self, name: str) -> SchemaType:
        if name in ("anyType", "anySimpleType"):
            return SchemaType()
        if not self.typed_values:
            result = SchemaType(kinds={KIND_STRING})
            result.format = _STRING_FORMATS.get(name)
            return result
        if name in _INTEGER_BOUNDS:
            low, high = _INTEGER_BOUNDS[name]
            return SchemaType(kinds={KIND_INTEGER}, minimum=low, maximum=high)
        if name in _NUMBER_TYPES:
            return SchemaType(kinds={KIND_NUMBER})
        if name == "boolean":
            return SchemaType(kinds={KIND_BOOLEAN})
        return SchemaType(kinds={KIND_STRING}, format=_STRING_FORMATS.get(name))

    def _element_type(
        self, element: ElementTree.Element, min_occurs: float, max_occurs: float
    ) -> SchemaType:
        """The JSON type of an element, wrapped in an array if it repeats."""
        if element.get("ref"):
            ref = _local(element.get("ref", ""))
            if ref not in self._elements:
                raise SchemaLoadError(f"Unknown element reference: {ref}")
            target = self._elements[ref]
        else:
            target = element

        inline_complex = target.find(XS + "complexType")
        inline_simple = target.find(XS + "simpleType")
        if target.get("type"):
            value_type = self._named_type(target.get("type", ""))
        elif inline_complex is not None:
            value_type = SchemaType()
            self._complex_type(value_type, inline_complex)
        elif inline_simple is not None:
            value_type = SchemaType()
            self._simple_type(value_type, inline_simple)
        else:
            value_type = SchemaType()

        if target.get("nillable") == "true" and value_type.kinds:
            nullable = SchemaType(kinds={KIND_NULL})
            value_type = SchemaType(variants=[value_type, nullable])

        if max_occurs > 1:
            return SchemaType(kinds={KIND_ARRAY}, items=value_type)
        return value_type

    def _complex_type(self, result: SchemaType, node: ElementTree.Element) -> None:
        result.kinds = {KIND_OBJECT}
        result.additional_properties = False
        if node.get("mixed") == "true":
            result.add_property(self.text_key, SchemaType(kinds={KIND_STRING}), False)
        for child in node:
            tag = child.tag.replace(XS, "")
            if tag in ("sequence", "choice", "all", "group"):
                self._particle(result, child, 1, 1)
            elif tag in ("attribute", "attributeGroup", "anyAttribute"):
                self._attribute(result, child)
            elif tag == "simpleContent":
                self._simple_content(result, child)
            elif tag == "complexContent":
                self._complex_content(result, child)

    def _complex_content(self, result: SchemaType, node: ElementTree.Element) -> None:
        if node.get("mixed") == "true":
            result.add_property(self.text_key, SchemaType(kinds={KIND_STRING}), False)
        for derivation in node:
            tag = derivation.tag.replace(XS, "")
            if tag not in ("extension", "restriction"):
                continue
            base = derivation.get("base")
            if tag == "extension" and base and _local(base) != "anyType":
                base_type = self._named_type(base)
                for prop in base_type.properties.values():
                    result.add_property(prop.name, prop.type, prop.required)
                result.additional_properties = base_type.additional_properties
            for child in derivation:
                child_tag = child.tag.replace(XS, "")
                if child_tag in ("sequence", "choice", "all", "group"):
                    self._particle(result, child, 1, 1)
                elif child_tag in ("attribute", "attributeGroup", "anyAttribute"):
                    self._attribute(result, child)

    def _simple_content(self, result: SchemaType, node: ElementTree.Element) -> None:
        for derivation in node:
            tag = derivation.tag.replace(XS, "")
            if tag not in ("extension", "restriction"):
                continue
            base = derivation.get("base")
            text_type = self._named_type(base) if base else SchemaType()
            if base and _local(base) in self._complex:
                # Deriving from a complex type with simple content.
                for prop in text_type.properties.values():
                    result.add_property(prop.name, prop.type, prop.required)
            else:
                if tag == "restriction":
                    restricted = SchemaType()
                    self._copy_simple(restricted, text_type)
                    self._facets(restricted, derivation)
                    text_type = restricted
                result.add_property(self.text_key, text_type, True)
            for child in derivation:
                if child.tag.replace(XS, "") in (
                    "attribute",
                    "attributeGroup",
                    "anyAttribute",
                ):
                    self._attribute(result, child)

    def _particle(
        self,
        result: SchemaType,
        node: ElementTree.Element,
        min_occurs: float,
        max_occurs: float,
    ) -> None:
        """Process a sequence / choice / all / group and the elements in it."""
        tag = node.tag.replace(XS, "")
        min_occurs = min_occurs * _occurs(node, "minOccurs", 1)
        max_occurs = max_occurs * _occurs(node, "maxOccurs", 1)
        if tag == "group":
            ref = node.get("ref")
            if ref is not None:
                group = self._groups.get(_local(ref))
                if group is None:
                    raise SchemaLoadError(f"Unknown group reference: {ref}")
                node = group
            for child in node:
                if child.tag.replace(XS, "") in ("sequence", "choice", "all"):
                    self._particle(result, child, min_occurs, max_occurs)
            return
        if tag == "choice":
            min_occurs = 0
        for child in node:
            child_tag = child.tag.replace(XS, "")
            if child_tag == "element":
                child_min = min_occurs * _occurs(child, "minOccurs", 1)
                child_max = max_occurs * _occurs(child, "maxOccurs", 1)
                name = child.get("name") or _local(child.get("ref", ""))
                result.add_property(
                    name,
                    self._element_type(child, child_min, child_max),
                    child_min > 0,
                )
            elif child_tag in ("sequence", "choice", "all", "group"):
                self._particle(result, child, min_occurs, max_occurs)
            elif child_tag == "any":
                result.additional_properties = True

    def _attribute(self, result: SchemaType, node: ElementTree.Element) -> None:
        tag = node.tag.replace(XS, "")
        if tag == "anyAttribute":
            result.additional_properties = True
            return
        if tag == "attributeGroup":
            group = self._attribute_groups.get(_local(node.get("ref", "")))
            if group is None:
                raise SchemaLoadError(f"Unknown attributeGroup: {node.get('ref')}")
            for child in group:
                if child.tag.replace(XS, "") in (
                    "attribute",
                    "attributeGroup",
                    "anyAttribute",
                ):
                    self._attribute(result, child)
            return
        if node.get("use") == "prohibited":
            return
        target = node
        if node.get("ref"):
            target = self._attributes.get(_local(node.get("ref", "")), node)
        name = target.get("name") or _local(node.get("ref", ""))
        inline = target.find(XS + "simpleType")
        if target.get("type"):
            attribute_type = self._named_type(target.get("type", ""))
        elif inline is not None:
            attribute_type = SchemaType()
            self._simple_type(attribute_type, inline)
        else:
            attribute_type = SchemaType(kinds={KIND_STRING})
        result.add_property(
            self.attribute_prefix + name, attribute_type, node.get("use") == "required"
        )

    def _simple_type(self, result: SchemaType, node: ElementTree.Element) -> None:
        for child in node:
            tag = child.tag.replace(XS, "")
            if tag == "restriction":
                base = child.get("base")
                if base:
                    base_type = self._named_type(base)
                else:
                    base_type = SchemaType()
                    inline = child.find(XS + "simpleType")
                    if inline is not None:
                        self._simple_type(base_type, inline)
                self._copy_simple(result, base_type)
                self._facets(result, child)
            elif tag == "list":
                result.kinds = {KIND_STRING}
            elif tag == "union":
                members = [
                    self._named_type(name)
                    for name in (child.get("memberTypes") or "").split()
                ]
                for inline in child.findall(XS + "simpleType"):
                    member = SchemaType()
                    self._simple_type(member, inline)
                    members.append(member)
                result.variants = members

    @staticmethod
    def _copy_simple(target: SchemaType, source: SchemaType) -> None:
        target.kinds = set(source.kinds)
        target.enum = None if source.enum is None else list(source.enum)
        target.minimum = source.minimum
        target.maximum = source.maximum
        target.format = source.format
        target.variants = list(source.variants)

    def _facets(self, result: SchemaType, restriction: ElementTree.Element) -> None:
        convert = self._converter(result)
        values = [
            facet.get("value", "") for facet in restriction.findall(XS + "enumeration")
        ]
        if values:
            result.enum = [convert(value) for value in values]
        for facet in restriction:
            tag = facet.tag.replace(XS, "")
            value = facet.get("value")
            if value is None or result.kinds - {KIND_INTEGER, KIND_NUMBER}:
                continue
            number = convert(value)
            integer = result.kinds == {KIND_INTEGER}
            if tag == "minInclusive":
                result.minimum = number
            elif tag == "maxInclusive":
                result.maximum = number
            elif tag == "minExclusive" and integer:
                result.minimum = number + 1
            elif tag == "maxExclusive" and integer:
                result.maximum = number - 1

    @staticmethod
    def _converter(result: SchemaType) -> Callable[[str], Any]:
        if result.kinds == {KIND_INTEGER}:
            return int
        if result.kinds == {KIND_NUMBER}:
            return float
        if result.kinds == {KIND_BOOLEAN}:
            return lambda value: value.strip() in ("true", "1")
        return str
