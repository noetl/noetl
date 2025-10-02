from fastapi import FastAPI


def test_executions_routes_registered():
    from noetl.api.routers.event.executions import router as executions_router
    app = FastAPI()
    app.include_router(executions_router, prefix="/api")

    paths = {r.path for r in app.routes}
    expected = {
        "/api/execution/data/{execution_id}",
        "/api/events/summary/{execution_id}",
        "/api/executions",
        "/api/executions/{execution_id}",
    }
    assert expected.issubset(paths)

