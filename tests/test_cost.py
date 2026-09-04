"""Rule 14: tokens are stored; a price is looked up on read from LiteLLM's map, overridden by
prices.json, and may be unknown."""

from code_steer_model_write import config


def test_the_map_prices_current_models_and_a_dated_id_finds_its_family():
    assert config.price_of("gpt-5.4-mini") is not None
    assert config.price_of("claude-sonnet-5") is not None
    assert config.price_of("claude-haiku-4-5-20251001") == config.price_of("claude-haiku-4-5")
    assert config.price_of("no-such-model-at-all") is None


def test_cost_and_its_words(tmp_path, monkeypatch):
    monkeypatch.setenv("CSMW_PRICES_FILE", str(tmp_path / "none.json"))
    pin, pout = config.price_of("claude-haiku-4-5")
    assert config.cost_usd("claude-haiku-4-5", 1_000_000, 0) == pin
    assert config.cost_usd("no-such-model-at-all", 10, 10) is None
    assert config.usd(None) == "$?"
    assert config.usd(0.123) == "$0.12"
    assert config.usd(0.001) == "$<0.01"


def test_prices_json_overrides_the_map(tmp_path, monkeypatch):
    p = tmp_path / "prices.json"
    p.write_text('{"gpt-5.4-mini": [0.5, 2.0], "my-negotiated-model": [9, 9]}')
    monkeypatch.setenv("CSMW_PRICES_FILE", str(p))
    assert config.price_of("gpt-5.4-mini") == (0.5, 2.0)
    assert config.price_of("my-negotiated-model") == (9.0, 9.0)
    assert config.cost_usd("my-negotiated-model", 1_000_000, 1_000_000) == 18.0
