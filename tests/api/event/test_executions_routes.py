from fastapi import FastAPI


def test_executions_routes_registered():
    from noetl.server.api.execution.endpoint import router as executions_router
    app = FastAPI()
    app.include_router(executions_router, prefix="/api")

    paths = {r.path for r in app.routes}
    expected = {
        "/api/executions",
        "/api/executions/{execution_id}",
        "/api/executions/{execution_id}/events",
        "/api/executions/{execution_id}/cancel",
        "/api/executions/{execution_id}/cancellation-check",
    }
    assert expected.issubset(paths)
