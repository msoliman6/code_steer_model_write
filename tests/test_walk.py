"""The offline walk as a test: every leg of every recipe, zero tokens (rule 12)."""

from code_steer_model_write import walk


def test_every_leg_green():
    rs = walk.run("all")
    red = [r for r in rs if not r.ok]
    assert not red, "\n" + walk.report(rs)
