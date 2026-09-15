import re
from time import time

from cloudinary import utils

from app.config import settings
from app.schemas.image_upload_schema import SignedUploadResponse

SIGNATURE_TTL_SECONDS = 60 * 60  # Cloudinary's own validity window
_SAFE_FOLDER = re.compile(r"^[A-Za-z0-9_\-/]{1,120}$")


def create_upload_signature(folder: str) -> SignedUploadResponse:
    """Sign a Cloudinary upload scoped to one folder.

    Callers pass a resource-scoped folder (`assets/<condition_id>`,
    `disputes/<agreement_id>`, `profiles/<user_id>`) so a leaked signature can
    only ever write into that one place. The signed parameter set is exactly
    what the mobile client echoes back, so no client change is required.
    """
    if not _SAFE_FOLDER.match(folder):
        raise ValueError("invalid upload folder")

    timestamp = int(time())
    scoped_folder = f"adehun/{folder}"
    params_to_sign = {"timestamp": timestamp, "folder": scoped_folder}
    signature = utils.api_sign_request(params_to_sign, settings.cloudinary_secret_key)
    return SignedUploadResponse(
        timestamp=timestamp,
        signature=signature,
        api_key=settings.cloudinary_api_key,
        cloud_name=settings.cloudinary_cloud_name,
        folder=scoped_folder,
        expires_at=timestamp + SIGNATURE_TTL_SECONDS,
    )
