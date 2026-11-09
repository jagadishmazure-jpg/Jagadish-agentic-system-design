import pytest

from harrowgate import world as W


def test_shortest_route_uses_train_to_pier_c():
    path, minutes = W.shortest_route("PLAZA", "C3")
    assert path[:3] == ["PLAZA", "TRAIN-PLAZA", "TRAIN-C"] and minutes == 14


def test_route_minutes_matches_dijkstra_and_rejects_fake_corridors():
    path, minutes = W.shortest_route("ENTRANCE", "A4")
    assert W.route_minutes(path) == minutes
    assert W.route_minutes(["PLAZA", "C3"]) is None


def test_unknown_node_raises():
    with pytest.raises(KeyError):
        W.shortest_route("PLAZA", "Z9")


def test_bag_transfer_is_symmetric():
    assert W.bag_transfer_minutes("MU-C", "MU-A") == W.bag_transfer_minutes("MU-A", "MU-C") == 18
    assert W.bag_transfer_minutes("MU-B", "MU-B") == 0


def test_world_copy_is_deep(world):
    clone = world.copy()
    clone.flights["SK204"]["gate"] = "C1"
    assert world.flights["SK204"]["gate"] == "B4"


def test_boarding_close_and_clock_format(world):
    assert world.boarding_close("SK204") == 585 and W.hhmm(585) == "09:45"


def test_every_gate_is_reachable_from_the_entrance():
    for node, meta in W.NODES.items():
        if meta["kind"] == "gate":
            assert W.shortest_route("ENTRANCE", node)[1] > 0
