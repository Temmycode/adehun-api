from time import time

from cloudinary import utils

from app.config import settings
from app.schemas.image_upload_schema import SignedUploadResponse


def create_upload_signature(folder: str) -> SignedUploadResponse:
    timestamp = int(time())
    params_to_sign = {"timestamp": timestamp, "folder": f"adehun/{folder}"}
    signature = utils.api_sign_request(params_to_sign, settings.cloudinary_secret_key)
    return SignedUploadResponse.model_validate(
        {
            "timestamp": timestamp,
            "signature": signature,
            "api_key": settings.cloudinary_api_key,
            "cloud_name": settings.cloudinary_cloud_name,
            "folder": folder,
        }
    )
