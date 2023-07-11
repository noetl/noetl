from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from strawberry.subscriptions import GRAPHQL_TRANSPORT_WS_PROTOCOL, GRAPHQL_WS_PROTOCOL
from strawberry.fastapi import GraphQLRouter
from schema import schema
from common import db

graphql_router = GraphQLRouter(
    schema,
    subscription_protocols=[
        GRAPHQL_TRANSPORT_WS_PROTOCOL,
        GRAPHQL_WS_PROTOCOL,
    ],
)
app = FastAPI()
"""
Not Only ETL is a Workflow Engine designed to manage the execution of complex workflows. 
"""

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    await db.pool_connect()


@app.on_event("shutdown")
async def shutdown_event():
    await db.pool_connect()


@app.get("/")
async def root():
    return {"message": "Not Only ETL is a Workflow Engine"}


# app.add_route("/graphql", GraphQL(schema=schema, graphiql=True))
# app.add_websocket_route("/graphql", app)
app.include_router(graphql_router, prefix="/graphql")


@app.websocket("/ws")
async def websocket_endpoint(websocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        await websocket.send_text(f"Received: {data}")
