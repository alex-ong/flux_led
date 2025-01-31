#!/usr/bin/env python
"""
This is a utility for controlling stand-alone Flux WiFi LED light bulbs.

The protocol was reverse-engineered by studying packet captures between a
bulb and the controlling "Magic Home" mobile app.  The code here dealing

with the network protocol is littered with magic numbers, and ain't so pretty.
But it does seem to work!

So far most of the functionality of the apps is available here via the CLI
and/or programmatically.

The classes in this project could very easily be used as an API, and incorporated into a GUI app written
in PyQt, Kivy, or some other framework.

##### Available:
* Discovering bulbs on LAN
* Turning on/off bulb
* Get state information
* Setting "warm white" mode
* Setting single color mode
* Setting preset pattern mode
* Setting custom pattern mode
* Reading timers
* Setting timers

##### Some missing pieces:
* Initial administration to set up WiFi SSID and passphrase/key.
* Remote access administration
* Music-relating pulsing. This feature isn't so impressive on the Magic Home app,
and looks like it might be a bit of work.

##### Cool feature:
* Specify colors with names or web hex values.  Requires that python "webcolors"
package is installed.  (Easily done via pip, easy_install, or apt-get, etc.)
See the following for valid color names: http://www.w3schools.com/html/html_colornames.asp

"""

import datetime
import logging
from optparse import OptionGroup, OptionParser, Values
import sys
from typing import Any, List, Optional, Tuple

from flux_led.device import WifiLedBulb
from flux_led.pattern import PresetPattern
from flux_led.scanner import BulbScanner, FluxLEDDiscovery
from flux_led.timer import LedTimer
from flux_led.utils import utils
from flux_led.const import ATTR_IPADDR, ATTR_ID

_LOGGER = logging.getLogger(__name__)


# =======================================================================
def showUsageExamples() -> None:
    example_text = """
Examples:

Scan network:
    %prog% -s

Scan network and show info about all:
    %prog% -sSti

Turn on:
    %prog% 192.168.1.100 --on
    %prog% 192.168.1.100 -192.168.1.101 -1

Turn on all bulbs on LAN:
    %prog% -sS --on

Turn off:
    %prog% 192.168.1.100 --off
    %prog% 192.168.1.100 --0
    %prog% -sS --off

Set warm white, 75%
    %prog% 192.168.1.100 -w 75

Set cold white, 55%
    %prog% 192.168.1.100 -d 55

Set CCT, 3500 85%
    %prog% 192.168.1.100 -k 3500 85

Set fixed color red :
    %prog% 192.168.1.100 -c Red
    %prog% 192.168.1.100 -c 255,0,0
    %prog% 192.168.1.100 -c "#FF0000"

Set RGBW 25 100 200 50:
    %prog% 192.168.1.100 -c 25,100,200,50

Set RGBWW 25 100 200 50 30:
    %prog% 192.168.1.100 -c 25,100,200,50,30

Set preset pattern #35 with 40% speed:
    %prog% 192.168.1.100 -p 35 40

Set custom pattern 25% speed, red/green/blue, gradual change:
    %prog% 192.168.1.100 -C gradual 25 "red green (0,0,255)"

Sync all bulb's clocks with this computer's:
    %prog% -sS --setclock

Set timer #1 to turn on red at 5:30pm on weekdays:
    %prog% 192.168.1.100 -T 1 color "time:1730;repeat:12345;color:red"

Deactivate timer #4:
    %prog% 192.168.1.100 -T 4 inactive ""

Use --timerhelp for more details on setting timers
    """

    print(example_text.replace("%prog%", sys.argv[0]))


