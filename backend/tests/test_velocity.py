from __future__ import annotations

from app.velocity import validate_velocity


def test_repeating_existing_url_variables_is_reviewable_but_not_invented():
    original = '<a href="$registrationUrl">Registrarse</a>'
    result = (
        '<a href="$registrationUrl">Registrarse</a>'
        '<p>Si el botón no funciona: <a href="$registrationUrl">$registrationUrl</a></p>'
    )
    report = validate_velocity(original, result)
    assert report.missing_variables == []
    assert report.added_variables == []
    assert report.repeated_variables == ["$registrationUrl", "$registrationUrl"]
    assert report.suspicious is True


def test_new_variable_name_remains_unsafe():
    report = validate_velocity("<p>$name</p>", "<p>$name</p><a href='$inventedUrl'>Abrir</a>")
    assert report.added_variables == ["$inventedUrl"]
    assert report.repeated_variables == []


def test_missing_original_occurrence_remains_unsafe():
    report = validate_velocity("<p>$name $name</p>", "<p>$name</p>")
    assert report.missing_variables == ["$name"]


def test_reordered_velocity_directives_are_unsafe_even_when_counts_match():
    original = "#if($first)A#else B#end #if($second)C#end"
    reordered = "#if($second)C#end #if($first)A#else B#end"

    report = validate_velocity(original, reordered)

    assert report.missing_directives == []
    assert report.added_directives == []
    assert report.directive_order_changed is True
    assert report.suspicious is True


def test_formal_braced_directives_are_recognized_and_must_not_be_normalized():
    original = "#if($approved)A#{else}B#end"
    normalized = "#if($approved)A#else B#end"

    report = validate_velocity(original, normalized)

    assert report.original_directives == ["#if($approved)", "#{else}", "#end"]
    assert report.missing_directives == ["#{else}"]
    assert report.added_directives == ["#else"]
    assert report.suspicious is True


def test_variable_brace_notation_remains_literal():
    report = validate_velocity("$reviewerComment", "${reviewerComment}")

    assert report.missing_variables == ["$reviewerComment"]
    assert report.added_variables == ["${reviewerComment}"]
