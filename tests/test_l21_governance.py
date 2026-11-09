from harrowgate.governance import (
    AuditLog,
    ResidencyPolicy,
    explain,
    find_pii,
    handoff_note,
    luhn_ok,
    mask,
    minimum_necessary,
    purge_expired,
)


def test_luhn_separates_real_card_shapes_from_random_digits():
    assert luhn_ok("4111 1111 1111 1111") and luhn_ok("3782 822463 10005")
    assert not luhn_ok("1234 5678 9012 3456") and not luhn_ok("12345")


def test_mask_keeps_last_four_and_hides_record_numbers_and_contacts():
    out = mask("card 4111 1111 1111 1111, MRN-401001, c-1@mail.example, +1 555 010 0701, ACCT-20010001")
    assert out == "card card ending 1111, [record], [email], [phone], account ending 0001"
    assert mask("order 1234 5678 9012 3456") == "order 1234 5678 9012 3456"  # fails Luhn, not a card


def test_find_pii_names_each_kind():
    assert find_pii("MRN-123456 and 123-45-6789") == ["ssn", "mrn"]
    assert find_pii("nothing here") == []


def test_minimum_necessary_removes_protected_attributes():
    kept, removed = minimum_necessary({"status": "locked", "age": 41, "sex": "F", "days": 7}, {"status", "days"})
    assert kept == {"status": "locked", "days": 7} and removed == ["age", "sex"]


def test_audit_chain_detects_edits_and_deletions():
    log = AuditLog()
    for i in range(4):
        log.append(rule=f"R{i}", outcome="allow")
    assert log.verify() is None
    log.entries[1]["body"]["outcome"] = "deny"
    assert log.verify() == 2
    log2 = AuditLog()
    for i in range(3):
        log2.append(rule=f"R{i}")
    del log2.entries[1]
    assert log2.verify() == 3


def test_residency_and_retention():
    pol = ResidencyPolicy({"healthcare": frozenset({"uk-south"})})
    assert pol.check("healthcare", "uk-south") and not pol.check("healthcare", "us-east")
    recs = {"a": {"closed_at": 0}, "b": {"closed_at": 90}, "c": {}}
    assert purge_expired(recs, now=100, retention=30) == ["a"] and set(recs) == {"b", "c"}


def test_explanation_and_handoff_note_are_masked_and_complete():
    e = explain("RT4-review", "amount 240 needs the store manager", {"total": 240, "status": "delivered"}, "mgr", "allow")
    assert e["facts_used"] == ["status", "total"] and e["approver"] == "mgr"
    note = handoff_note("retail", "C-101", "action", ["return label"], ["refund"], "card 4111 1111 1111 1111 failed")
    assert "card ending 1111" in note and "4111 1111" not in note and "waiting: refund" in note
