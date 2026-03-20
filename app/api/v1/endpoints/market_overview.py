from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.responses import success_response
from app.models.user import User
from app.services.market_overview_service import fetch_market_overview

router = APIRouter(prefix="/market-overview", tags=["market-overview"])


@router.get("")
def get_market_overview(current_user: User = Depends(get_current_user)):
    items = fetch_market_overview()
    data = [
        {
            "label": item.label,
            "ticker": item.ticker,
            "price": item.price,
            "change_percent": item.change_percent,
            "currency": item.currency,
        }
        for item in items
    ]
    return success_response(data=data, message="Market overview fetched successfully")
