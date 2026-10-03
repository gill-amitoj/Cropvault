import pytest

from app import db, routes_images
from tests.conftest import make_experiment, make_user

# (filename, species, experiment code, station, tags, capture_date)
IMAGES = [
    ("a.jpg", "Wheat", "EXP-A", "ST01", ["drought", "leaf"], "2026-05-01"),
    ("b.jpg", "wheat", "EXP-A", "ST02", ["drought"], "2026-05-10"),
    ("c.jpg", "Canola", "EXP-B", "ST01", ["leaf", "rust"], "2026-06-01"),
    ("d.jpg", "Barley", None, "ST03", [], "2026-04-15"),
    ("e.jpg", "Wheat", "EXP-B", "ST01", ["rust"], None),
]


@pytest.fixture
def viewer(api):
    """A viewer, plus the five images above (inserted directly; search doesn't need files)."""
    owner = make_user("researcher")
    experiments = {code: make_experiment(code)["id"] for code in ("EXP-A", "EXP-B")}
    with db.get_connection() as conn:
        for n, (name, species, exp, station, tags, date) in enumerate(IMAGES):
            conn.execute(
                """INSERT INTO images (original_filename, storage_key, content_type, size_bytes,
                       width, height, sha256, uploaded_by, crop_species, experiment_id,
                       station_id, tags, capture_date)
                   VALUES (%s, %s, 'image/jpeg', 100, 10, 10, %s, %s, %s, %s, %s, %s, %s)""",
                (name, f"originals/{name}", str(n) * 64, owner["id"], species,
                 experiments.get(exp), station, tags, date),
            )  # fmt: skip
    return make_user("viewer")


def search(api, user, query=""):
    response = api.get(f"/api/images?{query}", headers=user["headers"])
    assert response.status_code == 200, response.text
    return response.json()


def names(api, user, query=""):
    return sorted(item["original_filename"] for item in search(api, user, query)["items"])


# --- one test per filter ------------------------------------------------------------------


def test_no_filters_returns_everything(api, viewer):
    body = search(api, viewer)
    assert body["total"] == 5
    assert len(body["items"]) == 5


def test_filter_species_is_case_insensitive_exact_match(api, viewer):
    assert names(api, viewer, "species=wheat") == ["a.jpg", "b.jpg", "e.jpg"]
    assert names(api, viewer, "species=WHEAT") == ["a.jpg", "b.jpg", "e.jpg"]
    assert names(api, viewer, "species=whe") == []  # exact, not partial


def test_filter_experiment_by_code(api, viewer):
    assert names(api, viewer, "experiment=EXP-B") == ["c.jpg", "e.jpg"]


def test_filter_unknown_experiment_returns_empty_not_error(api, viewer):
    body = search(api, viewer, "experiment=NOPE")
    assert body["total"] == 0 and body["items"] == []


def test_filter_station(api, viewer):
    assert names(api, viewer, "station=ST01") == ["a.jpg", "c.jpg", "e.jpg"]


def test_filter_single_tag(api, viewer):
    assert names(api, viewer, "tags=leaf") == ["a.jpg", "c.jpg"]


def test_filter_multiple_tags_requires_all(api, viewer):
    assert names(api, viewer, "tags=drought,leaf") == ["a.jpg"]
    assert names(api, viewer, "tags=Drought,%20LEAF") == ["a.jpg"]  # normalized like on upload


def test_filter_date_from_is_inclusive(api, viewer):
    assert names(api, viewer, "date_from=2026-05-10") == ["b.jpg", "c.jpg"]


def test_filter_date_to_is_inclusive(api, viewer):
    assert names(api, viewer, "date_to=2026-05-01") == ["a.jpg", "d.jpg"]


def test_filter_date_range_excludes_undated_images(api, viewer):
    assert names(api, viewer, "date_from=2026-01-01&date_to=2026-12-31") == [
        "a.jpg", "b.jpg", "c.jpg", "d.jpg",
    ]  # fmt: skip


def test_reversed_date_range_is_422(api, viewer):
    response = api.get(
        "/api/images?date_from=2026-06-01&date_to=2026-05-01", headers=viewer["headers"]
    )
    assert response.status_code == 422


def test_invalid_date_is_422(api, viewer):
    response = api.get("/api/images?date_from=yesterday", headers=viewer["headers"])
    assert response.status_code == 422


def test_filters_combine_with_and(api, viewer):
    assert names(api, viewer, "species=wheat&station=ST01&tags=rust") == ["e.jpg"]
    assert names(api, viewer, "species=wheat&experiment=EXP-A&date_from=2026-05-05") == ["b.jpg"]


# --- sorting and pagination ---------------------------------------------------------------


def test_sorted_newest_capture_date_first_undated_last(api, viewer):
    order = [item["original_filename"] for item in search(api, viewer)["items"]]
    assert order == ["c.jpg", "b.jpg", "a.jpg", "d.jpg", "e.jpg"]


def test_pagination_pages_do_not_overlap(api, viewer):
    first = search(api, viewer, "page_size=2")
    second = search(api, viewer, "page_size=2&page=2")
    third = search(api, viewer, "page_size=2&page=3")
    beyond = search(api, viewer, "page_size=2&page=4")

    seen = [i["id"] for page in (first, second, third) for i in page["items"]]
    assert len(seen) == 5 and len(set(seen)) == 5
    assert first["total"] == 5 and first["page_size"] == 2
    assert beyond["items"] == [] and beyond["total"] == 5


def test_default_page_size_is_24(api, viewer):
    body = search(api, viewer)
    assert (body["page"], body["page_size"]) == (1, 24)


@pytest.mark.parametrize("query", ["page=0", "page_size=0", "page_size=101"])
def test_bad_pagination_is_422(api, viewer, query):
    assert api.get(f"/api/images?{query}", headers=viewer["headers"]).status_code == 422


# --- access -------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["admin", "researcher", "viewer"])
def test_every_role_can_search(api, viewer, role):
    user = make_user(role, email=f"search-{role}@example.com")
    assert search(api, user)["total"] == 5


def test_search_requires_login(api):
    assert api.get("/api/images").status_code == 401


def test_sql_in_a_filter_is_treated_as_text(api, viewer):
    assert names(api, viewer, "species=wheat' OR '1'='1") == []
    assert search(api, viewer)["total"] == 5  # table untouched


# --- indexes: each filter can use its index ----------------------------------------------


@pytest.mark.parametrize(
    ("filters", "index"),
    [
        ({"species": "wheat"}, "idx_images_crop_species_lower"),
        ({"experiment": "EXP-A"}, "idx_images_experiment_id"),
        ({"station": "ST01"}, "idx_images_station_id"),
        ({"tags": "drought"}, "idx_images_tags"),
        ({"date_from": "2026-05-01"}, "idx_images_capture_date"),
    ],
)
def test_filter_query_uses_its_index(api, viewer, filters, index):
    """With 5 rows Postgres would just scan the table, so we turn sequential scans off and
    check the planner CAN answer the real search query with the intended index."""
    where, params = routes_images.search_where(**filters)
    with db.get_connection() as conn:
        conn.execute("SET LOCAL enable_seqscan = off")
        plan = conn.execute("EXPLAIN SELECT i.id FROM images i" + where, params).fetchall()
    plan_text = "\n".join(row["QUERY PLAN"] for row in plan)
    assert index in plan_text, plan_text
