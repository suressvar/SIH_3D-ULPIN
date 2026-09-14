from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://astra:astra_local@localhost:54329/astra"
    redis_url: str = "redis://localhost:63799/0"
    cors_origins: list[str] = ["http://localhost:3000"]
    supabase_url: str = ""
    jwt_audience: str = "authenticated"
    storage_backend: Literal["local", "r2"] = "local"
    storage_root: Path = Path("data/objects")
    r2_endpoint: str = ""
    r2_bucket: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    node_executable: str = ""
    gltf_verify_script: str = ""
    blender_executable: str = ""
    segformer_weights: str = ""
    segformer_building_class: int | None = None
    pointnet_weights: str = ""
    max_raster_pixels: int = 16_000_000
    max_point_count: int = 200_000
    max_vertical_extent_m: float = 1000
    requests_per_minute: int = Field(default=120, gt=0)

    @model_validator(mode="after")
    def secure_production(self):
        if self.environment == "production":
            if not self.supabase_url.startswith("https://"):
                raise ValueError("Production requires an HTTPS Supabase URL")
            if self.storage_backend != "r2":
                raise ValueError("Production requires configured durable R2 storage")
            if any(not x.startswith("https://") for x in self.cors_origins):
                raise ValueError("Production CORS origins must use HTTPS")
        if self.storage_backend == "r2" and not all(
            [
                self.r2_endpoint,
                self.r2_bucket,
                self.r2_access_key_id,
                self.r2_secret_access_key,
            ]
        ):
            raise ValueError("R2 storage configuration is incomplete")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
