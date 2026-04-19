import os
import tempfile
from enum import Enum
from typing import NamedTuple

import pybgcode as bg
from pybgcode._bgcode import skip_block_content, GCodeBlock  # ty: ignore[unresolved-import]

from pybgcode import EResult

from lib.gcode_parse_call import parse_function_call
from lib.prusa_connect import GCodeFile, GCodeFileType

COMMAND_PREFIX_ASYNC = "; PCE: "
COMMAND_PREFIX_SYNC = "; PCE-WAIT: "


class GCodeLineComment(NamedTuple):
    cmd_cnt: int
    line_number: int
    sdpos: int
    raw_str: str
    comment: str


class MethodCallsType(Enum):
    ASYNC = "async"
    SYNC = "sync"


class GCodeLineCommentMethodCall(NamedTuple):
    cmd_cnt: int
    line_number: int
    sdpos: int
    raw_str: str
    comment: str
    handler_name: str
    handler_params: dict
    call_type: MethodCallsType


class GCodeLineInstruction(NamedTuple):
    cmd_cnt: int
    line_number: int
    sdpos: int
    raw_str: str
    code: str
    params: str | None


GCodeLine = GCodeLineComment | GCodeLineCommentMethodCall | GCodeLineInstruction


class MarlinGCodeBlock(NamedTuple):
    sdpos_start: int
    sdpos_end: int
    gcode_line: GCodeLineInstruction
    async_method_call_lines: list[GCodeLineCommentMethodCall]
    sync_method_call_line: GCodeLineCommentMethodCall | None
    comment_lines: list[GCodeLineComment]


def parse_gcode(gcode_str: str, file_type: GCodeFileType) -> list[GCodeLine]:
    result = []
    line_number = 0
    cmd_cnt = 0
    sdpos = 0
    for line_str in gcode_str.split("\n"):
        stripped_line = line_str.lstrip()

        if not stripped_line:
            sdpos += 1
            continue
        elif stripped_line.startswith(COMMAND_PREFIX_ASYNC):
            handler_name, handler_kwargs = parse_function_call(
                stripped_line[len(COMMAND_PREFIX_ASYNC) :]
            )
            line = GCodeLineCommentMethodCall(
                comment=stripped_line[len(COMMAND_PREFIX_ASYNC) :],
                line_number=line_number,
                cmd_cnt=cmd_cnt,
                sdpos=sdpos,
                raw_str=line_str,
                handler_name=handler_name,
                handler_params=handler_kwargs,
                call_type=MethodCallsType.ASYNC,
            )
        elif stripped_line.startswith(COMMAND_PREFIX_SYNC):
            handler_name, handler_kwargs = parse_function_call(
                stripped_line[len(COMMAND_PREFIX_SYNC) :]
            )
            line = GCodeLineCommentMethodCall(
                comment=stripped_line[len(COMMAND_PREFIX_SYNC) :],
                line_number=line_number,
                cmd_cnt=cmd_cnt,
                sdpos=sdpos,
                raw_str=line_str,
                handler_name=handler_name,
                handler_params=handler_kwargs,
                call_type=MethodCallsType.SYNC,
            )
        elif stripped_line[0] == ";":
            line = GCodeLineComment(
                comment=stripped_line[1:],
                line_number=line_number,
                cmd_cnt=cmd_cnt,
                sdpos=sdpos,
                raw_str=line_str,
            )
        else:
            parts = stripped_line.split(";", 1)
            gcode = parts[0].strip()
            gcode_parts = gcode.split(" ", 1)
            line = GCodeLineInstruction(
                code=gcode_parts[0],
                params=gcode_parts[1] if len(gcode_parts) > 1 else None,
                line_number=line_number,
                cmd_cnt=cmd_cnt,
                sdpos=sdpos,
                raw_str=line_str,
            )
            cmd_cnt += 1
        line_number += 1

        if file_type == GCodeFileType.BGCode:
            if isinstance(line, GCodeLineInstruction) and line.code.startswith("G"):
                # emulate how the prusa media_prefect code work. it looses track of the correct offset.
                # we try to count incorrectly in the same way.
                # needed until this is resolved: https://github.com/prusa3d/Prusa-Firmware-Buddy/issues/5249
                sdpos += len(line_str.replace(" ", "")) + 1
            else:
                # special case is only for G instructions. Everything else is sane.
                sdpos += len(line_str) + 1
        else:
            sdpos += len(line_str) + 1

        result.append(line)

    return result


