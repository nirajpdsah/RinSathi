from utils.income_parsers import normalize_to_monthly_estimate


def test_monthly_form_amounts_add_directly():
    signals = []
    for month in ["2026-06", "2026-05", "2026-04"]:
        signals.extend([
            {"date": f"{month}-10", "amount_npr": 30000, "source": "esewa", "type": "regular"},
            {"date": f"{month}-20", "amount_npr": 28500, "source": "remittance", "type": "irregular_periodic"},
            {"date": f"{month}-01", "amount_npr": 35000, "source": "cooperative", "type": "regular"},
        ])

    estimate = normalize_to_monthly_estimate(signals)

    assert estimate["mean_monthly_npr"] == 93500.0
    assert estimate["sources"] == ["cooperative", "esewa", "remittance"]
