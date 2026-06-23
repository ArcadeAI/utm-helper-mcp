"""Parse and model the authoritative ``utm-spec.yaml``.

This module turns the structured spec file (see the top of ``utm-spec.yaml`` for
the parser contract) into a small, typed in-memory model plus the deterministic
normalization the engine applies to every parameter value. Tools read behavior
from *here* — parsed from the spec — and never hard-code enums or rules.

Parsing is fail-loud: a missing/blank/malformed spec raises
:class:`SpecParseError` rather than degrading to built-in defaults, mirroring the
fail-loud contract for spec *fetching* in :mod:`utm_server.sources`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

#: The structured, machine-readable spec served alongside the human guide.
SPEC_FILENAME = "utm-spec.yaml"

#: The UTM parameters this server governs, in canonical link order.
UTM_PARAMS: tuple[str, ...] = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
)


class SpecParseError(Exception):
    """The spec file could not be parsed into a valid :class:`Spec`.

    The message is admin-facing: it names what was wrong with the spec so a
    misconfigured/garbled source is fixed rather than silently tolerated.
    """


@dataclass(frozen=True)
class ParameterSpec:
    """The rules for one UTM parameter, as declared in the spec.

    Attributes:
        name: The parameter name (e.g. ``utm_medium``).
        store: Where the authoritative values live (``git`` or ``sheet``).
        required: Whether a link must carry this parameter.
        enum_type: ``closed``/``open``/``free`` (or ``None`` for campaign,
            which is governed by a template rather than an enum).
        on_unknown: Behavior when a value is not recognized — ``refuse``,
            ``emit_and_nudge``, or ``normalize``.
        values: The enum values (for git-stored enum params).
        shape_regex: Anchored regex a normalized free-form value must match.
        template_regex: Anchored regex a normalized campaign name must match.
    """

    name: str
    store: str
    required: bool
    enum_type: str | None
    on_unknown: str | None
    values: tuple[str, ...]
    shape_regex: str | None
    template_regex: str | None


@dataclass(frozen=True)
class Spec:
    """The parsed UTM spec: global normalization + per-parameter rules.

    Attributes:
        version: Integer schema version of the spec file.
        separator: Canonical in-value word separator (e.g. ``-``).
        parameters: Map of parameter name -> :class:`ParameterSpec`.
    """

    version: int
    separator: str
    parameters: dict[str, ParameterSpec]

    def parameter(self, name: str) -> ParameterSpec:
        """Return the :class:`ParameterSpec` for ``name`` (KeyError if absent)."""
        return self.parameters[name]


def parse_spec(text: str) -> Spec:
    """Parse the raw text of ``utm-spec.yaml`` into a :class:`Spec`.

    Raises:
        SpecParseError: If the YAML is invalid, the top level is not a mapping,
            the normalization block is missing, or any of the five governed UTM
            parameters is absent or malformed.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SpecParseError(
            f"The UTM spec ({SPEC_FILENAME}) is not valid YAML: {exc}. "
            "The spec source may be corrupt — contact the admin."
        ) from exc

    if not isinstance(data, dict):
        raise SpecParseError(
            f"The UTM spec ({SPEC_FILENAME}) must be a YAML mapping at the top "
            "level — contact the admin."
        )

    version = _require_int(data, "version")
    separator = _parse_separator(data)
    parameters = _parse_parameters(data)
    return Spec(version=version, separator=separator, parameters=parameters)


def _parse_separator(data: dict) -> str:
    normalization = data.get("normalization")
    if not isinstance(normalization, dict):
        raise SpecParseError(
            f"The UTM spec ({SPEC_FILENAME}) is missing the 'normalization' "
            "block — contact the admin."
        )
    separator = normalization.get("separator", "-")
    if not isinstance(separator, str) or len(separator) != 1:
        raise SpecParseError(
            f"The UTM spec ({SPEC_FILENAME}) declares an invalid "
            f"'normalization.separator' ({separator!r}); it must be a single "
            "character — contact the admin."
        )
    return separator


def _parse_parameters(data: dict) -> dict[str, ParameterSpec]:
    raw = data.get("parameters")
    if not isinstance(raw, dict):
        raise SpecParseError(
            f"The UTM spec ({SPEC_FILENAME}) is missing the 'parameters' block "
            "— contact the admin."
        )

    parameters: dict[str, ParameterSpec] = {}
    for name in UTM_PARAMS:
        block = raw.get(name)
        if not isinstance(block, dict):
            raise SpecParseError(
                f"The UTM spec ({SPEC_FILENAME}) is missing the required "
                f"parameter '{name}' — contact the admin."
            )
        parameters[name] = _parse_parameter(name, block)
    return parameters


def _parse_parameter(name: str, block: dict) -> ParameterSpec:
    values = block.get("values", [])
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise SpecParseError(
            f"The UTM spec ({SPEC_FILENAME}) declares non-string 'values' for "
            f"'{name}' — contact the admin."
        )
    return ParameterSpec(
        name=name,
        store=str(block.get("store", "git")),
        required=bool(block.get("required", False)),
        enum_type=_opt_str(block, "enum_type"),
        on_unknown=_opt_str(block, "on_unknown"),
        values=tuple(values),
        shape_regex=_opt_str(block, "shape_regex"),
        template_regex=_opt_str(block, "template_regex"),
    )


def _require_int(data: dict, key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int):
        raise SpecParseError(
            f"The UTM spec ({SPEC_FILENAME}) is missing an integer '{key}' "
            "— contact the admin."
        )
    return value


def _opt_str(block: dict, key: str) -> str | None:
    value = block.get(key)
    return value if isinstance(value, str) else None


# -----------------------------------------------------------------------------
# Normalization — the deterministic transform applied before validation.
#
# Mirrors normalization.steps in the spec, in order. It is idempotent:
# normalize(normalize(x)) == normalize(x), which is what makes the engine's
# "mandatory last hop" safe to apply to already-clean links.
# -----------------------------------------------------------------------------


def normalize_value(value: str, separator: str = "-") -> str:
    """Normalize a free-form UTM value to ``[a-z0-9]+(-[a-z0-9]+)*`` form.

    Steps (per the spec): trim, lowercase, spaces -> separator,
    underscores -> separator, drop chars outside ``[a-z0-9<sep>]``, collapse
    repeated separators, then trim leading/trailing separators.
    """
    sep = re.escape(separator)
    s = value.strip().lower()
    s = re.sub(r"\s+", separator, s)                  # spaces_to_separator
    s = s.replace("_", separator)                     # underscores_to_separator
    s = re.sub(rf"[^a-z0-9{sep}]+", "", s)            # strip_invalid_chars
    s = re.sub(rf"{sep}{{2,}}", separator, s)         # collapse_separators
    return s.strip(separator)                          # trim_separators


def normalize_campaign(value: str, separator: str = "-") -> str:
    """Normalize a campaign name, preserving the one structural ``_``.

    A campaign name is ``<YYYY>-q<N>_<kebab-slug>``: the underscore between the
    date-quarter prefix and the slug is structural and must survive
    normalization, while everything on either side is normalized as a normal
    free-form value. Names with no underscore are normalized whole (and will
    then fail template validation, which is the intended signal).
    """
    s = value.strip().lower()
    if "_" not in s:
        return normalize_value(s, separator)
    head, tail = s.split("_", 1)
    return f"{normalize_value(head, separator)}_{normalize_value(tail, separator)}"
