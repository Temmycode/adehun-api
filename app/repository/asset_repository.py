import logging

from redis import Redis
from sqlmodel import Session, select

from app.models import Asset
from app.redis import RedisClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TTL constants (seconds)
# ---------------------------------------------------------------------------
_TTL_AGREEMENT_ASSETS = 60 * 60 * 24  # 24 hours – cache TTL
_TTL_ASSETS = 60 * 60 * 24  # 24 hours – cache TTL
_NONE_SENTINEL = "__none__"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _asset_key(asset_id: str) -> str:
    return f"asset:{asset_id}"


def _agreement_asset_key(agreement_id: str) -> str:
    return f"agreement:{agreement_id}:asset"


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------
class AssetRepository(RedisClient):
    def __init__(self, session: Session, redis_client: Redis):
        super().__init__(redis_client)
        self.session = session

    # ------------------------------------------------------------------ #
    #  Asset Operations                                                  #
    # ------------------------------------------------------------------ #

    def flush_asset(self, asset: Asset) -> Asset:
        """Flush an asset to the database to retrieve the id"""
        self.session.add(asset)
        self.session.flush()
        return asset

    def get_by_id(self, asset_id: str) -> Asset | None:
        """Get an asset by id"""
        key = _asset_key(asset_id)
        cached = self._cache_get(key)
        if cached is not None:
            return Asset.model_validate(cached)

        asset = self.session.exec(
            select(Asset).where(Asset.asset_id == asset_id)
        ).first()
        if asset:
            self._cache_set(key, asset, _TTL_ASSETS)
        return asset

    def get_agreement_assets(self, agreement_id: str) -> list[Asset]:
        """Get all assets assigned to an agreement"""
        key = _agreement_asset_key(agreement_id)
        cached = self._cache_get(key)
        if cached is not None:
            return [Asset.model_validate(asset) for asset in cached]

        assets = list(
            self.session.exec(
                select(Asset).where(Asset.agreement_id == agreement_id)
            ).all()
        )
        if assets:
            self._cache_set(
                key,
                [asset.model_dump(mode="json") for asset in assets],
                _TTL_AGREEMENT_ASSETS,
            )
        return assets

    def delete_asset(self, asset_id: str) -> None:
        asset = self.get_by_id(asset_id)
        if asset:
            self.session.delete(asset)
            self.session.commit()
            self._cache_delete(_asset_key(asset_id))

    # ------------------------------------------------------------------ #
    #  Write operations (always invalidate relevant cache keys)          #
    # ------------------------------------------------------------------ #

    def save_asset(self, asset: Asset, *, commit: bool = True) -> Asset:
        """Save an asset to the database"""
        self.session.add(asset)
        if commit:
            self.session.commit()
            self.session.refresh(asset)
        return asset

    def commit(self) -> None:
        """Commit the session"""
        self.session.commit()

    def rollback(self) -> None:
        """Rollback the session"""
        self.session.rollback()

    def refresh(self, asset: Asset) -> None:
        """Refresh an asset from the database"""
        self.session.refresh(asset)
