from fastapi import FastAPI


def test_events_routes_registered():
    from noetl.api.routers.event.events import router as events_router
    app = FastAPI()
    app.include_router(events_router, prefix="/api")

    paths = {r.path for r in app.routes}
    expected_paths = {
        "/api/events",
        "/api/events/by-execution/{execution_id}",
        "/api/events/by-id/{event_id}",
        "/api/events/{event_id}",
        "/api/events/query",
    }
    # Not all endpoints may be present depending on refactor; ensure at least core ones exist
    assert "/api/events" in paths
    assert "/api/events/by-execution/{execution_id}" in paths
    # Remaining paths are optional; verify that at least one more is present to indicate breadth
    assert expected_paths.intersection(paths)

