import pytest
from lib.gcode_parse_call import parse_function_call, ParseError


def test_basic_example():
    s = "check_build_plate(allowed_build_plates=[2, 4], check_empty=True)"
    name, kwargs = parse_function_call(s)
    assert name == "check_build_plate"
    assert kwargs == {"allowed_build_plates": [2, 4], "check_empty": True}


def test_types():
    name, kwargs = parse_function_call("f(a=1, b=2.5, s='x', t=\"y\")")
    assert name == "f"
    assert kwargs == {"a": 1, "b": 2.5, "s": "x", "t": "y"}


def test_lowercase_true_false_none():
    name, kwargs = parse_function_call("g(x=true, y=false, z=none)")
    assert name == "g"
    assert kwargs == {"x": True, "y": False, "z": None}


def test_nested_collections():
    name, kwargs = parse_function_call("h(a=[1, [2, 3], true], d={'k': false})")
    assert name == "h"
    assert kwargs["a"] == [1, [2, 3], True]
    assert kwargs["d"] == {"k": False}


def test_errors_positional_arg():
    with pytest.raises(ParseError):
        parse_function_call("f(1)")


def test_errors_attribute_func():
    with pytest.raises(ParseError):
        parse_function_call("m.f(a=1)")
