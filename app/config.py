from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Access to our env file data"""

    database_hostname: str
    database_port: str
    database_password: str
    database_name: str
    database_username: str
    secret_key: str
    algorithm: str
    access_token_expiration_minutes: int
    refresh_token_expiration_days: int
    cloudinary_cloud_name: str
    cloudinary_api_key: str
    cloudinary_secret_key: str
    redis_database_host: str
    redis_database_password: str
    redis_database_port: str
    resend_api_key: str
    google_application_credentials: str

    model_config = {
        "env_file": ".env.local",
    }


settings = Settings()  # pyright: ignore[reportCallIssue]
