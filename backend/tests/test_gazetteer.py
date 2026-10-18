"""Local names in the shared region graph, against a real FalkorDB. Skipped when none is reachable.

The region graph is shared, so each test removes the names it adds."""
import pytest

from reliefnet import areas, db, gazetteer, geo
from reliefnet.seed import seed_region

ALIAS = "pytest naya naam"


@pytest.fixture
async def region():
    try:
        await db.redis().ping()
    except Exception:
        pytest.skip("FalkorDB not reachable")
    await seed_region()
    yield areas.region()
    await db.close()


async def test_new_alias_reaches_geo_and_survives_a_landmark_refresh(region):
    lm = region.landmarks[0]
    try:
        out = await gazetteer.add_alias(lm["id"], "  Pytest  Naya Naam ", by="pytest")
        assert ALIAS in out["aliases"]
        hit = await geo.resolve("", 0, f"5 log {ALIAS} ke paas", seed="pytest")
        assert hit["landmark"] == lm["name"]
        with pytest.raises(gazetteer.GazetteerError) as e:
            await gazetteer.add_alias(lm["id"], ALIAS, by="pytest")
        assert e.value.status == 409
        other = region.landmarks[1]
        with pytest.raises(gazetteer.GazetteerError) as e:
            await gazetteer.add_alias(lm["id"], other["name"], by="pytest")
        assert e.value.status == 409

        junctions = await db.scalar("region", "MATCH (j:Junction) RETURN count(j)")
        await gazetteer.refresh_landmarks(region, areas.landmark_version())
        assert await db.scalar("region", "MATCH (j:Junction) RETURN count(j)") == junctions
        again = next(l for l in await geo.landmarks() if l["id"] == lm["id"])
        assert ALIAS in again["aliases"]
    finally:
        await gazetteer.forget(lm["id"])
    assert ALIAS not in next(l for l in await geo.landmarks() if l["id"] == lm["id"])["aliases"]


async def test_neighbourhoods_are_seeded_and_take_local_names(region):
    if not region.neighbourhoods:
        pytest.skip("this area has no neighbourhoods")
    rows = await geo.neighbourhoods()
    assert sorted(n["id"] for n in rows) == sorted(n["id"] for n in region.neighbourhoods)
    assert all(set(n) == {"id", "name", "aliases", "ward", "lat", "lon", "polygon"} for n in rows)
    nb = region.neighbourhoods[0]
    try:
        await gazetteer.add_alias(nb["id"], ALIAS, by="pytest")
        hit = await geo.resolve("", 0, "", seed="pytest", neighbourhood=ALIAS)
        assert hit["neighbourhood"] == nb["name"] and hit["geo_confidence"] == "low"
        await gazetteer.refresh_landmarks(region, areas.landmark_version())
        again = next(n for n in await geo.neighbourhoods() if n["id"] == nb["id"])
        assert ALIAS in again["aliases"]
    finally:
        await gazetteer.forget(nb["id"])
    assert ALIAS not in next(n for n in await geo.neighbourhoods() if n["id"] == nb["id"])["aliases"]


async def test_resolve_uses_a_real_road(region):
    names = await geo.clue_road_names()
    if not names:
        pytest.skip("this area has no named roads")
    hit = await geo.resolve("", 0, "", seed="pytest", road=names[0])
    assert hit["road"] and hit["geo_confidence"] == "low"


async def test_new_landmark_inside_the_area(region):
    w = region.wards[-1]
    lid = ""
    try:
        lm = await gazetteer.add_landmark("Pytest Pani Tanki", ["pytest tanki"], "landmark", w["lat"], w["lon"],
                                          by="pytest")
        lid = lm["id"]
        assert lm["ward"] == w["num"] and lm["source"] == "app"
        hit = await geo.resolve("", w["num"], "pytest tanki ke saamne", seed="pytest")
        assert hit["landmark"] == "Pytest Pani Tanki"
        with pytest.raises(gazetteer.GazetteerError) as e:
            await gazetteer.add_landmark("Pytest Pani Tanki", [], "landmark", w["lat"], w["lon"], by="pytest")
        assert e.value.status == 409
        with pytest.raises(gazetteer.GazetteerError) as e:
            await gazetteer.add_landmark("Pytest Far Place", [], "landmark", w["lat"] + 1, w["lon"], by="pytest")
        assert e.value.status == 400
        # A region rebuild writes the coordinators' landmarks again.
        await gazetteer.refresh_landmarks(region, areas.landmark_version())
        assert any(l["id"] == lid for l in await geo.landmarks())
    finally:
        if lid:
            await gazetteer.forget(lid)
    assert not any(l["name"] == "Pytest Pani Tanki" for l in await geo.landmarks())