def showTimerHelp() -> None:
    timerhelp_text = """
    There are 6 timers available for each bulb.

Mode Details:
    inactive:   timer is inactive and unused
    poweroff:   turns off the light
    default:    turns on the light in default mode
    color:      turns on the light with specified color
    preset:     turns on the light with specified preset and speed
    warmwhite:  turns on the light with warm white at specified brightness

Settings available for each mode:
    Timer Mode | Settings
    --------------------------------------------
    inactive:   [none]
    poweroff:   time, (repeat | date)
    default:    time, (repeat | date)
    color:      time, (repeat | date), color
    preset:     time, (repeat | date), code, speed
    warmwhite:  time, (repeat | date), level
    sunrise:    time, (repeat | date), startBrightness, endBrightness, duration
    sunset:     time, (repeat | date), startBrightness, endBrightness, duration

Setting Details:

    time: 4 digit string with zeros, no colons
        e.g:
        "1000"  - for 10:00am
        "2312"  - for 11:23pm
        "0315"  - for 3:15am

    repeat: Days of the week that the timer should repeat
            (Mutually exclusive with date)
            0=Sun, 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat
        e.g:
        "0123456"  - everyday
        "06"       - weekends
        "12345"    - weekdays
        "2"        - only Tuesday

    date: Date that the one-time timer should fire
            (Mutually exclusive with repeat)
        e.g:
        "2015-09-13"
        "2016-12-03"

    color: Color name, hex code, or rgb triple

    level: Level of the warm while light (0-100)

    code:  Code of the preset pattern (use -l to list them)

    speed: Speed of the preset pattern transitions (0-100)

    startBrightness: starting brightness of warmlight (0-100)

    endBrightness: ending brightness of warmlight (0-100)

    duration: transition time in minutes

Example setting strings:
    "time:2130;repeat:0123456"
    "time:2130;date:2015-08-11"
    "time:1245;repeat:12345;color:123,345,23"
    "time:1245;repeat:12345;color:green"
    "time:1245;repeat:06;code:50;speed:30"
    "time:0345;date:2015-08-11;level:100"
    """

    print(timerhelp_text)


