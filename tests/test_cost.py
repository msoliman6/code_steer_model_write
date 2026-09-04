"""Rule 14: tokens are stored, a price is looked up on read and may be unknown."""

from code_steer_model_write import config


def test_prefix_match_prefers_the_longest_key():
    assert config.price_of("claude-haiku-4-5-20251001") == config.PRICE_PER_MTOK["claude-haiku-4-5"]
    assert config.price_of("gpt-5-mini") == config.PRICE_PER_MTOK["gpt-5-mini"]
    assert config.price_of("gpt-5") == config.PRICE_PER_MTOK["gpt-5"]
    assert config.price_of("fake-a") is None
    assert (
        config.price_of("gpt-5.4-mini") is None
    )  # a newer model is unpriced until prices.json says otherwise


def test_cost_and_its_words():
    assert config.cost_usd("claude-haiku-4-5", 1_000_000, 0) == 1.0
    assert config.cost_usd("no-such-model", 10, 10) is None
    assert config.usd(None) == ""
    assert config.usd(0.123) == "≈ $0.12"
    assert config.usd(0.001) == "≈ <$0.01"


def test_prices_json_overlays_the_table(tmp_path, monkeypatch):
    p = tmp_path / "prices.json"
    p.write_text('{"gpt-5.4-mini": [0.5, 2.0], "claude-haiku-4-5": [9, 9]}')
    monkeypatch.setenv("CSMW_PRICES_FILE", str(p))
    assert config.price_of("gpt-5.4-mini") == (0.5, 2.0)
    assert config.price_of("claude-haiku-4-5") == (9.0, 9.0)
