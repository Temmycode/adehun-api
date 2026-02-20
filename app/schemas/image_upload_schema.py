from pydantic import BaseModel


class SignedUploadResponse(BaseModel):
    timestamp: int
    signature: str
    api_key: str
    cloud_name: str
    folder: str