def processSetTimerArgs(parser: OptionParser, args: Any) -> LedTimer:  # noqa: C901
    mode = args[1]
    num = args[0]
    settings = args[2]

    if not num.isdigit() or int(num) > 6 or int(num) < 1:
        parser.error("Timer number must be between 1 and 6")

    # create a dict from the settings string
    settings_list = settings.split(";")
    settings_dict = {}
    for s in settings_list:
        pair = s.split(":")
        key = pair[0].strip().lower()
        val = ""
        if len(pair) > 1:
            val = pair[1].strip().lower()
        settings_dict[key] = val

    keys = list(settings_dict.keys())
    timer = LedTimer()

    if mode == "inactive":
        # no setting needed
        timer.setActive(False)

    elif mode in [
        "poweroff",
        "default",
        "color",
        "preset",
        "warmwhite",
        "sunrise",
        "sunset",
    ]:
        timer.setActive(True)

        if "time" not in keys:
            parser.error(f"This mode needs a time: {mode}")
        if "repeat" in keys and "date" in keys:
            parser.error(f"This mode only a repeat or a date, not both: {mode}")

        # validate time format
        if len(settings_dict["time"]) != 4 or not settings_dict["time"].isdigit():
            parser.error("time must be a 4 digits")
        hour = int(settings_dict["time"][0:2:])
        minute = int(settings_dict["time"][2:4:])
        if hour > 23:
            parser.error("timer hour can't be greater than 23")
        if minute > 59:
            parser.error("timer minute can't be greater than 59")

        timer.setTime(hour, minute)

        # validate date format
        if "repeat" not in keys and "date" not in keys:
            # Generate date for next occurance of time
            print("No time or repeat given. Defaulting to next occurance of time")
            now = datetime.datetime.now()
            dt = now.replace(hour=hour, minute=minute)
            if utils.date_has_passed(dt):
                dt = dt + datetime.timedelta(days=1)
            # settings_dict["date"] = date
            timer.setDate(dt.year, dt.month, dt.day)
        elif "date" in keys:
            try:
                dt = datetime.datetime.strptime(settings_dict["date"], "%Y-%m-%d")
                timer.setDate(dt.year, dt.month, dt.day)
            except ValueError:
                parser.error("date is not properly formatted: YYYY-MM-DD")

        # validate repeat format
        if "repeat" in keys:
            if len(settings_dict["repeat"]) == 0:
                parser.error("Must specify days to repeat")
            days = set()
            for c in list(settings_dict["repeat"]):
                if c not in ["0", "1", "2", "3", "4", "5", "6"]:
                    parser.error("repeat can only contain digits 0-6")
                days.add(int(c))

            repeat = 0
            if 0 in days:
                repeat |= LedTimer.Su
            if 1 in days:
                repeat |= LedTimer.Mo
            if 2 in days:
                repeat |= LedTimer.Tu
            if 3 in days:
                repeat |= LedTimer.We
            if 4 in days:
                repeat |= LedTimer.Th
            if 5 in days:
                repeat |= LedTimer.Fr
            if 6 in days:
                repeat |= LedTimer.Sa
            timer.setRepeatMask(repeat)

        if mode == "default":
            timer.setModeDefault()

        if mode == "poweroff":
            timer.setModeTurnOff()

        if mode == "color":
            if "color" not in keys:
                parser.error("color mode needs a color setting")
            # validate color val
            c = utils.color_object_to_tuple(settings_dict["color"])  # type: ignore
            if c is None:
                parser.error("Invalid color value: {}".format(settings_dict["color"]))
            assert c is not None
            timer.setModeColor(c[0], c[1], c[2])  # type: ignore

        if mode == "preset":
            if "code" not in keys:
                parser.error(f"preset mode needs a code: {mode}")
            if "speed" not in keys:
                parser.error(f"preset mode needs a speed: {mode}")
            code = settings_dict["code"]
            speed = settings_dict["speed"]
            if not speed.isdigit() or int(speed) > 100:
                parser.error("preset speed must be a percentage (0-100)")
            if not code.isdigit():
                parser.error("preset code must be a valid integer")
            timer.setModePresetPattern(int(code), int(speed))

        if mode == "warmwhite":
            if "level" not in keys:
                parser.error(f"warmwhite mode needs a level: {mode}")
            level = settings_dict["level"]
            if not level.isdigit() or int(level) > 100:
                parser.error("warmwhite level must be a percentage (0-100)")
            timer.setModeWarmWhite(int(level))

        if mode == "sunrise" or mode == "sunset":
            if "startbrightness" not in keys:
                parser.error(f"{mode} mode needs a startBrightness (0% -> 100%)")
            startBrightness = int(settings_dict["startbrightness"])

            if "endbrightness" not in keys:
                parser.error(f"{mode} mode needs an endBrightness (0% -> 100%)")
            endBrightness = int(settings_dict["endbrightness"])

            if "duration" not in keys:
                parser.error(f"{mode} mode needs a duration (minutes)")
            duration = int(settings_dict["duration"])

            if mode == "sunrise":
                timer.setModeSunrise(startBrightness, endBrightness, duration)

            elif mode == "sunset":
                timer.setModeSunset(startBrightness, endBrightness, duration)

    else:
        parser.error(f"Not a valid timer mode: {mode}")

    return timer


def processCustomArgs(
    parser: OptionParser, args: Any
) -> Optional[Tuple[Any, int, List[Tuple[int, ...]]]]:
    if args[0] not in ["gradual", "jump", "strobe"]:
        parser.error(f"bad pattern type: {args[0]}")
        return None

    speed = int(args[1])

    # convert the string to a list of RGB tuples
    # it should have space separated items of either
    # color names, hex values, or byte triples
    try:
        color_list_str = args[2].strip()
        str_list = color_list_str.split(" ")
        color_list = []
        for s in str_list:
            c = utils.color_object_to_tuple(s)
            if c is not None:
                color_list.append(c)
            else:
                raise Exception

    except Exception:
        parser.error(
            "COLORLIST isn't formatted right.  It should be a space separated list of RGB tuples, color names or web hex values"
        )

    return args[0], speed, color_list


