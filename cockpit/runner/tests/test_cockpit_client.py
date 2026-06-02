from uuid import uuid4

from cockpit_runner.cockpit_client import ClaimedRequest


def test_claimed_request_dataclass() -> None:
    rid = uuid4()
    iid = uuid4()
    r = ClaimedRequest(
        id=rid,
        instance_slug="schule-x",
        instance_base_url="https://schule-x.example.ch",
        instance_channel="stable",
        target_version="0.4.0",
    )
    assert r.instance_slug == "schule-x"
    assert r.target_version == "0.4.0"
    assert isinstance(r.id, type(rid))
    assert iid != rid
