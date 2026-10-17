import asyncio
from types import SimpleNamespace

from app.personas import PersonaLookup


class FakeDb:
    def __init__(self, docs, fail=False):
        self.docs, self.fail, self.reads = docs, fail, 0

    def collection(self, name):
        assert name == "personas"
        return self

    def document(self, persona_id):
        self._id = persona_id
        return self

    def get(self):
        self.reads += 1
        if self.fail:
            raise RuntimeError("firestore down")
        data = self.docs.get(self._id)
        return SimpleNamespace(exists=data is not None, to_dict=lambda: data)


PERSONA = {"usual_mode": "motorcycle", "vehicles": ["motorcycle"], "income_band": "low",
           "occupation": "courier", "memory": ["x"], "home": {}}


def test_returns_only_stable_fields_and_caches():
    db = FakeDb({"p_1": PERSONA})
    lookup = PersonaLookup(db)
    first = asyncio.run(lookup.get("p_1"))
    second = asyncio.run(lookup.get("p_1"))
    assert first == {"usual_mode": "motorcycle", "vehicles": ["motorcycle"], "income_band": "low", "occupation": "courier"}
    assert second == first
    assert db.reads == 1


def test_missing_persona_is_none():
    assert asyncio.run(PersonaLookup(FakeDb({})).get("p_x")) is None


def test_lookup_failure_is_none():
    assert asyncio.run(PersonaLookup(FakeDb({}, fail=True)).get("p_1")) is None
