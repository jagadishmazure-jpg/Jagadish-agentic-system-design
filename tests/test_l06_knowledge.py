import pytest

from harrowgate.knowledge import FaqRetriever, KnowledgeGraph, choose_store, gate_change_impact
from harrowgate.scenarios import FAQ_SET, STORE_SET


def test_graph_walk_gate_to_makeup_area(world):
    kg = KnowledgeGraph.from_world(world)
    assert kg.walk("SK204", ["DEPARTS_FROM", "IN_PIER", "SERVED_BY"]) == ["SK204", "B4", "PIER-B", "MU-B"]


def test_walk_stops_where_chain_breaks(world):
    kg = KnowledgeGraph.from_world(world)
    assert kg.walk("SK204", ["DEPARTS_FROM", "FLIES_TO"]) == ["SK204", "B4"]


def test_gate_change_impact_says_move_when_pier_changes(world):
    world.flights["SK204"]["gate"] = "C2"
    impact = gate_change_impact(KnowledgeGraph.from_world(world), "P-1001", now=520, dep=600)
    assert impact[0]["status"] == "move" and impact[0]["to"] == "MU-C"


def test_gate_change_impact_too_late_after_cutoff(world):
    world.flights["SK204"]["gate"] = "A1"
    impact = gate_change_impact(KnowledgeGraph.from_world(world), "P-1001", now=570, dep=600)
    assert impact[0]["status"] == "too_late"


def test_same_pier_gate_change_needs_no_move(world):
    world.flights["SK204"]["gate"] = "B6"
    assert gate_change_impact(KnowledgeGraph.from_world(world), "P-1001", 520, 600)[0]["status"] == "ok"


@pytest.mark.parametrize("question,store", [
    ("My gate changed, what about my bag?", "graph"),
    ("What gate is SK204?", "database"),
    ("Can I take a power bank?", "retrieval"),
])
def test_store_choice_by_question_shape(question, store):
    assert choose_store(question)[0] == store


def test_store_choice_regression_set_has_one_known_miss():
    misses = [q for q, e in STORE_SET if choose_store(q)[0] != e]
    assert misses == ["Is my plane leaving on time?"]  # 'plane' is not in the entity word list


def test_faq_retrieval_regression_set_has_one_known_miss():
    r = FaqRetriever()
    misses = [q for q, e in FAQ_SET if r.search(q, 1)[0]["id"] != e]
    assert misses == ["How do I connect to the wifi?"]  # 'Wi-Fi' tokenises to 'wi' + 'fi'


def test_retriever_scores_are_sorted():
    hits = FaqRetriever().search("liquids security", 3)
    assert [h["score"] for h in hits] == sorted([h["score"] for h in hits], reverse=True)
