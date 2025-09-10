from fastapi import FastAPI


def test_broker_routes_registered():
    from noetl.api.event.broker import router as broker_router
    app = FastAPI()
    app.include_router(broker_router, prefix="/api")

    paths = {r.path for r in app.routes}
    assert "/api/broker/evaluate/{execution_id}" in paths
    assert "/api/loop/complete/{execution_id}" in paths

