import asyncio
from noetl.config.settings import AppConfig
from noetl.util import setup_logger
logger = setup_logger(__name__)

class AppContext:
    _lock = asyncio.Lock()

    def __init__(self, config: AppConfig):
        self._components = {}
        self.config: AppConfig = config

    def register_component(self, name, component):
        self._components[name] = component
        logger.info(f"Component {name} registered.")

    async def get_component(self, name):
        logger.debug(f"Attempting to retrieve component: {name}")
        if name not in self._components:
            raise ValueError(f"Component '{name}' is not registered.")

        component = self._components[name]
        logger.debug(f"Component '{name}' retrieved: {component}")

        if hasattr(component, "initialize") and callable(component.initialize):
            if not getattr(component, "_initialized", False):
                logger.info(f"Initializing component: {name}")
                await component.initialize()
                component._initialized = True
            else:
                logger.info(f"Component '{name}' already initialized.")

        return component

    async def initialize_components(self):
        for name, component in self._components.items():
            if hasattr(component, "initialize") and callable(component.initialize):
                await component.initialize()

    async def cleanup(self):
        for name, component in self._components.items():
            if hasattr(component, "shutdown") and callable(component.shutdown):
                logger.debug(f"Shutting down component: {name}")
                await component.shutdown()

    async def __aenter__(self):
        logger.info("Upgraded placeholder logger to async logging.")
        await self.initialize_components()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        logger.debug("Exiting async context.")
        await self.cleanup()

    async def initialize_postgres(self):
        if "postgres" not in self._components:
            from noetl.connectors.postgrefy import PostgresHandler
            postgres_handler = PostgresHandler(config=self.config)
            self.register_component("postgres", postgres_handler)
        postgres = await self.get_component("postgres")
        await postgres.initialize()
        await postgres.initialize_sqlmodel()
        logger.info("NoETL tables initialized.")
        return postgres

    async def initialize_gs(self):
        if "gs" not in self._components:
            from connectors.gcp.cloud_storage import GoogleStorageHandler
            gs_handler = GoogleStorageHandler(
                config=self.config.cloud
            )
            self.register_component("gs", gs_handler)
        return await self.get_component("gs")

    async def initialize_request(self):
        from noetl.connectors.requestify import RequestHandler

        if "request" not in self._components:
            self._components["request"] = RequestHandler(self.config.cloud)
            logger.info("RequestHandler registered.")
        else:
            logger.warning("RequestHandler already registered.")

    @property
    def postgres(self):
        return self._components.get("postgres")

    @property
    def gs(self):
        return self._components.get("gs")

    @property
    def request(self):
        return self._components.get("request")

    @staticmethod
    def load_config():
        from noetl.config.settings import AppConfig, CloudConfig, PostgresConfig, LogConfig
        return AppConfig(
            cloud=CloudConfig(),
            log=LogConfig(),
            postgres=PostgresConfig(),
        )

_app_context = None

async def get_app_context() -> AppContext:
    global _app_context
    from noetl.config.settings import AppConfig, CloudConfig, PostgresConfig, LogConfig

    if _app_context is None:
        lock = asyncio.Lock()

        async with lock:
            if _app_context is None:
                try:
                    config = AppConfig(
                        cloud=CloudConfig(),
                        log=LogConfig(),
                        postgres=PostgresConfig(),
                    )
                    _app_context = AppContext(config)
                    await _app_context.__aenter__()
                    await _app_context.initialize_postgres()
                    await _app_context.postgres.initialize()
                    await _app_context.initialize_request()

                except Exception as e:
                    raise Exception(f"Failed to initialize application context: {e}.")

    return _app_context
