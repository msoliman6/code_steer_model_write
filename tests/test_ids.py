from code_steer_model_write.ids import Prefix, assign, find_ids, fmt, is_id, next_id, number_of


def test_format_and_parse():
    assert fmt(Prefix.FINDING, 7) == "F-0007"
    assert is_id("F-0007") and not is_id("F-7") and not is_id("f-0007")
    assert number_of("C-0123") == 123


def test_next_is_max_plus_one_never_reuse():
    assert next_id(Prefix.CLAUSE, []) == "C-0001"
    assert next_id(Prefix.CLAUSE, ["C-0001", "C-0005", "F-0009"]) == "C-0006"
    assert assign(Prefix.PROPERTY, 3, ["P-0002"]) == ["P-0003", "P-0004", "P-0005"]


def test_find_ids_in_text():
    assert find_ids("see C-0001 and P-0004, then C-0001 again") == ["C-0001", "P-0004"]
