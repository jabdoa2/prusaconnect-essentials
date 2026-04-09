import pybgcode
from pybgcode import EResult


def convert_bgcode(file_in, file_out):
    in_f = pybgcode.open(file_in, "rb")
    out_f = pybgcode.open(file_out, "w")

    assert in_f
    assert out_f

    assert pybgcode.is_open(in_f)
    assert pybgcode.is_open(out_f)

    res = pybgcode.from_binary_to_ascii(in_f, out_f, True)
    assert res == EResult.Success


def parse_allowed_build_plate_values(gcode_str) -> list[int]:
    search_string = "; allowed_build_plates="

    allowed_build_plate_lines = [
        line for line in gcode_str.split("\n") if line.startswith(search_string)
    ]
    if not allowed_build_plate_lines:
        print(
            "WARNING: Did not find any allowed_build_plates lines in gcode. Will assume nothing is allowed."
        )
        return []

    if len(allowed_build_plate_lines) > 1:
        print(
            "WARNING: Found more than one allowed_build_plates lines. Will use first line."
        )

    allowed_build_plate_str_values = allowed_build_plate_lines[0][
        len(search_string) :
    ].split(",")
    try:
        allowed_build_plate_values = [
            int(value) for value in allowed_build_plate_str_values
        ]
    except ValueError:
        print(
            f"Failed to parse allowed_build_plates values to int: {allowed_build_plate_str_values}"
        )
        return []

    return allowed_build_plate_values
