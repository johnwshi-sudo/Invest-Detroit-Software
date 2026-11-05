import pytest

from underwriter.engine.common import annual_debt_service, max_loan_for_payment, monthly_payment
from underwriter.engine.cre import analyze_cre
from underwriter.engine.policy import check_policy, risk_rating
from underwriter.engine.small_business import analyze_small_business


def test_loan_math_matches_invest_detroit_sample_figures():
    # standard level-payment (PMT) mortgage math; the sample memo figures are covered by the golden test
    assert round(annual_debt_service(500_000, 0.085, 300)) == 48_314
    assert round(annual_debt_service(750_000, 0.10, 300)) == 81_783
    assert monthly_payment(100_000, 0.06, 0) == pytest.approx(500.0)  # interest only
    assert max_loan_for_payment(annual_debt_service(500_000, 0.07, 240), 0.07, 240) == pytest.approx(500_000)


def test_small_business_ebitda_dscr_and_breakeven(sb_deal):
    r = analyze_small_business(sb_deal)
    i = r["income"]["FY2023"]
    ni = 2_200_000 - 1_320_000 - 640_000 + 12_000 + 50_000 - 38_000 - 5_000
    assert i["net_income"] == ni
    assert i["ebitda"] == ni + 38_000 + 5_000 + 32_000              # NI + interest + taxes + depreciation
    ds = annual_debt_service(250_000, 0.09, 60) + 108_000
    assert i["debt_service"] == pytest.approx(ds)
    assert i["dscr"] == pytest.approx(i["ebitda"] / ds)
    assert i["dscr_ex_nonrecurring"] == pytest.approx((i["ebitda"] - 50_000) / ds)
    be = r["break_even"]["FY2023"]
    assert be["dscr"] == pytest.approx(1.0)
    assert be["gross_profit"] / be["revenue"] == pytest.approx(i["gross_profit"] / i["revenue"])
    assert r["growth"][0]["pct"] == pytest.approx(0.10)
    assert any("non-recurring" in f.message for f in r["flags"])


def test_small_business_ratios_use_360_day_year(sb_deal):
    r = analyze_small_business(sb_deal)
    q = r["ratios"]["FY2023"]
    assert q["ar_days"] == pytest.approx(260_000 * 360 / 2_200_000)
    assert q["inventory_days"] == pytest.approx(310_000 * 360 / 2_200_000)   # template: on sales
    assert q["ap_days"] == pytest.approx(160_000 * 360 / 1_320_000)
    assert q["current_ratio"] == pytest.approx((120_000 + 260_000 + 310_000) / (160_000 + 55_000 + 180_000))


def test_policy_flags_guarantee_gap_and_rate(sb_deal):
    r = analyze_small_business(sb_deal)
    pol = check_policy(sb_deal, r, "311812")
    items = {e["item"] for e in pol["exceptions"]}
    assert "Guarantee for owners > 20%" in items          # Owner B 40% not guaranteeing
    assert "Interest rate" not in items                     # 9% inside 8-10% non-RE range
    assert pol["line_of_business"]["line"] == "C&I"        # manufacturing NAICS


def test_cre_underwriter_adjustments(cre_deal):
    r = analyze_cre(cre_deal)
    L = r["id"]["lines"]
    assert L["re_taxes"][0] == 20_000 and L["re_taxes"][1] == pytest.approx(20_600)   # appraiser estimate, +3%
    assert L["leasing_marketing"][1:] == [0.0, 0.0]                                     # one-time lease-up
    assert L["insurance"][2] == pytest.approx(10_000 * 1.03 ** 2)                       # floored at 3% growth
    # blended vacancy 10% < 15% guideline -> general vacancy added in stabilized years
    assert r["blended_vacancy"][1] == pytest.approx(0.15)
    assert r["months"][0] == 6 and r["ds_proposed"][0] == pytest.approx(annual_debt_service(1_000_000, 0.085, 300) / 2)
    s = r["sensitivity"]
    assert all(d == pytest.approx(1.0) for d, ds in zip(s["dscr"], s["debt_service"]) if ds)


def test_cre_sources_uses_and_exceptions(cre_deal):
    r = analyze_cre(cre_deal)
    su = r["sources_uses"]
    assert su["total_uses"] == 1_710_000 and su["ltc"] == pytest.approx(1_000_000 / 1_710_000)
    assert su["hard_contingency_pct"] == pytest.approx(0.10)
    pol = check_policy(cre_deal, r, "531120")
    items = {e["item"] for e in pol["exceptions"]}
    assert "Hard cost contingency for rehab" in items          # 10% < 15%
    assert "Soft cost contingency for rehab" not in items      # 10% meets 10%
    assert "Background check" in items
    rr = risk_rating(cre_deal, r, pol)
    assert rr["rows"][2]["auto_score"] == 1   # LTV 50% < 55%
    assert rr["preliminary"] is not None


def test_sources_must_equal_uses(cre_deal):
    cre_deal.cre.sources[1].amount = 600_000
    r = analyze_cre(cre_deal)
    assert any(f.severity == "critical" and "Sources" in f.message for f in r["flags"])
