from app.repository.agreement_repository import AgreementRepository
from app.repository.asset_repository import AssetRepository
from app.repository.condition_repository import ConditionRepository


class AgreementService:
    def __init__(
        self,
        agreement_repo: AgreementRepository,
        condition_repo: ConditionRepository,
        asset_repo: AssetRepository,
    ):
        self.agreement_repo = agreement_repo
        self.condition_repo = condition_repo
        self.asset_repo = asset_repo
