from contextlib import suppress

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import UploadedAsset, User
from app.deps.db import get_session
from app.deps.security import require_jwt_user
from app.schemas import AssetUploadResponse
from app.services.asset_storage import (
    AssetNotFoundError,
    AssetStorageError,
    asset_response,
    delete_approved_asset,
    store_approved_asset,
)

router = APIRouter(dependencies=[Depends(require_jwt_user)])


@router.post(
    "/assets",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetUploadResponse,
)
async def upload_asset(
    file: UploadFile = File(...),
    user: User = Depends(require_jwt_user),
    session: AsyncSession = Depends(get_session),
) -> AssetUploadResponse:
    """Store a rendered clip for its owner, outside the public media tree."""

    max_bytes = settings.UPLOAD_MAX_FILE_SIZE_MB * 1024 * 1024

    try:
        stored = await store_approved_asset(file, user_id=user.id, max_bytes=max_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except AssetStorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    asset = UploadedAsset(
        user_id=user.id,
        storage_backend=stored.backend,
        storage_path=stored.location,
        checksum=stored.checksum,
        size_bytes=stored.size_bytes,
        content_type=stored.content_type,
    )
    session.add(asset)
    try:
        await session.commit()
    except Exception:
        with suppress(Exception):
            await delete_approved_asset(asset)
        raise
    await session.refresh(asset)
    return AssetUploadResponse(
        asset_id=asset.id,
        asset_url=f"/api/v1/uploads/assets/{asset.id}",
        asset_checksum=stored.checksum,
        asset_size_bytes=stored.size_bytes,
        content_type=stored.content_type,
    )


@router.get("/assets/{asset_id}", response_model=None)
async def get_asset(
    asset_id: int,
    request: Request,
    user: User = Depends(require_jwt_user),
    session: AsyncSession = Depends(get_session),
) -> FileResponse | StreamingResponse:
    asset = await session.get(UploadedAsset, asset_id)
    if asset is None or asset.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    try:
        return await asset_response(asset, request.headers.get("range"))
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Asset not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=416, detail=str(exc)) from exc
    except AssetStorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
