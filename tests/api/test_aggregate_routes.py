from fastapi import FastAPI


def test_aggregate_routes_registered():
    from noetl.api import aggregate
    app = FastAPI()
    app.include_router(aggregate.router, prefix="/api")

    paths = {r.path for r in app.routes}
    assert "/api/aggregate/loop/results" in paths

