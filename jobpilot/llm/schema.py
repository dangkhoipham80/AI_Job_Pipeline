"""Turning one Pydantic schema into the dialect each provider will accept.

Pydantic emits a schema with nested models hoisted into ``$defs`` and referenced
by ``$ref``. The three providers disagree about that, and about optional fields,
in ways that are cheap to fix here and expensive to discover at request time:

* **Anthropic** — the SDK takes the model class and handles it.
* **OpenAI** strict mode — supports ``$ref``, but requires every object to set
  ``additionalProperties: false`` and to list *every* property in ``required``.
* **Gemini** — documents only a subset of JSON Schema and warns that large or
  deeply nested schemas may be rejected; ``$defs`` with several definitions is
  not among the documented features. Flattening is the safe reading.

Keeping both transforms in one file is deliberate: they are two answers to the
same question, and a provider added later needs to pick one rather than invent
a third quietly.
"""

from __future__ import annotations

from typing import Any


def flatten_schema(schema: dict) -> dict:
    """Inline ``$ref``/``$defs`` so the reader sees one plain tree.

    Written for Ollama's grammar compiler, kept for Gemini, which has the same
    weak spot: references are the shakiest corner of schema-to-grammar, and a
    schema that fails to compile reports a problem with the grammar rather than
    with the model. Inlining costs nothing here — these schemas are small, two
    levels deep, and non-recursive by construction.
    """
    defs = schema.get("$defs") or {}

    def resolve(node: Any, seen: frozenset[str]) -> Any:
        if isinstance(node, list):
            return [resolve(n, seen) for n in node]
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            name = ref.split("/")[-1]
            if name in seen:
                # Recursive schema — leave the ref alone rather than expand it
                # forever. None of ours are, so this is a guard, not a path.
                return node
            target = defs.get(name)
            if target is None:
                return node
            return resolve(target, seen | {name})
        return {k: resolve(v, seen) for k, v in node.items() if k != "$defs"}

    return resolve({k: v for k, v in schema.items() if k != "$defs"}, frozenset())


def strictify(schema: dict) -> dict:
    """Make a Pydantic schema satisfy OpenAI strict mode.

    Two rules, applied to every object anywhere in the tree:

    1. ``additionalProperties: false``.
    2. every declared property listed in ``required``.

    Rule 2 reads like it forbids optional fields, and it doesn't: strict mode's
    position is that a field is always *present*, and "absent" is spelled by
    allowing ``null``. So a property Pydantic left out of ``required`` gets
    widened to accept null rather than dropped — otherwise a plan that legally
    omits ``summary`` would become impossible to express, and the model would be
    forced to invent one. That is the failure mode this whole repo is built
    against, so it is worth the extra branch.
    """

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(n) for n in node]
        if not isinstance(node, dict):
            return node

        out = {k: walk(v) for k, v in node.items()}
        props = out.get("properties")
        if isinstance(props, dict):
            out["additionalProperties"] = False
            required = list(out.get("required") or [])
            for name in props:
                if name not in required:
                    props[name] = _nullable(props[name])
                    required.append(name)
            out["required"] = required
        return out

    return walk(schema)


def _nullable(node: Any) -> Any:
    """Widen one property so ``null`` is a legal value for it."""
    if not isinstance(node, dict):
        return node
    if "anyOf" in node:
        branches = node["anyOf"]
        if any(isinstance(b, dict) and b.get("type") == "null" for b in branches):
            return node
        return {**node, "anyOf": [*branches, {"type": "null"}]}
    kind = node.get("type")
    if isinstance(kind, str) and kind != "null":
        return {**node, "type": [kind, "null"]}
    if isinstance(kind, list) and "null" not in kind:
        return {**node, "type": [*kind, "null"]}
    return node
