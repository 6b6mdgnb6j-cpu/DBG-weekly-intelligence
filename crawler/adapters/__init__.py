from .dbg import parse_dbg_list, parse_eurex_list
from .apra import parse_apra_list
from .crypto_finance import parse_crypto_finance_list
from .csrc import parse_csrc_search_json
from .euronext import parse_euronext_list
from .fca import parse_fca_list
from .govuk import parse_govuk_list
from .hkma import parse_hkma_list
from .hkex import parse_hkex_list
from .jpx import parse_jpx_list
from .nfra import parse_nfra_docinfo_json
from .osc import parse_osc_list
from .sfc import parse_sfc_list
from .shfe import parse_shfe_notice_list
from .expansion import (
    parse_adgm_list,
    parse_360t_press_list,
    parse_article_release_list,
    parse_b3_list,
    parse_bafin_press_list,
    parse_bma_list,
    parse_dtcc_list,
    parse_eex_list,
    parse_korea_fsc_list,
    parse_naic_list,
    parse_six_list,
    parse_table_release_list,
)


ADAPTERS = {
    "SRC-001": parse_nfra_docinfo_json,
    "SRC-003": parse_csrc_search_json,
    "SRC-006": parse_hkma_list,
    "SRC-007": parse_sfc_list,
    "SRC-021": parse_fca_list,
    "SRC-023": parse_govuk_list,
    "SRC-040": parse_apra_list,
    "SRC-064": parse_euronext_list,
    "SRC-073": parse_jpx_list,
    "SRC-089": parse_dbg_list,
    "SRC-143": parse_eurex_list,
    "SRC-144": parse_crypto_finance_list,
    "SRC-152": parse_hkex_list,
    "SRC-045": parse_osc_list,
    "SRC-014": parse_table_release_list,
    "SRC-016": parse_table_release_list,
    "SRC-035": parse_article_release_list,
    "SRC-037": parse_article_release_list,
    "SRC-046": parse_article_release_list,
    "SRC-048": parse_bma_list,
    "SRC-050": parse_korea_fsc_list,
    "SRC-052": parse_adgm_list,
    "SRC-070": parse_six_list,
    "SRC-076": parse_shfe_notice_list,
    "SRC-087": parse_b3_list,
    "SRC-123": parse_naic_list,
    "SRC-025": parse_bafin_press_list,
    "SRC-126": parse_article_release_list,
    "SRC-130": parse_article_release_list,
    "SRC-134": parse_article_release_list,
    "SRC-182": parse_eex_list,
    "SRC-183": parse_360t_press_list,
    "SRC-184": parse_dtcc_list,
}


def get_adapter(source):
    return ADAPTERS.get(source.get("id", ""))
