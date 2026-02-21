"""Broker connection and symbol listing endpoints."""

from fastapi import APIRouter, HTTPException
from app.models.schemas import (
    BrokerConnectRequest, BrokerConnectResponse,
    SymbolsResponse, SymbolInfo,
)
from app.services.mt5_service import mt5_service

router = APIRouter(prefix="/api/broker", tags=["broker"])


@router.post("/connect", response_model=BrokerConnectResponse)
async def connect_broker(req: BrokerConnectRequest):
    """
    Connect to a broker using investor (read-only) password.
    This logs into the MT5 terminal with the provided credentials.
    """
    result = mt5_service.login(
        login=req.login,
        password=req.password,
        server=req.server,
    )
    if "error" in result:
        return BrokerConnectResponse(
            connected=False,
            server=req.server,
            login=req.login,
            error=result["error"],
        )

    return BrokerConnectResponse(
        connected=True,
        server=req.server,
        login=req.login,
        mt5_version=mt5_service.get_version(),
        account_name=result.get("name"),
        account_balance=result.get("balance"),
    )


@router.get("/symbols", response_model=SymbolsResponse)
async def list_symbols(group: str = None):
    """
    List available symbols from the currently connected broker.
    Optionally filter by group pattern (e.g., "*GOLD*", "*USD*").
    """
    if not mt5_service.is_connected():
        raise HTTPException(status_code=400, detail="Not connected to any broker. Call /connect first.")

    symbols = mt5_service.get_symbols(group=group)
    return SymbolsResponse(
        count=len(symbols),
        symbols=[SymbolInfo(**s) for s in symbols],
    )
