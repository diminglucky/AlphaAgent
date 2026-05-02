from pydantic import BaseModel


class ProviderStatusResponse(BaseModel):
    selected_provider: str
    active_provider: str
    akshare_installed: bool

