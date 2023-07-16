from strawberry import UNSET, asdict
import yaml
import json
from loguru import logger
from noetl.ncl.config import Config
from strawberry.scalars import JSON
import strawberry
from strawberry.file_uploads import Upload
from storage import RedisStorage

db = RedisStorage()

default_transition = {
    "ready": ["running"],
    "running": ["idle", "paused", "completed", "failed", "terminated"],
    "idle": ["running"],
    "paused": ["running"]
}


# remove unset
def to_dict(obj: any) -> any:
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items() if v != UNSET}
    elif isinstance(obj, list):
        return [to_dict(item) for item in obj]
    elif hasattr(obj, '__annotations__'):
        return to_dict(asdict(obj))
    else:
        return obj



@strawberry.input
class FolderInput:
    files: list[Upload]


@strawberry.type
class Workflow:
    data: JSON


@strawberry.type
class Query:
    @strawberry.field
    async def get_workflow(self, name: str) -> None | Workflow:
        workflow_json =  await db.load_json(f'workflow:{name}')
        if workflow_json is None:
            return None
        else:
            workflow_data = json.loads(workflow_json)
            return Workflow(**workflow_data)


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def read_file(self, file: Upload) -> str:
        try:
            config = Config(yaml.safe_load((await file.read()).decode("utf-8")))
            logger.info(config)
            workflow_name = config.get_value("metadata.name")
            logger.info(workflow_name)
            await db.save_json(f'workflow:{workflow_name}', config)
            workflow_json = await db.load_json(f'workflow:{workflow_name}')
            logger.info(workflow_json)
            return json.dumps(workflow_json)
        except yaml.YAMLError as e:
            logger.error(e)

    @strawberry.mutation
    async def read_files(self, files: list[Upload]) -> list[str]:
        contents = []
        for file in files:
            content = (await file.read()).decode("utf-8")
            contents.append(content)
        return contents

    @strawberry.mutation
    async def read_folder(self, folder: FolderInput) -> list[str]:
        contents = []
        for file in folder.files:
            content = (await file.read()).decode("utf-8")
            contents.append(content)
        return contents


schema = strawberry.Schema(query=Query, mutation=Mutation)
