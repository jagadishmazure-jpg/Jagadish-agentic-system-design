import pytest

from harrowgate.identity import AccessDenied, AgentIdentity, TokenIssuer, check_ownership

AGENT = AgentIdentity("retail-agent", frozenset({"read", "write"}))
READER = AgentIdentity("faq-agent", frozenset({"read"}))


def test_token_names_actor_subject_scope_and_expires():
    iss = TokenIssuer()
    tok = iss.mint(AGENT, "C-101", {"read"}, now=100, ttl=15)
    claims = iss.verify(tok, scope="read", now=110)
    assert claims["act"] == "retail-agent" and claims["sub"] == "C-101" and claims["scp"] == ["read"]
    with pytest.raises(AccessDenied, match="expired"):
        iss.verify(tok, scope="read", now=116)


def test_scope_cannot_exceed_what_the_agent_holds():
    iss = TokenIssuer()
    tok = iss.mint(READER, "C-1", {"read", "write"}, now=0)
    with pytest.raises(AccessDenied, match="scope write"):
        iss.verify(tok, scope="write", now=1)


def test_tampered_or_foreign_tokens_are_rejected():
    iss, other = TokenIssuer(), TokenIssuer()
    tok = iss.mint(AGENT, "C-1", {"read"}, now=0)
    with pytest.raises(AccessDenied, match="bad signature"):
        other.verify(tok, scope="read", now=1)
    with pytest.raises(AccessDenied, match="malformed"):
        iss.verify("not-a-token", scope="read", now=1)
    with pytest.raises(AccessDenied, match="audience"):
        iss.verify(tok, scope="read", now=1, audience="billing")


def test_delegation_only_narrows_and_keeps_the_chain():
    iss = TokenIssuer()
    parent = iss.mint(AGENT, "C-1", {"read", "write"}, now=0, ttl=10)
    child = iss.delegate(parent, AgentIdentity("helper", frozenset({"read", "write", "admin"})), {"read", "admin"},
                         now=2)
    c = iss.verify(child, scope="read", now=3)
    assert c["scp"] == ["read"] and c["sub"] == "C-1" and c["chain"] == ["retail-agent", "helper"]
    assert c["exp"] == 10


def test_ownership_check_stops_the_confused_deputy():
    check_ownership({"sub": "C-1"}, "C-1")
    check_ownership({"sub": "C-1"}, None)
    with pytest.raises(AccessDenied, match="someone else"):
        check_ownership({"sub": "C-1"}, "C-2")
