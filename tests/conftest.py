from __future__ import annotations

import json
from pathlib import Path

import pytest

from finauto.assumptions import derive_assumptions
from finauto.schemas import CompanyFinancials, MarketData, ValuationInputs

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def fin() -> CompanyFinancials:
    return CompanyFinancials.model_validate_json(
        (FIXTURES / "financials_sample.json").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="session")
def market() -> MarketData:
    return MarketData.model_validate_json(
        (FIXTURES / "market_sample.json").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="session")
def inputs(fin, market) -> ValuationInputs:
    return ValuationInputs(
        financials=fin,
        market=market,
        assumptions=derive_assumptions(fin),
        locale="tr",
    )


@pytest.fixture(scope="session")
def workbook_path(inputs, tmp_path_factory) -> Path:
    from finauto.engine.builder import build_workbook

    out = tmp_path_factory.mktemp("wb") / "DEMO_valuation.xlsx"
    return build_workbook(inputs, out)