def group_gcode_lines_like_marlin(
    gcode_lines: list[GCodeLine],
) -> list[MarlinGCodeBlock]:
    blocks = []
    current_block_async_method_call_lines = []
    current_block_sync_method_call_line = None
    current_block_comment_lines = []
    sdpos_start = None
    for gcode_line in gcode_lines:
        if not sdpos_start:
            sdpos_start = gcode_line.sdpos
        if isinstance(gcode_line, GCodeLineInstruction):
            if current_block_sync_method_call_line and not gcode_line.code.startswith(
                "M0"
            ):
                print(
                    "WARNING: Found sync instruction before non M0 instruction. This is currently not supported."
                )

            # TODO: refactor sdlen_end
            sdlen_end = gcode_line.sdpos + len(gcode_line.raw_str.replace(" ", ""))
            blocks.append(
                MarlinGCodeBlock(
                    sdpos_start=sdpos_start,
                    sdpos_end=sdlen_end,
                    gcode_line=gcode_line,
                    sync_method_call_line=current_block_sync_method_call_line,
                    async_method_call_lines=current_block_async_method_call_lines,
                    comment_lines=current_block_comment_lines,
                )
            )
            current_block_async_method_call_lines = []
            current_block_sync_method_call_line = None
            current_block_comment_lines = []
            sdpos_start = None
        elif isinstance(gcode_line, GCodeLineComment):
            current_block_comment_lines.append(gcode_line)
        elif isinstance(gcode_line, GCodeLineCommentMethodCall):
            if gcode_line.call_type == MethodCallsType.ASYNC:
                current_block_async_method_call_lines.append(gcode_line)
            else:
                if current_block_sync_method_call_line is not None:
                    print(
                        "WARNING: Only one sync line per G-Code is supported. Will use only the last instruction!"
                    )
                current_block_sync_method_call_line = gcode_line

    if (
        current_block_comment_lines
        or current_block_async_method_call_lines
        or current_block_sync_method_call_line
    ):
        print("WARNING: Ignoring comments after the last G-Code.")

    return blocks


def find_gcode_at_offset(gcode_lines: list[GCodeLine], offset: int) -> GCodeLine | None:
    found_line = False
    for line in gcode_lines:
        # find the first line past our offset
        if line.sdpos + len(line.raw_str) > offset:
            found_line = True
        # continue until we found the first gcode
        if found_line and isinstance(line, GCodeLineInstruction):
            return line
    return None


def convert_bgcode_file_to_gcode_file(file_in, file_out):
    in_f = bg.open(file_in, "rb")
    out_f = bg.open(file_out, "w")

    assert in_f
    assert out_f

    assert bg.is_open(in_f)
    assert bg.is_open(out_f)

    res = bg.from_binary_to_ascii(in_f, out_f, True)
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


def convert_gcode_file_like_prusa_marlin(gcode_file: GCodeFile) -> str:
    if gcode_file.file_type == GCodeFileType.BGCode:
        return convert_bgcode_to_gcode_like_prusa_marlin(gcode_file.content_raw)

    # by default just decode
    return gcode_file.content_raw.decode()


def convert_bgcode_to_gcode_like_prusa_marlin(bgcode_bytes: bytes) -> str:
    """Extract only the G-Code sections from a bgcode byte string like Prusa does in Marlin."""
    gcode_text = []
    with tempfile.TemporaryDirectory() as temp_dir_name:
        job_path = os.path.join(temp_dir_name, "job.bgcode")
        with open(job_path, "wb") as f:
            f.write(bgcode_bytes)

        fp = bg.open(job_path, "r")

        file_header = bg.FileHeader()
        file_header.read(fp)

        block_header = bg.BlockHeader()

        res = bg.read_next_block_header(fp, file_header, block_header)

        while res == bg.EResult.Success:
            # Only decode G-code blocks
            if block_header.type == bg.EBlockType.GCode.value:
                gcode_block = GCodeBlock()
                res = gcode_block.read_data(fp, file_header, block_header)
                if res != bg.EResult.Success:
                    raise AssertionError("Failed to read gcode")

                gcode_text.append(gcode_block.raw_data)

            else:
                skip_block_content(fp, file_header, block_header)

            res = bg.read_next_block_header(fp, file_header, block_header)

        bg.close(fp)

    return "".join(gcode_text)


def convert_bgcode_to_gcode(bgcode_bytes: bytes) -> str:
    with tempfile.TemporaryDirectory() as tmpdirname:
        with open(os.path.join(tmpdirname, "job.bgcode"), "wb") as f:
            f.write(bgcode_bytes)

        convert_bgcode_file_to_gcode_file(
            os.path.join(tmpdirname, "job.bgcode"),
            os.path.join(tmpdirname, "job.gcode"),
        )

        with open(os.path.join(tmpdirname, "job.gcode"), "r") as f:
            gcode = f.read()
    return gcode
