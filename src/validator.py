"""Validates model predictions against the module's closed value lists."""

from __future__ import annotations

from .data_loader import normalise_name, normalise_value


def is_closed(characteristic) -> bool:
    return str(characteristic.get("open_close", "")).strip().lower().startswith("close")


def validate(prediction, context, dataset=None):
    """Return (accepted, errors, warnings).

    `accepted` maps the exact output column name -> value, so it can be written
    straight into the sample_output layout. Values that violate a closed list are
    dropped, not passed through.
    """
    taxonomy = {normalise_name(c["characteristic"]): c for c in context["characteristics"]}
    allowed = {
        key: {normalise_value(v) for v in c["possible_values"]}
        for key, c in taxonomy.items()
    }

    accepted, errors, warnings = {}, [], []
    answered = set()

    for raw_key, raw_value in (prediction.get("characteristics") or {}).items():
        key = normalise_name(raw_key)
        value = str(raw_value).strip()

        if not value:
            warnings.append(f"Empty value for {raw_key!r}; skipped")
            continue

        characteristic = taxonomy.get(key)

        if characteristic is None:
            # Not part of this module's taxonomy. If it is still a real output
            # column (e.g. GLOBAL_FLAVOUR_FRAGRANCE_INGREDIENT, which has no
            # char_value_list entry) keep it as free text, otherwise drop it.
            column = dataset.output_column_for(raw_key) if dataset else None
            if column:
                accepted[column] = value
                warnings.append(
                    f"{raw_key!r} is not in the taxonomy for this module; "
                    "accepted as open-ended"
                )
            else:
                errors.append(f"Unknown characteristic {raw_key!r}; dropped")
            continue

        answered.add(key)

        column = characteristic.get("output_column")
        if not column:
            errors.append(
                f"{characteristic['characteristic']!r} has no matching output column; dropped"
            )
            continue

        if is_closed(characteristic) and normalise_value(value) not in allowed[key]:
            errors.append(
                f"Invalid closed value for {characteristic['characteristic']!r}: "
                f"{value!r}; allowed={characteristic['possible_values']}; dropped"
            )
            continue

        accepted[column] = value

    for key, characteristic in taxonomy.items():
        if key not in answered:
            warnings.append(
                f"No prediction returned for {characteristic['characteristic']!r}"
            )

    return accepted, errors, warnings
