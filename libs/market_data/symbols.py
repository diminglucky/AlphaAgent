from __future__ import annotations

from typing import Optional


def normalize_provider_code(code: str) -> str:
    clean_code = code.strip().upper()
    if clean_code.startswith(("SH", "SZ", "BJ")) and len(clean_code) > 2:
        suffix = clean_code[2:]
        if suffix.isdigit():
            return suffix
    return clean_code


def infer_exchange(code: str) -> str:
    normalized = normalize_provider_code(code)
    if normalized.startswith(("600", "601", "603", "605", "688", "900")):
        return "SH"
    if normalized.startswith(("000", "001", "002", "003", "300", "301", "200")):
        return "SZ"
    if normalized.startswith(("430", "830", "831", "832", "833", "835", "836", "837", "838", "839", "870", "871", "872", "873", "874", "875", "876", "877", "878", "879", "880", "881", "882", "883", "884", "885", "886", "887", "888", "889")):
        return "BJ"
    return "UNKNOWN"


def to_internal_symbol(code: str, exchange: Optional[str] = None) -> str:
    clean_code = code.strip().upper()
    if "." in clean_code:
        return clean_code

    if clean_code.startswith(("SH", "SZ", "BJ")) and len(clean_code) > 2:
        suffix = clean_code[2:]
        if suffix.isdigit():
            return f"{suffix}.{clean_code[:2]}"

    normalized = normalize_provider_code(clean_code)
    exchange_code = exchange or infer_exchange(normalized)
    if exchange_code == "UNKNOWN":
        return normalized
    return f"{normalized}.{exchange_code}"


def to_provider_symbol(symbol: str) -> str:
    return symbol.split(".", maxsplit=1)[0]
