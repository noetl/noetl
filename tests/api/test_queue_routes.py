from fastapi import FastAPI


def test_queue_routes_registered():
    from noetl.server.api import queue
    app = FastAPI()
    app.include_router(queue.router, prefix="/api")

    paths = {r.path for r in app.routes}
    # Spot check a few representative endpoints
    expected = {
        "/api/queue",
        "/api/queue/size",
        "/api/queue/reserve",
        "/api/queue/ack",
        "/api/queue/nack",
    }
    assert expected.issubset(paths)