def parseArgs() -> Tuple[Values, Any]:  # noqa: C901
    parser = OptionParser()

    parser.description = "A utility to control Flux WiFi LED Bulbs. "
    # parser.description += ""
    # parser.description += "."
    power_group = OptionGroup(parser, "Power options (mutually exclusive)")
    mode_group = OptionGroup(parser, "Mode options (mutually exclusive)")
    info_group = OptionGroup(parser, "Program help and information option")
    other_group = OptionGroup(parser, "Other options")

    parser.add_option_group(info_group)
    info_group.add_option(
        "--debug",
        action="store_true",
        dest="debug",
        default=False,
        help="Enable debug logging",
    )
    info_group.add_option(
        "-e",
        "--examples",
        action="store_true",
        dest="showexamples",
        default=False,
        help="Show usage examples",
    )
    info_group.add_option(
        "",
        "--timerhelp",
        action="store_true",
        dest="timerhelp",
        default=False,
        help="Show detailed help for setting timers",
    )
    info_group.add_option(
        "-l",
        "--listpresets",
        action="store_true",
        dest="listpresets",
        default=False,
        help="List preset codes",
    )
    info_group.add_option(
        "--listcolors",
        action="store_true",
        dest="listcolors",
        default=False,
        help="List color names",
    )

    parser.add_option(
        "-s",
        "--scan",
        action="store_true",
        dest="scan",
        default=False,
        help="Search for bulbs on local network",
    )
    parser.add_option(
        "-S",
        "--scanresults",
        action="store_true",
        dest="scanresults",
        default=False,
        help="Operate on scan results instead of arg list",
    )
    power_group.add_option(
        "-1",
        "--on",
        action="store_true",
        dest="on",
        default=False,
        help="Turn on specified bulb(s)",
    )
    power_group.add_option(
        "-0",
        "--off",
        action="store_true",
        dest="off",
        default=False,
        help="Turn off specified bulb(s)",
    )
    parser.add_option_group(power_group)

    mode_group.add_option(
        "-c",
        "--color",
        dest="color",
        default=None,
        help="""For setting a single color mode.  Can be either color name, web hex, or comma-separated RGB triple.
        For setting an RGBW can be a comma-seperated RGBW list
        For setting an RGBWW can be a comma-seperated RGBWW list""",
        metavar="COLOR",
    )
    mode_group.add_option(
        "-w",
        "--warmwhite",
        dest="ww",
        default=None,
        help="Set warm white mode (LEVELWW is percent)",
        metavar="LEVELWW",
        type="int",
    )
    mode_group.add_option(
        "-d",
        "--coldwhite",
        dest="cw",
        default=None,
        help="Set cold white mode (LEVELCW is percent)",
        metavar="LEVELCW",
        type="int",
    )
    mode_group.add_option(
        "-k",
        "--CCT",
        dest="cct",
        default=None,
        help="Temperture and brightness (CCT Kelvin, brightness percent)",
        metavar="LEVELCCT",
        type="int",
        nargs=2,
    )
    mode_group.add_option(
        "-p",
        "--preset",
        dest="preset",
        default=None,
        help="Set preset pattern mode (SPEED is percent)",
        metavar="CODE SPEED",
        type="int",
        nargs=2,
    )
    mode_group.add_option(
        "-C",
        "--custom",
        dest="custom",
        metavar="TYPE SPEED COLORLIST",
        default=None,
        nargs=3,
        help="Set custom pattern mode. "
        + "TYPE should be jump, gradual, or strobe. SPEED is percent. "
        + "COLORLIST is a space-separated list of color names, web hex values, or comma-separated RGB triples",
    )
    mode_group.add_option(
        "-r",
        "--raw",
        dest="raw_packet",
        default=None,
        help="Send raw byte packet formatted as hex string",
        metavar="HEX",
        nargs=1,
    )
    parser.add_option_group(mode_group)

    parser.add_option(
        "-i",
        "--info",
        action="store_true",
        dest="info",
        default=False,
        help="Info about bulb(s) state",
    )
    parser.add_option(
        "",
        "--getclock",
        action="store_true",
        dest="getclock",
        default=False,
        help="Get clock",
    )
    parser.add_option(
        "",
        "--setclock",
        action="store_true",
        dest="setclock",
        default=False,
        help="Set clock to same as current time on this computer",
    )
    parser.add_option(
        "-t",
        "--timers",
        action="store_true",
        dest="showtimers",
        default=False,
        help="Show timers",
    )
    parser.add_option(
        "-T",
        "--settimer",
        dest="settimer",
        metavar="NUM MODE SETTINGS",
        default=None,
        nargs=3,
        help="Set timer. "
        + "NUM: number of the timer (1-6). "
        + "MODE: inactive, poweroff, default, color, preset, or warmwhite. "
        + "SETTINGS: a string of settings including time, repeatdays or date, "
        + "and other mode specific settings.   Use --timerhelp for more details.",
    )

    parser.add_option(
        "--protocol",
        dest="protocol",
        default=None,
        metavar="PROTOCOL",
        help="Set the device protocol. Currently only supports LEDENET",
    )

    other_group.add_option(
        "-v",
        "--volatile",
        action="store_true",
        dest="volatile",
        default=False,
        help="Don't persist mode setting with hard power cycle (RGB and WW modes only).",
    )
    parser.add_option_group(other_group)

    parser.usage = "usage: %prog [-sS10cwdkpCiltThe] [addr1 [addr2 [addr3] ...]."
    (options, args) = parser.parse_args()

    if options.debug:
        logging.basicConfig(level=logging.DEBUG)

    if options.showexamples:
        showUsageExamples()
        sys.exit(0)

    if options.timerhelp:
        showTimerHelp()
        sys.exit(0)

    if options.listcolors:
        for c in utils.get_color_names_list():  # type: ignore
            print(f"{c}, ")
        print("")
        sys.exit(0)

    if options.settimer:
        new_timer = processSetTimerArgs(parser, options.settimer)
        options.new_timer = new_timer
    else:
        options.new_timer = None

    mode_count = 0
    if options.color:
        mode_count += 1
    if options.ww:
        mode_count += 1
    if options.cw:
        mode_count += 1
    if options.cct:
        mode_count += 1
    if options.preset:
        mode_count += 1
    if options.custom:
        mode_count += 1
    if options.raw_packet:
        mode_count += 1

    if mode_count > 1:
        parser.error(
            "options --color, --*white, --preset, --CCT, and --custom are mutually exclusive"
        )

    if options.on and options.off:
        parser.error("options --on and --off are mutually exclusive")

    if options.custom:
        options.custom = processCustomArgs(parser, options.custom)

    if options.color:
        options.color = utils.color_object_to_tuple(options.color)
        if options.color is None:
            parser.error("bad color specification")

    # asking for timer info, implicitly gets the state
    if options.showtimers:
        options.info = True

    op_count = mode_count
    if options.on:
        op_count += 1
    if options.off:
        op_count += 1
    if options.info:
        op_count += 1
    if options.getclock:
        op_count += 1
    if options.setclock:
        op_count += 1
    if options.listpresets:
        op_count += 1
    if options.settimer:
        op_count += 1

    if (not options.scan or options.scanresults) and (op_count == 0):
        parser.error("An operation must be specified")

    # if we're not scanning, IP addresses must be specified as positional args
    if not options.scan and not options.scanresults:
        if len(args) == 0:
            parser.error(
                "You must specify at least one IP address as an argument, or use scan results"
            )

    return (options, args)


