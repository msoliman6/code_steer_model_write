"""Plan §12: recipes are packages the harness discovers; a project repo registers its recipe by
entry point and the template never names it."""

from types import SimpleNamespace

from code_steer_model_write.recipes import registry


class _EP:
    def __init__(self, name, obj):
        self.name, self._obj = name, obj

    def load(self):
        return self._obj


def test_bundled_recipes_resolve_and_the_project_recipe_comes_first(monkeypatch):
    registry._installed.cache_clear()
    monkeypatch.setattr(registry, "entry_points", lambda group: [])
    assert registry.names() == ["code_builder", "debate"]
    assert registry.get("debate").spec.name == "debate"
    registry._installed.cache_clear()
    fake = SimpleNamespace(spec=SimpleNamespace(name="coder"))
    monkeypatch.setattr(
        registry,
        "entry_points",
        lambda group: [_EP("coder", lambda: fake)] if group == "csmw.recipes" else [],
    )
    try:
        assert registry.names()[0] == "coder" and registry.default_name() == "coder"
        assert registry.get("coder") is fake
    finally:
        registry._installed.cache_clear()


def test_walk_legs_from_installed_packages(monkeypatch):
    legs = {"happy": lambda tmp: "ok"}
    monkeypatch.setattr(
        registry, "entry_points", lambda group: [_EP("coder", legs)] if group == "csmw.walk_legs" else []
    )
    assert registry.walk_legs() == {"coder": legs}
