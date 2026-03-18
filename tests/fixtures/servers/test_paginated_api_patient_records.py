"""
Tests for /api/v1/patient-records endpoint (AHM-4287).

Covers all acceptance criteria:
- Correct FHIR-like paginated structure
- ~100KB response body per page
- Server-side delay observable (timing check, skippable in CI)
- 51st request in 1-second window returns 429 + Retry-After: 1
- Page count per patientId is consistent across repeated requests
- link.next present on non-last pages, absent on last page
- Unique entry IDs across pages
"""

import json
import time
import pytest
from fastapi.testclient import TestClient

import tests.fixtures.servers.paginated_api as paginated_api_module
from tests.fixtures.servers.paginated_api import app

# Use delay_min=0&delay_max=0 in all latency-insensitive tests to keep suite fast.
BASE = "/api/v1/patient-records"
NO_DELAY = "delay_min=0&delay_max=0"


@pytest.fixture(autouse=True)
def reset_rate_window():
    """Clear the global rate-limit window before each test."""
    paginated_api_module.patient_records_rate_window.clear()
    yield
    paginated_api_module.patient_records_rate_window.clear()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

class TestFhirBundleStructure:
    def test_top_level_fields(self, client):
        r = client.get(f"{BASE}?patientId=p1&page=1&{NO_DELAY}&payload_kb=1")
        assert r.status_code == 200
        body = r.json()
        assert body["resourceType"] == "Bundle"
        assert body["type"] == "searchset"
        assert isinstance(body["total"], int) and body["total"] > 0
        assert isinstance(body["entry"], list) and len(body["entry"]) > 0
        assert isinstance(body["link"], list) and len(body["link"]) > 0

    def test_entry_shape(self, client):
        r = client.get(f"{BASE}?patientId=p1&page=1&pageSize=3&{NO_DELAY}&payload_kb=1")
        entry = r.json()["entry"][0]
        assert "fullUrl" in entry
        assert "resource" in entry
        res = entry["resource"]
        assert res["resourceType"] == "MedicationStatement"
        assert "id" in res
        assert res["subject"]["reference"].startswith("Patient/")
        assert "medicationCodeableConcept" in res
        assert "dosage" in res

    def test_entry_ids_unique_within_page(self, client):
        r = client.get(f"{BASE}?patientId=p2&page=1&pageSize=10&{NO_DELAY}&payload_kb=1")
        ids = [e["resource"]["id"] for e in r.json()["entry"]]
        assert len(ids) == len(set(ids))

    def test_entry_ids_unique_across_pages(self, client):
        r1 = client.get(f"{BASE}?patientId=p3&page=1&pageSize=5&{NO_DELAY}&payload_kb=1")
        r2 = client.get(f"{BASE}?patientId=p3&page=2&pageSize=5&{NO_DELAY}&payload_kb=1")
        ids1 = {e["resource"]["id"] for e in r1.json()["entry"]}
        ids2 = {e["resource"]["id"] for e in r2.json()["entry"]}
        assert ids1.isdisjoint(ids2), "Entry IDs must not overlap across pages"


# ---------------------------------------------------------------------------
# Pagination links
# ---------------------------------------------------------------------------

