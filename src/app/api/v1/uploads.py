from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.core.config import settings
from app.deps.security import require_jwt_user
from app.schemas import AssetUploadResponse
from app.services.storage import store_uploaded_asset

router = APIRouter(dependencies=[Depends(require_jwt_user)])


@router.post(
    "/assets",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetUploadResponse,
)
async def upload_asset(file: UploadFile = File(...)) -> AssetUploadResponse:
    """Accept multipart asset upload from Flutter; store under MEDIA_STORAGE_DIR."""

    max_bytes = settings.UPLOAD_MAX_FILE_SIZE_MB * 1024 * 1024

    try:
        stored = await store_uploaded_asset(file, max_bytes=max_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return AssetUploadResponse(
        asset_url=stored.asset_url,
        asset_checksum=stored.checksum,
        asset_size_bytes=stored.size_bytes,
        content_type=stored.content_type,
    )
