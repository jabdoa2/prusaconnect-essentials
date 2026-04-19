from lib.gcode_handling import (
    parse_gcode,
    GCodeLineCommentMethodCall,
    GCodeLineInstruction,
)
from lib.prusa_connect import GCodeFileType


def test_parser_sync_call():
    s = '; PCE-WAIT: test_call(arg1=1, arg2="Check3", arg3=1.2, arg4=True, arg5=False, arg6=None)\nM0 Check3'
    lines = parse_gcode(s, GCodeFileType.BGCode)
    assert len(lines) == 2
    assert isinstance(lines[0], GCodeLineCommentMethodCall)
    assert isinstance(lines[1], GCodeLineInstruction)