class TestPaginationLinks:
    def test_link_next_present_on_first_page(self, client):
        r = client.get(f"{BASE}?patientId=p4&page=1&{NO_DELAY}&payload_kb=1")
        rels = [lnk["relation"] for lnk in r.json()["link"]]
        assert "self" in rels
        assert "next" in rels

    def test_link_next_absent_on_last_page(self, client):
        # Fetch first page to discover total_pages
        r1 = client.get(f"{BASE}?patientId=p5&page=1&pageSize=10&{NO_DELAY}&payload_kb=1")
        body = r1.json()
        total_pages = body["total"] // 10
        assert total_pages >= 1

        r_last = client.get(f"{BASE}?patientId=p5&page={total_pages}&pageSize=10&{NO_DELAY}&payload_kb=1")
        rels = [lnk["relation"] for lnk in r_last.json()["link"]]
        assert "self" in rels
        assert "next" not in rels

    def test_link_next_url_points_to_correct_page(self, client):
        r = client.get(f"{BASE}?patientId=p6&page=1&pageSize=5&{NO_DELAY}&payload_kb=1")
        links = {lnk["relation"]: lnk["url"] for lnk in r.json()["link"]}
        assert "next" in links
        assert "page=2" in links["next"]

    def test_beyond_last_page_returns_empty_bundle(self, client):
        r = client.get(f"{BASE}?patientId=p7&page=999&{NO_DELAY}&payload_kb=1")
        assert r.status_code == 200
        body = r.json()
        assert body["entry"] == []
        rels = [lnk["relation"] for lnk in body["link"]]
        assert "next" not in rels


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_patient_same_page_count(self, client):
        def get_total(patient_id):
            r = client.get(f"{BASE}?patientId={patient_id}&page=1&pageSize=10&{NO_DELAY}&payload_kb=1")
            return r.json()["total"]

        assert get_total("patient-abc") == get_total("patient-abc")

    def test_same_patient_same_entries_on_same_page(self, client):
        def get_ids(patient_id):
            r = client.get(f"{BASE}?patientId={patient_id}&page=1&pageSize=5&{NO_DELAY}&payload_kb=1")
            return [e["resource"]["id"] for e in r.json()["entry"]]

        assert get_ids("patient-xyz") == get_ids("patient-xyz")

    def test_different_patients_may_have_different_page_counts(self, client):
        """Different patientIds should produce varied (not all identical) page counts."""
        patients = [f"patient-{i}" for i in range(20)]
        counts = set()
        for pid in patients:
            r = client.get(f"{BASE}?patientId={pid}&page=1&pageSize=10&{NO_DELAY}&payload_kb=1")
            counts.add(r.json()["total"] // 10)
        # With 20 patients and range 2-5, we expect more than one distinct count
        assert len(counts) > 1, "Expected page counts to vary across patients"


# ---------------------------------------------------------------------------
# Payload size
# ---------------------------------------------------------------------------

class TestPayloadSize:
    def test_response_approximately_100kb(self, client):
        r = client.get(f"{BASE}?patientId=p8&page=1&pageSize=10&{NO_DELAY}&payload_kb=100")
        size = len(r.content)
        # Allow ±20% tolerance around 100 KB
        assert 80 * 1024 <= size <= 120 * 1024, (
            f"Expected ~100KB response, got {size / 1024:.1f}KB"
        )

    def test_payload_kb_query_param_respected(self, client):
        r_small = client.get(f"{BASE}?patientId=p9&page=1&{NO_DELAY}&payload_kb=10")
        r_large = client.get(f"{BASE}?patientId=p9&page=1&{NO_DELAY}&payload_kb=200")
        assert len(r_large.content) > len(r_small.content) * 5


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class TestRateLimit:
    def test_51st_request_returns_429(self, client):
        statuses = []
        for _ in range(55):
            r = client.get(f"{BASE}?patientId=rl&page=1&{NO_DELAY}&payload_kb=1&rate_limit=50")
            statuses.append(r.status_code)

        assert statuses.count(200) == 50
        assert statuses.count(429) == 5
        assert statuses.index(429) == 50  # first 429 is the 51st request

    def test_429_has_retry_after_header(self, client):
        # Exhaust the limit
        for _ in range(50):
            client.get(f"{BASE}?patientId=rl2&page=1&{NO_DELAY}&payload_kb=1&rate_limit=50")

        r = client.get(f"{BASE}?patientId=rl2&page=1&{NO_DELAY}&payload_kb=1&rate_limit=50")
        assert r.status_code == 429
        assert r.headers.get("retry-after") == "1"

    def test_429_body_content(self, client):
        for _ in range(50):
            client.get(f"{BASE}?patientId=rl3&page=1&{NO_DELAY}&payload_kb=1&rate_limit=50")

        r = client.get(f"{BASE}?patientId=rl3&page=1&{NO_DELAY}&payload_kb=1&rate_limit=50")
        assert r.status_code == 429
        body = r.json()
        assert "error" in body

    def test_custom_rate_limit_via_query_param(self, client):
        statuses = []
        for _ in range(7):
            r = client.get(f"{BASE}?patientId=rl4&page=1&{NO_DELAY}&payload_kb=1&rate_limit=5")
            statuses.append(r.status_code)

        assert statuses[:5] == [200] * 5
        assert statuses[5] == 429


# ---------------------------------------------------------------------------
# Server-side latency (skipped in CI by default)
# ---------------------------------------------------------------------------

class TestLatency:
    @pytest.mark.skipif(
        __import__("os").getenv("NOETL_SKIP_SLOW_TESTS", "false").lower() == "true",
        reason="Slow tests disabled",
    )
    def test_server_delay_is_applied(self, client):
        start = time.monotonic()
        client.get(f"{BASE}?patientId=latency-1&page=1&payload_kb=1&delay_min=0.5&delay_max=0.5")
        elapsed = time.monotonic() - start
        assert elapsed >= 0.5, f"Expected at least 0.5s delay, got {elapsed:.2f}s"

    def test_zero_delay_is_fast(self, client):
        start = time.monotonic()
        client.get(f"{BASE}?patientId=fast&page=1&payload_kb=1&{NO_DELAY}")
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"Zero-delay request took too long: {elapsed:.2f}s"
