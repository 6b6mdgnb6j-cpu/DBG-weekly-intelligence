from .dbg import parse_dbg_list, parse_eurex_list
from .apra import parse_apra_list
from .crypto_finance import parse_crypto_finance_list
from .euronext import parse_euronext_list
from .govuk import parse_govuk_list
from .hkma import parse_hkma_list
from .hkex import parse_hkex_list
from .jpx import parse_jpx_list
from .osc import parse_osc_list
from .sfc import parse_sfc_list


ADAPTERS = {
    "SRC-006": parse_hkma_list,
    "SRC-007": parse_sfc_list,
    "SRC-023": parse_govuk_list,
    "SRC-040": parse_apra_list,
    "SRC-064": parse_euronext_list,
    "SRC-073": parse_jpx_list,
    "SRC-089": parse_dbg_list,
    "SRC-143": parse_eurex_list,
    "SRC-144": parse_crypto_finance_list,
    "SRC-152": parse_hkex_list,
    "SRC-045": parse_osc_list,
}


def get_adapter(source):
    return ADAPTERS.get(source.get("id", ""))
