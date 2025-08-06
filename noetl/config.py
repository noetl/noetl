import os
from typing import Optional, Dict, Any, ClassVar
from pydantic import BaseModel, Field, ConfigDict, model_validator

class Settings(BaseModel):
    """
    NoETL application settings from environment variables.
    """
    app_name: str = "NoETL"
    app_version: str = "0.1.36"
    debug: bool = False
    
    host: str = "0.0.0.0"
    port: int = 8080
    enable_ui: bool = True
    
    run_mode: str = "server"  # "server", "worker", "cli"
    
    playbook_path: Optional[str] = None
    playbook_version: Optional[str] = None
    mock_mode: bool = False
    
    postgres_user: str = "noetl"
    postgres_password: str = "noetl"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "noetl"
    postgres_schema: str = "noetl"
    
    admin_postgres_user: str = "postgres"
    admin_postgres_password: str = "postgres"
    
    data_dir: str = "./data"
    
    model_config = ConfigDict(
        extra="ignore"
    )
    
    env_prefix: ClassVar[str] = "NOETL_"
    env_file: ClassVar[str] = ".env"
    
    env_mappings: ClassVar[Dict[str, str]] = {
        "postgres_user": "POSTGRES_USER",
        "postgres_password": "POSTGRES_PASSWORD",
        "postgres_host": "POSTGRES_HOST",
        "postgres_port": "POSTGRES_PORT",
        "postgres_db": "POSTGRES_DB",
        "postgres_schema": "POSTGRES_SCHEMA",
        "admin_postgres_user": "POSTGRES_USER",
        "admin_postgres_password": "POSTGRES_PASSWORD",
    }
    
    @model_validator(mode='before')
    @classmethod
    def load_from_env(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Load settings from environment variables."""
        if isinstance(data, dict):
            for key in cls.__annotations__:
                env_var = f"{cls.env_prefix}{key.upper()}"
                if env_var in os.environ:
                    data[key] = os.environ[env_var]
            
            for field_name, env_var in cls.env_mappings.items():
                if env_var in os.environ:
                    data[field_name] = os.environ[env_var]
                    
            if "port" in data and isinstance(data["port"], str):
                data["port"] = int(data["port"])
            if "postgres_port" in data and isinstance(data["postgres_port"], str):
                data["postgres_port"] = int(data["postgres_port"])
            if "debug" in data and isinstance(data["debug"], str):
                data["debug"] = data["debug"].lower() == "true"
            if "enable_ui" in data and isinstance(data["enable_ui"], str):
                data["enable_ui"] = data["enable_ui"].lower() == "true"
            if "mock_mode" in data and isinstance(data["mock_mode"], str):
                data["mock_mode"] = data["mock_mode"].lower() == "true"
                
        return data
    
    def get_database_url(self, admin: bool = False) -> str:
        """
        Get the database URL for connecting to Postgres.
        
        Args:
            admin: If True, use admin credentials
            
        Returns:
            Database URL string
        """
        user = self.admin_postgres_user if admin else self.postgres_user
        password = self.admin_postgres_password if admin else self.postgres_password
        
        return f"postgresql://{user}:{password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
    
    def get_pgdb_connection_string(self, admin: bool = False) -> str:
        """
        Get the Postgres connection string in psycopg format.
        
        Args:
            admin: If True, use admin credentials
            
        Returns:
            Connection string
        """
        user = self.admin_postgres_user if admin else self.postgres_user
        password = self.admin_postgres_password if admin else self.postgres_password
        
        return f"dbname={self.postgres_db} user={user} password={password} host={self.postgres_host} port={self.postgres_port}"


settings = Settings()