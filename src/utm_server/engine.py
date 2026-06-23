"""The ``validate_and_normalize`` engine — the mandatory last hop for any link.

Given an arbitrary URL and a parsed :class:`~utm_server.spec.Spec`, this
normalizes every UTM parameter and validates it with the per-field behavior
asymmetry the spec declares:

* ``utm_source``  (open enum)   — unknown value: emit the normalized link **plus
  a nudge** to add the source to the spec repo.
* ``utm_medium``  (closed enum) — unknown value: **hard refuse** with the valid
  set and the closest suggestion; never emit a link.
* ``utm_campaign`` (sheet)      — must match the naming template; a malformed
  name **hard-errors**. Membership in the campaign registry is checked only when
  ``known_campaigns`` is supplied (wired in a later issue); until then this is a
  shape check.
* ``utm_content`` / ``utm_term`` (free) — always shape-normalized, never refused.

Soft outcomes (the normalized link + a changelog + nudges) are returned as a
:class:`ValidationResult`. Hard outcomes raise :class:`ValidationRefused` so a
refused link is never accidentally emitted.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .spec import UTM_PARAMS, Spec, normalize_campaign, normalize_value


class ValidationRefused(Exception):
    """A link was hard-refused: a closed-enum or campaign rule was violated.

    Raised instead of returning a result so the offending link is never emitted.
    The message is agent-facing and includes the valid values and/or the closest
    suggestion where applicable.
    """


@dataclass(frozen=True)
class Fixup:
    """One normalization change applied to a parameter value.

    Attributes:
        param: The (normalized, lowercase) parameter name.
        original: The value as it appeared in the input URL.
        normalized: The value after normalization.
    """

    param: str
    original: str
    normalized: str


@dataclass(frozen=True)
class ValidationResult:
    """The outcome of a successful (emit) validation pass.

    Attributes:
        url: The normalized URL, safe to emit.
        changelog: The list of value fixups that were applied.
        nudges: Soft, non-blocking advisories (e.g. an unknown ``utm_source``).
    """

    url: str
    changelog: list[Fixup] = field(default_factory=list)
    nudges: list[str] = field(default_factory=list)


def validate_and_normalize(
    url: str,
    spec: Spec,
    known_campaigns: set[str] | None = None,
) -> ValidationResult:
    """Normalize and validate every UTM parameter on ``url`` end-to-end.

    Args:
        url: The (possibly messy) URL to normalize and validate.
        spec: The parsed authoritative spec driving all behavior.
        known_campaigns: Optional set of registered campaign names. When given,
            a well-formed campaign that is not a member is refused; when ``None``
            (registry not yet wired) only the campaign's shape is checked.

    Returns:
        A :class:`ValidationResult` with the normalized URL, the changelog of
        fixups, and any soft nudges.

    Raises:
        ValidationRefused: On a hard-refuse condition — unknown ``utm_medium``,
            a malformed/unknown ``utm_campaign``, or a missing required
            parameter. No URL is produced in these cases.
    """
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)

    changelog: list[Fixup] = []
    nudges: list[str] = []
    out_pairs: list[tuple[str, str]] = []
    seen: set[str] = set()

    for key, value in pairs:
        canonical = key.lower()
        if canonical not in UTM_PARAMS:
            out_pairs.append((key, value))  # leave non-UTM params untouched
            continue

        seen.add(canonical)
        normalized = _normalize_for(canonical, value, spec)
        if normalized != value or key != canonical:
            changelog.append(Fixup(param=canonical, original=value, normalized=normalized))

        _validate(canonical, normalized, spec, known_campaigns, nudges)
        out_pairs.append((canonical, normalized))

    _require_present(spec, seen)

    new_query = urlencode(out_pairs)
    normalized_url = urlunsplit(parts._replace(query=new_query))
    return ValidationResult(url=normalized_url, changelog=changelog, nudges=nudges)


def _normalize_for(param: str, value: str, spec: Spec) -> str:
    if param == "utm_campaign":
        return normalize_campaign(value, spec.separator)
    return normalize_value(value, spec.separator)


def _validate(
    param: str,
    normalized: str,
    spec: Spec,
    known_campaigns: set[str] | None,
    nudges: list[str],
) -> None:
    """Apply the spec's per-field behavior to a single normalized value.

    Mutates ``nudges`` for soft outcomes; raises :class:`ValidationRefused` for
    hard ones.
    """
    pspec = spec.parameter(param)

    if param == "utm_campaign":
        _validate_campaign(pspec, normalized, known_campaigns)
        return

    if pspec.enum_type in ("closed", "open"):
        if normalized in pspec.values:
            return
        if pspec.on_unknown == "refuse":  # closed enum (utm_medium)
            raise ValidationRefused(_refuse_enum_message(param, normalized, pspec.values))
        if pspec.on_unknown == "emit_and_nudge":  # open enum (utm_source)
            nudges.append(_nudge_message(param, normalized, pspec.values))
        return

    # Free-form (utm_content / utm_term): normalization already enforced shape.
    if pspec.shape_regex and not re.match(pspec.shape_regex, normalized):
        # Should be unreachable for a non-empty value after normalization, but
        # guard against a spec whose shape disagrees with normalization output.
        raise ValidationRefused(
            f"{param}={normalized!r} doesn't match the required shape "
            f"{pspec.shape_regex!r} after normalization — contact the admin."
        )


def _validate_campaign(pspec, normalized: str, known_campaigns: set[str] | None) -> None:
    if pspec.template_regex and not re.match(pspec.template_regex, normalized):
        raise ValidationRefused(
            f"utm_campaign={normalized!r} is not a valid campaign name. It must "
            f"match the template {pspec.template_regex!r} (e.g. "
            "'2026-q2_agent-launch'). Create it with add_campaign, then retry."
        )
    if known_campaigns is not None and normalized not in known_campaigns:
        suggestion = _closest(normalized, known_campaigns)
        hint = f" Did you mean {suggestion!r}?" if suggestion else ""
        raise ValidationRefused(
            f"utm_campaign={normalized!r} is not in the campaign registry.{hint} "
            "Add it with add_campaign, then retry."
        )


def _require_present(spec: Spec, seen: set[str]) -> None:
    missing = [
        name
        for name in UTM_PARAMS
        if spec.parameter(name).required and name not in seen
    ]
    if missing:
        raise ValidationRefused(
            "The link is missing required UTM parameter(s): "
            f"{', '.join(missing)}. A valid link must include them."
        )


def _refuse_enum_message(param: str, value: str, values: tuple[str, ...]) -> str:
    suggestion = _closest(value, set(values))
    hint = f" Closest match: {suggestion!r}." if suggestion else ""
    valid = ", ".join(values)
    return (
        f"{param}={value!r} is not a valid value and was refused — no link was "
        f"produced.{hint} Valid {param} values are: {valid}."
    )


def _nudge_message(param: str, value: str, values: tuple[str, ...]) -> str:
    valid = ", ".join(values)
    return (
        f"{param}={value!r} is not a known value. The link was still produced, "
        f"but consider adding {value!r} to the spec repo via PR if it is a "
        f"genuine new {param}. Known values: {valid}."
    )


def _closest(value: str, candidates: set[str]) -> str | None:
    matches = difflib.get_close_matches(value, candidates, n=1, cutoff=0.6)
    return matches[0] if matches else None
