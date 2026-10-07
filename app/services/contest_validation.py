"""Validate all contest fields before mutating rows or scheduling tasks."""

import re
from datetime import datetime, timezone

from app.services.validation import InputError


FIELDS = {
    "startTime": "start_time", "endTime": "end_time", "votingEndTime": "voting_end_time",
    "advancementNumerator": "advancement_numerator", "advancementDenominator": "advancement_denominator",
}


def _invalid(field):
    raise InputError(f"Invalid field: {field}")


def _integer(value, field, minimum):
    if type(value) is int:
        result = value
    elif isinstance(value, str) and re.fullmatch(r"[+-]?[0-9]+", value):
        try:
            result = int(value)
        except ValueError:
            _invalid(field)
    else:
        _invalid(field)
    if not minimum <= result < 2**31:
        _invalid(field)
    return result


def _date(value, field):
    if not isinstance(value, str):
        _invalid(field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        _invalid(field)


def validate_contest(data, contest=None):
    if not isinstance(data, dict):
        raise InputError("Expected a JSON object")
    normalized = dict(data)
    if contest is None:
        for field in ("name", "startTime", "endTime", "votingEndTime"):
            if field not in data:
                _invalid(field)
    for field, value in data.items():
        base = field[9:10].lower() + field[10:] if field.startswith("qualifier") else field
        if base in {"hasTheme", "hasQualifier", "isVotingVisible", "judgeAwardAdvancement"}:
            if type(value) is not bool:
                _invalid(field)
        elif base in {"name", "theme", "judgePassword", "resultCommentTop", "resultCommentBottom"}:
            if value is None and base != "name":
                continue
            if not isinstance(value, str) or (base == "name" and (not value.strip() or len(value) > 120)):
                _invalid(field)
            if base == "judgePassword" and len(value) > 120:
                _invalid(field)
        elif base in {"generalVoteWeight", "judgeMaxScore", "advancementNumerator", "advancementDenominator"}:
            if base.startswith("advancement") and value in (None, ""):
                normalized[field] = None
                continue
            minimum = 1 if base in {"judgeMaxScore", "advancementDenominator"} else 0
            normalized[field] = _integer(value, field, minimum)
        elif base in {"startTime", "endTime", "votingEndTime"}:
            if field.startswith("qualifier") and value in (None, ""):
                continue
            normalized[field] = _date(value, field).isoformat()
        elif base in {"type", "scoringMethod", "imageRule"}:
            allowed = {
                "type": {"grandprix", "daily"},
                "scoringMethod": {"user", "judge", "both", "general"},
                "imageRule": {"none", "required", "optional", "forbidden"},
            }[base]
            if not isinstance(value, str) or value not in allowed:
                _invalid(field)
            # The legacy general label used combined judge and user scoring.
            normalized[field] = {"forbidden": "none", "general": "both"}.get(value, value)

    if contest is None and normalized.get("hasQualifier") and len(normalized["name"]) + len(" 予選") > 120:
        _invalid("name")

    times = []
    for field in ("startTime", "endTime", "votingEndTime"):
        value = normalized.get(field)
        times.append(_date(value, field) if value is not None else getattr(contest, FIELDS[field], None))
    if contest is None or any(field in data for field in ("startTime", "endTime", "votingEndTime")):
        times = [value.replace(tzinfo=timezone.utc) for value in times]
        if not times[0] < times[1] < times[2]:
            _invalid("period")
    if normalized.get("hasQualifier"):
        qt = [_date(normalized.get("qualifier" + field) or times[index].isoformat(), "qualifier" + field)
              for index, field in enumerate(("StartTime", "EndTime", "VotingEndTime"))]
        if not qt[0] < qt[1] < qt[2]:
            _invalid("qualifierPeriod")
    numerator = normalized.get("advancementNumerator", getattr(contest, "advancement_numerator", None))
    denominator = normalized.get("advancementDenominator", getattr(contest, "advancement_denominator", None))
    if numerator is not None and denominator is not None and numerator > denominator:
        _invalid("advancementNumerator")
    return normalized
