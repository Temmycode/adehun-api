from pydantic import BaseModel


class SignedUploadResponse(BaseModel):
    timestamp: int
    signature: str
    api_key: str
    cloud_name: str
    folder: str
    # Cloudinary rejects signatures older than one hour; clients should start
    # the upload well before this.
    expires_at: int | None = None
