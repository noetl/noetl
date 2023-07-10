from storage import db
from fastapi import FastAPI
from strawberry.asgi import GraphQL
from schema.workflow import schema

app = FastAPI()
"""
Not Only ETL is a Workflow Engine designed to manage the execution of complex workflows. 
"""


@app.on_event("startup")
async def startup_event():
    await db.pool_connect()


@app.on_event("startup")
async def startup_event():
    await db.pool_connect()


@app.get("/")
async def root():
    return {"message": "Not Only ETL is a Workflow Engine"}


app.add_route("/graphql", GraphQL(schema=schema, graphiql=True))
