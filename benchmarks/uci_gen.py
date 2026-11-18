"""
Schema-guided generator of realistic UCI v2.6 (message version 6.0) traffic,
in the xmltodict JSON mapping (attributes "@x", text "#text").

Each simulated source ("track") fixes a message *shape* once: which optional
members are present, IDs, labels, enum choices, small integers. Every update
then re-draws only the volatile values: floating-point numbers (kinematics,
covariances, confidences) and timestamps, which advance in time.
"""

import datetime
import math
import random
import uuid

from sjson.schema.model import (
    KIND_ARRAY, KIND_BOOLEAN, KIND_INTEGER, KIND_NULL, KIND_NUMBER, KIND_OBJECT,
    KIND_STRING,
)

WORDS = ["ALPHA", "BRAVO", "CHARLIE", "DELTA", "ECHO", "FOXTROT", "GOLF", "HOTEL",
         "VIPER", "EAGLE", "RAVEN", "HAWK", "COBRA", "SABER", "TALON", "STORM"]
EPOCH = datetime.datetime(2026, 11, 18, 16, 0, 0, tzinfo=datetime.timezone.utc)


class Shape:
    """A frozen message shape plus stable values, re-rendered per update."""

    def __init__(self, gen, schema, seed, optional_p):
        self.gen = gen
        self.rng = random.Random(seed)
        self.optional_p = optional_p
        self.smooth = False
        self.series = {}
        self.template = self._build(schema, "", 0, set())

    # The template is a tree of ("const", v) / ("num", lo, hi) / ("time",) /
    # ("obj", [(name, t)]) / ("arr", [t]) nodes.
    def _build(self, schema, name, depth, path):
        if depth > 16:
            raise RecursionError
        if schema.variants:
            choices = [v for v in schema.variants if v.kinds != {KIND_NULL}]
            return self._build(choices[0] if choices else schema, name, depth, path)
        if schema.enum:
            return ("const", self.rng.choice(schema.enum))
        kinds = set(schema.kinds) - {KIND_NULL}
        if not kinds:
            return ("const", self._word())
        kind = sorted(kinds)[0]
        if kind == KIND_OBJECT:
            members = []
            for prop in schema.properties.values():
                if id(prop.type) in path and not prop.required:
                    continue
                p = self.optional_p[min(depth, len(self.optional_p) - 1)]
                if prop.required or self.rng.random() < p:
                    try:
                        members.append((prop.name, self._build(
                            prop.type, prop.name, depth + 1, path | {id(schema)})))
                    except RecursionError:
                        if prop.required:
                            raise
            return ("obj", members)
        if kind == KIND_ARRAY:
            item = schema.items or schema
            count = 1 if self.rng.random() < 0.8 else 2
            return ("arr", [self._build(item, name, depth + 1, path)
                            for _ in range(count)])
        if kind == KIND_BOOLEAN:
            return ("const", self.rng.random() < 0.5)
        if kind == KIND_INTEGER:
            low = 0 if schema.minimum is None or schema.minimum < -1000 else schema.minimum
            high = schema.maximum if schema.maximum is not None else low + 1000
            high = min(high, low + 1000)
            return ("const", self.rng.randint(int(low), int(high)))
        if kind == KIND_NUMBER:
            low, high = schema.minimum, schema.maximum
            if low is None and high is None:
                low, high = -5000.0, 5000.0
            elif high is None:
                low, high = max(low, -100.0), max(low, 0) + 12000.0
            elif low is None:
                low = high - 10000.0
            return ("num", float(low), float(high))
        # strings
        if schema.format == "date-time":
            return ("time",)
        if schema.format == "date":
            return ("const", "2026-11-18")
        if name == "UUID":
            return ("const", str(uuid.UUID(int=self.rng.getrandbits(128), version=4)))
        if name == "SchemaVersion":
            return ("const", "002.6.0")
        if name == "DescriptiveLabel":
            return ("const", f"{self._word()}-{self.rng.randint(1, 99):02d}")
        if "Duration" in name or name.endswith("Time"):
            return ("const", f"PT{self.rng.randint(1, 120)}S")
        return ("const", self._word())

    def _word(self):
        return f"{self.rng.choice(WORDS)} {self.rng.randint(1, 9)}"

    def render(self, rng, when):
        return self._render(self.template, rng, when)

    def _render(self, node, rng, when):
        tag = node[0]
        if tag == "const":
            return node[1]
        if tag == "num":
            if not self.smooth:
                return rng.uniform(node[1], node[2])
            # Each number belongs to a time series: some are constant (fixed
            # configuration), the rest drift by a small random step per update.
            state = self.series.get(id(node))
            low, high = node[1], node[2]
            if state is None:
                state = [rng.uniform(low, high), 0.0 if rng.random() < 0.3 else (high - low) * 0.002]
                self.series[id(node)] = state
            elif state[1]:
                state[0] = min(high, max(low, state[0] + rng.gauss(0, state[1])))
            return state[0]
        if tag == "time":
            t = when + datetime.timedelta(milliseconds=rng.randint(-400, 0))
            return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"
        if tag == "obj":
            return {name: self._render(child, rng, when) for name, child in node[1]}
        return [self._render(child, rng, when) for child in node[1]]


class UciTraffic:
    def __init__(self, model, seed=7):
        self.model = model
        self.seed = seed

    def message_type(self, name):
        return self.model.root.properties[name].type

    def track_stream(self, message, sources, updates, optional_p=(1, 0.45, 0.3, 0.2, 0.1, 0.0)):
        """``sources`` tracks, each reporting ``updates`` times, interleaved."""
        shapes = [Shape(self, self.message_type(message), self.seed * 1000 + i, optional_p)
                  for i in range(sources)]
        rng = random.Random(self.seed)
        out = []
        for step in range(updates):
            when = EPOCH + datetime.timedelta(seconds=step)
            for shape in shapes:
                out.append({message: shape.render(rng, when)})
        return out

    def mixed_stream(self, count_types, per_type, optional_p=(1, 0.4, 0.25, 0.15, 0.0)):
        rng = random.Random(self.seed)
        names = sorted(self.model.root.properties)
        chosen = rng.sample(names, count_types)
        out = []
        for i, name in enumerate(chosen):
            try:
                shape = Shape(self, self.message_type(name), self.seed + i, optional_p)
            except RecursionError:
                continue
            for k in range(per_type):
                out.append({name: shape.render(rng, EPOCH + datetime.timedelta(seconds=k))})
        rng.shuffle(out)
        return out