# -------------------------------------------
def main() -> None:  # noqa: C901
    (options, args) = parseArgs()
    scanner = BulbScanner()

    if options.scan:
        scanner.scan(timeout=6)
        bulb_info_list = scanner.getBulbInfo()
        # we have a list of buld info dicts
        addrs = []
        if options.scanresults and len(bulb_info_list) > 0:
            for b in bulb_info_list:
                addrs.append(b["ipaddr"])
        else:
            print(f"{len(bulb_info_list)} bulbs found")
            for b in bulb_info_list:
                print("  {} {}".format(b["id"], b["ipaddr"]))
            sys.exit(0)
    else:
        for addr in args:
            scanner.scan(timeout=6, address=addr)
        bulb_info_list = scanner.getBulbInfo()
        found_addrs = {discovery[ATTR_IPADDR] for discovery in bulb_info_list}
        for addr in args:
            if addr in found_addrs:
                continue
            bulb_info_list.append(
                FluxLEDDiscovery({ATTR_IPADDR: addr, ATTR_ID: "Unknown ID"})
            )  # type: ignore

    # now we have our bulb list, perform same operation on all of them
    for info in bulb_info_list:
        try:
            bulb = WifiLedBulb(info["ipaddr"], discovery=info)
        except Exception as e:
            print("Unable to connect to bulb at [{}]: {}".format(info["ipaddr"], e))
            continue

        if options.getclock:
            print("{} [{}] {}".format(info["id"], info["ipaddr"], bulb.getClock()))

        if options.setclock:
            bulb.setClock()

        if options.protocol:
            bulb.setProtocol(options.protocol)

        if options.ww is not None:
            if options.ww > 100:
                print("Input can not be higher than 100%")
            else:
                print(f"Setting warm white mode, level: {options.ww}%")
                bulb.setWarmWhite(options.ww, not options.volatile)

        if options.cw is not None:
            if options.cw > 100:
                print("Input can not be higher than 100%")
            else:
                print(f"Setting cold white mode, level: {options.cw}%")
                bulb.setColdWhite(options.cw, not options.volatile)

        if options.cct is not None:
            if options.cct[1] > 100:
                print("Brightness can not be higher than 100%")
            elif options.cct[0] < 2700 or options.cct[0] > 6500:
                print("Color Temp must be between 2700 and 6500")
            else:
                print(
                    "Setting LED temperature {}K and brightness: {}%".format(
                        options.cct[0], options.cct[1]
                    )
                )
                bulb.setWhiteTemperature(
                    options.cct[0], options.cct[1] * 2.55, not options.volatile
                )

        if options.color is not None:
            print(
                f"Setting color RGB:{options.color}",
            )
            name = utils.color_tuple_to_string(options.color)
            if name is None:
                print()
            else:
                print(f"[{name}]")
            if any(i < 0 or i > 255 for i in options.color):
                print("Invalid value received must be between 0-255")
            elif len(options.color) == 3:
                bulb.setRgb(
                    options.color[0],
                    options.color[1],
                    options.color[2],
                    not options.volatile,
                )
            elif len(options.color) == 4:
                bulb.setRgbw(
                    options.color[0],
                    options.color[1],
                    options.color[2],
                    options.color[3],
                    not options.volatile,
                )
            elif len(options.color) == 5:
                bulb.setRgbw(
                    options.color[0],
                    options.color[1],
                    options.color[2],
                    options.color[3],
                    not options.volatile,
                    None,
                    options.color[4],
                )

        elif options.custom is not None:
            bulb.setCustomPattern(
                options.custom[2], options.custom[1], options.custom[0]
            )
            print(
                "Setting custom pattern: {}, Speed={}%, {}".format(
                    options.custom[0], options.custom[1], options.custom[2]
                )
            )

        elif options.preset is not None:
            print(
                "Setting preset pattern: {}, Speed={}%".format(
                    PresetPattern.valtostr(options.preset[0]), options.preset[1]
                )
            )
            bulb.setPresetPattern(options.preset[0], options.preset[1])
        elif options.raw_packet is not None:
            print("Sending raw packet:", options.raw_packet)
            bulb.turnOn()
            byte_data = bytearray.fromhex(options.raw_packet)
            bulb._process_levels_change(byte_data, None)

        if options.on:
            print(f"Turning on bulb at {bulb.ipaddr}")
            bulb.turnOn()
        elif options.off:
            print(f"Turning off bulb at {bulb.ipaddr}")
            bulb.turnOff()

        if options.info:
            print(
                "{} [{}] {} ({})".format(info["id"], info["ipaddr"], bulb, bulb.model)
            )

        if options.settimer:
            timers = bulb.getTimers()
            num = int(options.settimer[0])
            print(f"New Timer ---- #{num}: {options.new_timer}")
            if options.new_timer.isExpired():
                print("[timer is already expired, will be deactivated]")
            timers[num - 1] = options.new_timer
            bulb.sendTimers(timers)

        if options.showtimers:
            timers = bulb.getTimers()
            num = 0
            for t in timers:
                num += 1
                print(f"  Timer #{num}: {t}")
            print("")

        if options.listpresets:
            print(bulb.effect_dict)

    sys.exit(0)


# Run in main folder as python -m flux_led.fluxled [args]
if __name__ == "__main__":
    main()
