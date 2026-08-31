"""``musil.doctor.scan`` — pin the advisory matchers on known source snippets (source -> expected finding),
the doctor's analog of the model corpus. Pure ast, so these are exact and stable."""

from __future__ import annotations

from musil import scan


def test_scan_flags_the_three_hand_rolled_patterns() -> None:
    src = (
        "def test_it():\n"
        "    r = check(m)\n"
        "    assert r.ok, str(r)\n"  # -> assert_ok
        "    names = [step.action for step in r.trace if step.action]\n"  # -> action_names
        "    bad = check(other)\n"
        "    assert not bad.ok\n"  # -> assert_violates
    )
    found = {(f.line, f.pattern) for f in scan(src)}
    assert (3, "assert-ok") in found
    assert (4, "action-names") in found
    assert (6, "assert-violates") in found
    assert len(found) == 3


def test_scan_does_not_flag_a_bare_ok_assert_or_clean_usage() -> None:
    # A bare `assert x.ok` (no message) is left alone — it is as likely `requests`' response.ok as a musil
    # result, and the message is what marks the musil idiom. Code already using the shipped APIs is clean.
    src = (
        "def test_ok():\n"
        "    assert response.ok\n"  # bare truthiness, not the `, str(r)` idiom
        "    assert_ok(check(m))\n"
        "    assert_violates(check(bad), kind='deadlock')\n"
        "    ns = r.action_names\n"
    )
    assert scan(src) == []


def test_scan_renders_the_subject_expression() -> None:
    # The suggestion names the actual subject, however it is written.
    (finding,) = scan("assert check_liveness(m, goal=g).ok, 'nope'\n")
    assert finding.pattern == "assert-ok"
    assert "assert_ok(check_liveness(m, goal=g))" in finding.message
