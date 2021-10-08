"""FluxLED Models Database."""

from enum import Enum


class LevelWriteMode(Enum):
    ALL = 0x00
    COLORS = 0xF0
    WHITES = 0x0F


# Color modes
COLOR_MODE_DIM = "DIM"
COLOR_MODE_CCT = "CCT"
COLOR_MODE_RGB = "RGB"
COLOR_MODE_RGBW = "RGBW"
COLOR_MODE_RGBWW = "RGBWW"
COLOR_MODE_ADDRESSABLE = "ADDRESSABLE"

STATE_CHANGE_LATENCY = 1
MIN_TEMP = 2700
MAX_TEMP = 6500

WRITE_ALL_COLORS = (LevelWriteMode.ALL, LevelWriteMode.COLORS)
WRITE_ALL_WHITES = (LevelWriteMode.ALL, LevelWriteMode.WHITES)

# Modes
MODE_SWITCH = "switch"
MODE_COLOR = "color"
MODE_WW = "ww"
MODE_CUSTOM = "custom"
MODE_MUSIC = "music"
MODE_PRESET = "preset"

# Transitions
TRANSITION_JUMP = "jump"
TRANSITION_STROBE = "strobe"
TRANSITION_GRADUAL = "gradual"

STATIC_MODES = {MODE_COLOR, MODE_WW}

# Non light device models
MODEL_NUM_SWITCH = 0x97

COLOR_MODES_RGB = {COLOR_MODE_RGB, COLOR_MODE_RGBW, COLOR_MODE_RGBWW}
COLOR_MODES_RGB_CCT = {  # AKA Split RGB & CCT modes used for bulbs/lamps
    COLOR_MODE_RGB,
    COLOR_MODE_CCT,
}
COLOR_MODES_RGB_W = {  # AKA RGB/W in the Magic Home Pro app
    COLOR_MODE_RGB,
    COLOR_MODE_DIM,
}

DEFAULT_MODE = COLOR_MODE_RGB
