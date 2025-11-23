import gc

VERSION = '1.8.1.5'
print("\nMoon Clock: Version {0} ({1:,} RAM free)".format(VERSION, gc.mem_free()))

import json
import math
import time

import board
import busio
import displayio
from microcontroller import watchdog
from watchdog import WatchDogMode

from microcontroller import nvm
from rtc import RTC
from supervisor import reload

import color

from adafruit_bitmap_font import bitmap_font
from adafruit_display_text.label import Label
from adafruit_esp32spi import adafruit_esp32spi
from adafruit_lis3dh import LIS3DH_I2C
from adafruit_matrixportal.matrix import Matrix
from adafruit_matrixportal.network import Network
from digitalio import DigitalInOut, Pull

from secrets import secrets

print('Imports loaded - ({0:,} RAM free)'.format(gc.mem_free()))

########################################################################################################################

# NOTE: Do _not_ call watchdog.feed() too quickly or the board will crash 🤦‍♂️
WATCHDOG_TIMEOUT = 12   # This is close to the maximum allowed value
REFRESH_DELAY = 3
BIT_DEPTH = 6
TODAY = 0
TOMORROW = 1
NUM_EVENTS = 8

TODAY_RISE = '\u2191'   # ↑
TODAY_SET = '\u2193'    # ↓
TOMORROW_RISE = '\u219F'# ↟
TOMORROW_SET = '\u21A1' # ↡

COLOR_BRIGHTNESS = 0.5
MOON_PHEN_COLOR = color.adjust_brightness(0xB8BFC9, COLOR_BRIGHTNESS) # (grey blue)
PERCENT_COLOR = color.adjust_brightness(0x9B24F9, COLOR_BRIGHTNESS) # (purple)
SUN_PHEN_COLOR = color.adjust_brightness(0xFBDE2C, COLOR_BRIGHTNESS) # (sun yellow)
TIME_COLOR = color.adjust_brightness(0xA00000, COLOR_BRIGHTNESS) # (red)
DATE_COLOR = color.adjust_brightness(0x46BBDF, COLOR_BRIGHTNESS) # (aqua)
MOON_PHASE_COLOR = color.adjust_brightness(0xBB9946, COLOR_BRIGHTNESS)

LARGE_FONT = bitmap_font.load_font('/fonts/helvB12.bdf')
SMALL_FONT = bitmap_font.load_font('/fonts/helvR10.bdf')
SYMBOL_FONT = bitmap_font.load_font('/fonts/6x10.bdf')
LARGE_FONT.load_glyphs('0123456789:')
SMALL_FONT.load_glyphs('0123456789:/.%-+')
SYMBOL_FONT.load_glyphs('\u2191\u2193\u219F\u21A1') # ↑ ↓ ↟ ↡

# NOTE! These values correspond to the _order_ of the clock_face.append() calls below. See comments there
CLOCK_PERCENT = 5
CLOCK_TIME = 6
CLOCK_DATE = 7
# Element 8 is a symbol indicating next rise or set - Color is overridden by event colors
CLOCK_GLYPH = 8
# Element 9 is the time of (or time to) next rise/set event - Color is overridden by event colors
CLOCK_EVENT = 9
CLOCK_DATE = 10
CLOCK_PHASE = 11

current_event = NUM_EVENTS
asleep = False
latitude = None
longitude = None
utc_offset = None
esp32_wifi_sync = None
last_update_sec = None
brightness = 0.0
dwell = 10

########################################################################################################################

def parse_utc_offset(offset_str):
    """
    Convert a UTC offset string like '-700' or '-07:00' into (hours, minutes)
    """
    offset_str = offset_str.strip()
    if ':' in offset_str:
        hours_str, minutes_str = offset_str.split(':')
    else:
        # e.g., -700 → -7 hours, 0 minutes
        val = int(offset_str)
        hours_str = str(val // 100)
        minutes_str = str(abs(val) % 100)
    return int(hours_str), int(minutes_str)

def get_timestamp_from_esp32_wifi():
    global esp32_wifi_sync

    retries = 100
    esp_time = None
    if esp32_wifi_sync is None:
        print('Syncing WiFi with ESP32...', end='')
    while retries > 0 and not esp_time:
        try:
            esp_time = esp.get_time() # In UTC
            if not esp_time:
                raise Exception('No time returned')
            else:
                if esp32_wifi_sync is None: print()
        except Exception:
            print('.', end='')
            time.sleep(1)
            retries -= 1

    if esp_time:
        esp32_wifi_sync = True
        adjusted = esp_time[0] + (int(utc_offset) // 100) * 3600
        return time.localtime(adjusted)
    else:
        print('Failed to Sync WiFi with ESP32!')
        return None

def forced_asleep(): return nvm[0] == 1

# When forced asleep, the clock will remain sleeping until forced awake
def sleep(forced = False):
    global asleep
    if not asleep:
        # CP10: use root_group assignment
        display.root_group = snoozing
        display.refresh()
        asleep = True
    if forced: nvm[0:1] = bytes([1])

# When forced awake, will resume sleeping at the scheduled time, if configured to do so
def wake(forced = False):
    global asleep, datetime
    if asleep:
        # CP10: use root_group assignment
        display.root_group = clock_face
        display.refresh()
        asleep = False
        datetime = update_time()
    if forced: nvm[0:1] = bytes([0])

def sleep_or_wake():
    global asleep
    local_time = time.localtime()
    time_to_sleep = time.struct_time((local_time.tm_year, local_time.tm_mon, local_time.tm_mday, int(secrets['sleep_time'].split(':')[0]), int(secrets['sleep_time'].split(':')[1]), 0, -1, -1, -1))
    time_to_wake = time.struct_time((local_time.tm_year, local_time.tm_mon, local_time.tm_mday, int(secrets['wake_time'].split(':')[0]), int(secrets['wake_time'].split(':')[1]), 0, -1, -1, -1))

    sleepy_time = time_to_sleep < time.localtime() < time_to_wake
    if not asleep and sleepy_time:
        print('Current time is {0} and sleep_time is {1}. Going to sleep...'.format(hh_mm(local_time), hh_mm(time_to_sleep)))
        sleep() # Prints '...' until wake
    elif asleep and not sleepy_time:
        print("\nCurrent time is {0} and wake_time is {1}. Waking up...".format(hh_mm(local_time), hh_mm(time_to_wake)))
        wake()

def check_buttons():
    if not pin_down.value: # negating to indicate button pressed because Pull.UP 😵
        while not pin_down.value: pass
        sleep(forced = True)
    if not pin_up.value:
        while not pin_up.value: pass
        wake(forced = True)

def parse_time(timestring):
    if timestring == None:
        return None

    try:
        date_time = timestring.split('T')
        year_month_day = date_time[0].split('-')
        hour_minute = date_time[1].split('+')[0].split('-')[0].split(':')
    except Exception as e:
        print('Exception parsing timestring: {0} - {1}'.format(timestring, e))
        return None

    return time.struct_time(( # Note: Extra parenthesis are needed because struct_time() now takes a tuple
        int(year_month_day[0]),
        int(year_month_day[1]),
        int(year_month_day[2]),
        int(hour_minute[0]),
        int(hour_minute[1]),
        0,  # second not provided by API
        -1, # day of week
        -1, # day of year
        -1  # 1 = Yes, 0 = No, -1 = Unknown
    ))

def update_time():
    """Sync with ESP32 WiFi and return UTC struct_time"""
    time_struct = get_timestamp_from_esp32_wifi()
    if time_struct is not None:
        esp32_wifi_sync = True
        RTC().datetime = time_struct
        return time_struct  # Return struct_time, not mktime
    else:
        return RTC().datetime  # Already struct_time

def hh_mm(time_struct):
    """
    Return a 12-hour formatted string with alternating colon separator
    Example: 2:35 ... 2 35 ... 2:35 ... 2 35 ...
    """

    hour = (time_struct.tm_hour) % 24
    minute = (time_struct.tm_min) % 60

    # Adjust hour if minutes overflow
    if time_struct.tm_min >= 60:
        hour = (hour + 1) % 24

    # Format as 12-hour clock
    hour12 = 12 if hour % 12 == 0 else hour % 12
    # Flash colon time separator
    separator = ':' if time_struct.tm_sec % 2 == 0 else ' '
    return "{0}{1}{2:02d}".format(hour12, separator, minute)

def strftime(time_struct):
    """
    Return a date/time string
    Format: MM/DD/YYYY HH:MM:SS ±HHMM
    """
    hour = (time_struct.tm_hour) % 24
    minute = (time_struct.tm_min) % 60

    return "{0:0>2}/{1:0>2}/{2:0>4} {3:0>2}:{4:0>2}:{5:0>2} {6}".format(
        time_struct.tm_mon,
        time_struct.tm_mday,
        time_struct.tm_year,
        hour,
        minute,
        time_struct.tm_sec,
        utc_offset
    )

def display_event(name, event, icon, event_y, glyph_x, center_x, phase_glyph):
    """
    Display a sun/moon event on the clock.
    event_y: vertical position of the event
    glyph_x: horizontal position of the icon
    center_x: horizontal center of the text
    """
    if event is not None:
        time_struct = time.localtime(event)

    if name.startswith('Sun'):
        event_color = SUN_PHEN_COLOR
        if event is not None:
            hour = 12 if time_struct.tm_hour == 0 else time_struct.tm_hour
            event_time_str = '{0}:{1:0>2}'.format(hour, time_struct.tm_min)
    else:
        event_color = MOON_PHEN_COLOR
        if event is not None:
            event_time_str = '{0}:{1:0>2}'.format(time_struct.tm_hour, time_struct.tm_min)

    # Update glyph
    clock_face[CLOCK_GLYPH].color = event_color
    clock_face[CLOCK_GLYPH].text = icon
    clock_face[CLOCK_GLYPH].x = glyph_x
    clock_face[CLOCK_GLYPH].y = event_y

    # If no event, display placeholder
    if event is None:
        event_time_str = '--:--'

    # Update event label
    clock_face[CLOCK_EVENT] = Label(SMALL_FONT, color=event_color, text=event_time_str)
    clock_face[CLOCK_EVENT].x = max(glyph_x + 6, center_x - clock_face[CLOCK_EVENT].bounding_box[2] // 2)
    clock_face[CLOCK_EVENT].y = event_y

def log_exception_and_restart(e):
    """
    Logs an exception to a file, then restarts the board.
    """
    msg = "{0}: [VERSION {1}] (RAM {2:,}) - {3}\n".format(
        strftime(time.localtime()), VERSION, gc.mem_free(), e
    )
    try:
        log = open('exceptions.log', 'a')   # Can fail if filesystem is read-only or full
        log.write(msg)
        log.flush()
        log.close()
    except Exception as e:
        print(msg)
        print(str(e))
        reload() # Reboot / restart

# Try to read the latitude/longitude from the secrets. If not present, then use IP geolocation
def get_lat_long():
    global latitude, longitude
    try:
        latitude = secrets['latitude']
        longitude = secrets['longitude']
        print('Lat/lon determined from secrets: {0}, {1}'.format(latitude, longitude))
    except KeyError:
        latitude, longitude = wifi.fetch_data('http://www.geoplugin.net/json.gp', json_path = [['geoplugin_latitude'], ['geoplugin_longitude']])
        print('Lat/lon determined from IP geolocation: {0}, {1}'.format(latitude, longitude))

# Try to read the UTC offset from the secrets. If not present, it will be set below via API call
def get_utc_offset():
    global utc_offset
    try:
        utc_offset = secrets['utc_offset']
        print('UTC offset determined from secrets: ' + utc_offset)
    except: utc_offset = "-800"   # Default/fallback (-700 is PDT and -800 PST)
    return

def format_utc_offset(offset_str):
    """
    Convert an offset like '-700', '-07:00', '+530', '+05:30' into standard ±HH:MM
    """
    offset_str = offset_str.strip()
    if ':' in offset_str:
        if offset_str[0] in '+-':
            sign = offset_str[0]
            hours, minutes = offset_str[1:].split(':')
        else:
            sign = '+'
            hours, minutes = offset_str.split(':')
        return "{}{:02d}:{:02d}".format(sign, int(hours), int(minutes))
    else:
        val = int(offset_str)
        sign = '-' if val < 0 else '+'
        val = abs(val)
        hours = val // 100
        minutes = val % 100
        return '{}{:02d}:{:02d}'.format(sign, hours, minutes)

def fetch_url_with_retry(url, max_retries=3, delay=3):
    """
    Fetch a URL via ESP32, retrying up to max_retries times on failure.
    """
    attempt = 1
    while attempt <= max_retries:
        print('[Attempt {}/{}] Fetching: {}'.format(attempt, max_retries, url))
        try:
            data = wifi.fetch_data(url)
            print('Success!')
            return data
        except Exception as e:
            print('Request failed: {}'.format(e))
            if attempt < max_retries:
                print('Retrying in {}s...'.format(delay))
                time.sleep(delay)
            else:
                print('All retries failed.')
                return None
        attempt += 1

def tz_hours_from_offset(utc_offset):
    """
    Convert a UTC offset string to an integer tz for USNO API.
    Supports "-07:00", "-0700", "-7", "+05:30" etc.
    Only hours are returned; minutes are ignored.
    Valid USNO tz range: -12 <= tz <= 14
    """
    utc_offset = utc_offset.replace(':', '')
    if utc_offset.startswith('-'):
        sign = -1
        digits = utc_offset[1:]
    elif utc_offset.startswith('+'):
        sign = 1
        digits = utc_offset[1:]
    else:
        sign = 1
        digits = utc_offset

    if len(digits) >= 3:
        hours = int(digits[:-2]) * sign
    else:
        hours = int(digits) * sign

    if hours < -12 or hours > 14:
        raise ValueError("tz offset out-of-bounds for USNO API: {}".format(hours))

    return hours

########################################################################################################################

class SolarEphemera:
    global latitude, longitude, utc_offset, moon_phase

    def __init__(self, datetime):
        self.sunrise = None
        self.sunset = None
        self.moonrise = None
        self.moonset = None
        self.percent = None
        self.datetime = datetime
        self.phase = None

        date_str = "{:04d}-{:02d}-{:02d}".format(datetime.tm_year, datetime.tm_mon, datetime.tm_mday)
        url = "https://aa.usno.navy.mil/api/rstt/oneday?date={}&coords={},{}&tz={}".format(
            date_str, latitude, longitude, tz_hours_from_offset(utc_offset)
        )

        # Interesting fields: isdst, curphase
        print("Fetching daily sun & moon data via USNO AA for {}".format(date_str))
        data_str = fetch_url_with_retry(url, max_retries=3, delay=3)
        if data_str is None:
            print("Failed to fetch USNO data. Leaving ephemera empty.")
            return

        try:
            raw = json.loads(data_str)
            data = raw['properties']['data']
        except Exception as e:
            print("Failed to parse USNO response: {}".format(e))
            return

        # "Waxing Crescent", "Waxing Gibbous", "Waning Crescent", "Waning Gibbous", "New Moon", "Full Moon"
        self.phase = data.get('curphase', '')
        daylight_saving_time = data.get('isdst', False)

        try:
            self.percent = float(data.get('fracillum', "0%").strip('%'))
        except Exception as e:
            print("Failed to parse fracillum: {}".format(e))
            self.percent = 100 # Default to full moon

        try:
            for item in data.get('sundata', []):
                phen = item.get('phen', '')
                t = self.parse_usno_time(item.get('time'))
                if phen == 'Rise':
                    self.sunrise = t
                elif phen == 'Set':
                    self.sunset = t
        except Exception as e:
            print("Failed to parse sun events: {}".format(e))

        try:
            for item in data.get('moondata', []):
                phen = item.get('phen', '')
                t = self.parse_usno_time(item.get('time'))
                if phen == 'Rise':
                    self.moonrise = t
                elif phen == 'Set':
                    self.moonset = t
        except Exception as e:
            print("Failed to parse moon events: {}".format(e))

    @staticmethod
    def parse_usno_time(timestr):
        if not timestr:
            return None
        try:
            h, m = [int(x) for x in timestr.split(':')]
            now = time.localtime()
            t = time.struct_time((
                now.tm_year, now.tm_mon, now.tm_mday, h, m, 0, -1, -1, -1
            ))
            return time.mktime(t)
        except Exception as e:
            print("Failed to parse time '{}': {}".format(timestr, e))
            return None

########################################################################################################################

def update_display(time_only=False):
    global moon_frame, percent_illum, days, current_event, last_update_sec, moon_phase

    # moon_frame = 90 if waning crescent and percent = 10
    # moon_frame = 10 if waxing crescent and percent = 10
    # moon_frame == 50 if full moon and percent >= 100.0
    # moon_frame == 99 if new moon and percent <= 0.0
    percent_illum = int(days[TODAY].percent)
    moon_phase = days[TODAY].phase
    if moon_phase != None:
        if "Waning" in moon_phase:
            phase_glyph = '-'
            moon_frame = 100 - percent_illum // 2
        if "Waxing" in moon_phase:
            phase_glyph = '+'
            moon_frame = percent_illum // 2
        if "New Moon" in moon_phase:
            phase_glyph = ''
            moon_frame = 99
        if "Full Moon" in moon_phase:
            phase_glyph = ''
            moon_frame = 50

    if landscape_orientation:
        MOON_Y = 0
        CENTER_X = 48
        TIME_Y = 6
        DATE_Y = 16
        EVENT_Y = 27
        CLOCK_GLYPH_X = 30
    else:
        MOON_Y = 0
        CENTER_X = 16
        TIME_Y = 37
        DATE_Y = 47
        EVENT_Y = 57
        CLOCK_GLYPH_X = 0

    try:
        bitmap = displayio.OnDiskBitmap('moon/moon{:02d}.bmp'.format(moon_frame))
        tile_grid = displayio.TileGrid(bitmap, pixel_shader=displayio.ColorConverter())
        tile_grid.x = 0
        tile_grid.y = MOON_Y
        clock_face[0] = tile_grid
    except Exception as e:
        print("Error loading bitmap: {}".format(e))

    # Update minimal set of display elements and return quickly
    if time_only:
        global brightness, dwell

        # Draw time with alternating (flashing) colon separator
        clock_face[CLOCK_TIME].text = hh_mm(local_time)
        clock_face[CLOCK_TIME].x = CENTER_X - clock_face[CLOCK_TIME].bounding_box[2] // 2
        clock_face[CLOCK_TIME].y = TIME_Y

        # Draw brightening glyph for waxing, or dimming glyph for waning
        clock_face[CLOCK_PHASE].x = 0
        clock_face[CLOCK_PHASE].y = 2
        clock_face[CLOCK_PHASE].text = phase_glyph
        if phase_glyph == '+':
            brightness = brightness + 0.1
            if brightness >= 1.0:
                brightness = 1.0
                if dwell > 0: dwell = dwell - 1
                else:
                    brightness = 0.0
                    dwell = 10
        else:
            brightness = brightness - 0.1
            if brightness <= 0.0:
                brightness = 0.0
                if dwell > 0: dwell = dwell - 1
                else:
                    brightness = 1.0
                    dwell = 10
        clock_face[CLOCK_PHASE].color = color.adjust_brightness(0xBB9946, brightness)

        display.refresh()
        return

    if last_update_sec == local_time.tm_sec:
        return

    clock_face[CLOCK_PERCENT].text = '100%' if percent_illum >= 99 else '{:.1f}%'.format(percent_illum)
    clock_face[CLOCK_PERCENT].x = 16 - clock_face[CLOCK_PERCENT].bounding_box[2] // 2
    clock_face[CLOCK_PERCENT].y = MOON_Y + 16
    for i in range(1, 5): clock_face[i].text = clock_face[CLOCK_PERCENT].text

    clock_face[1].x, clock_face[1].y = clock_face[CLOCK_PERCENT].x, clock_face[CLOCK_PERCENT].y - 1
    clock_face[2].x, clock_face[2].y = clock_face[CLOCK_PERCENT].x - 1, clock_face[CLOCK_PERCENT].y
    clock_face[3].x, clock_face[3].y = clock_face[CLOCK_PERCENT].x + 1, clock_face[CLOCK_PERCENT].y
    clock_face[4].x, clock_face[4].y = clock_face[CLOCK_PERCENT].x, clock_face[CLOCK_PERCENT].y + 1

    event_map = [
        ('Moonset tomorrow', days[TOMORROW].moonset, TOMORROW_SET),
        ('Moonrise tomorrow', days[TOMORROW].moonrise, TOMORROW_RISE),
        ('Sunset tomorrow', days[TOMORROW].sunset, TOMORROW_SET),
        ('Sunrise tomorrow', days[TOMORROW].sunrise, TOMORROW_RISE),
        ('Moonset today', days[TODAY].moonset, TODAY_SET),
        ('Moonrise today', days[TODAY].moonrise, TODAY_RISE),
        ('Sunset today', days[TODAY].sunset, TODAY_SET),
        ('Sunrise today', days[TODAY].sunrise, TODAY_RISE)
    ]

    event_name, event_time, icon = event_map[(NUM_EVENTS - current_event) % NUM_EVENTS]
    display_event(event_name, event_time, icon, EVENT_Y, CLOCK_GLYPH_X, CENTER_X, phase_glyph)

    clock_face[CLOCK_TIME].text = hh_mm(local_time)
    clock_face[CLOCK_TIME].x = CENTER_X - clock_face[CLOCK_TIME].bounding_box[2] // 2
    clock_face[CLOCK_TIME].y = TIME_Y

    clock_face[CLOCK_DATE].text = '{0}-{1:02d}'.format(local_time.tm_mon, local_time.tm_mday)
    clock_face[CLOCK_DATE].x = CENTER_X - clock_face[CLOCK_DATE].bounding_box[2] // 2
    clock_face[CLOCK_DATE].y = DATE_Y

    display.refresh()
    last_update_sec = local_time.tm_sec

    current_event = current_event - 1 if current_event > 1 else NUM_EVENTS

########################################################################################################################

# Setup force sleep and wake buttons
pin_down = DigitalInOut(board.BUTTON_DOWN)
pin_down.switch_to_input(pull=Pull.UP)
pin_up = DigitalInOut(board.BUTTON_UP)
pin_up.switch_to_input(pull=Pull.UP)

nvm[0:1] = bytes([0])

display = Matrix(bit_depth=BIT_DEPTH).display
accelerometer = LIS3DH_I2C(busio.I2C(board.SCL, board.SDA), address=0x19)
accelerometer.acceleration
time.sleep(0.1)
display.rotation = (int(((math.atan2(-accelerometer.acceleration.y, -accelerometer.acceleration.x) + math.pi) / (math.pi * 2) + 0.875) * 4) % 4) * 90
landscape_orientation = display.rotation in (0, 180)
clock_face = displayio.Group()
snoozing = displayio.Group()

# Append elements to clock_face
try:
    splash_screen_image = 'splash-landscape.bmp' if landscape_orientation else 'splash-portrait.bmp'
    clock_face.append(displayio.TileGrid(displayio.OnDiskBitmap(splash_screen_image), pixel_shader=displayio.ColorConverter()))
    snoozing.append(displayio.TileGrid(displayio.OnDiskBitmap('sleeping.bmp'), pixel_shader=displayio.ColorConverter()))
except Exception as e:
    print("Error loading image(s): {}".format(e))
    clock_face.append(Label(SMALL_FONT, color=0xFF0000, text='ERROR!'))
    clock_face[0].x = (display.width - clock_face[0].bounding_box[2] + 1) // 2
    clock_face[0].y = display.height // 2 - 1

display.root_group = clock_face
display.refresh()

for i in range(4): clock_face.append(Label(SMALL_FONT, color=0, text='99.9%', y=-99))
clock_face.append(Label(SMALL_FONT, color=PERCENT_COLOR, text='99.9%', y=-99))
clock_face.append(Label(LARGE_FONT, color=TIME_COLOR, text='24:59', y=-99))
clock_face.append(Label(SMALL_FONT, color=DATE_COLOR, text='12/31', y=-99))
clock_face.append(Label(SYMBOL_FONT, color=0x00FF00, text='x', y=-99))
clock_face.append(Label(SMALL_FONT, color=0x00FF00, text='24:59', y=-99))
clock_face.append(Label(SMALL_FONT, color=DATE_COLOR, text='12', y=-99))
clock_face.append(Label(SMALL_FONT, color=MOON_PHASE_COLOR, text='+', y=-99))

esp32_cs = DigitalInOut(board.ESP_CS)
esp32_ready = DigitalInOut(board.ESP_BUSY)
esp32_reset = DigitalInOut(board.ESP_RESET)
spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
esp = adafruit_esp32spi.ESP_SPIcontrol(spi, esp32_cs, esp32_ready, esp32_reset)
wifi = Network(status_neopixel=board.NEOPIXEL, esp=esp, external_spi=spi, debug=False)
wifi.connect()

get_utc_offset()
get_lat_long()

datetime = update_time()

days = [
    SolarEphemera(datetime),
    SolarEphemera(time.localtime(time.mktime(datetime) + 86400))
]

watchdog.timeout = WATCHDOG_TIMEOUT
watchdog.mode = WatchDogMode.RESET
should_update_dst = False

########################################################################################################################

while True:
    display.rotation = (int(((math.atan2(-accelerometer.acceleration.y, -accelerometer.acceleration.x) + math.pi) / (math.pi * 2) + 0.875) * 4) % 4) * 90
    landscape_orientation = display.rotation in (0, 180)
    watchdog.feed()
    local_time = time.localtime()

    if secrets['sleep_time'] != None and secrets['wake_time'] != None: sleep_or_wake()

    if local_time.tm_mday == days[TOMORROW].datetime.tm_mday:
        should_update_dst = True
        datetime = update_time()
        days = [
            SolarEphemera(datetime),
            SolarEphemera(time.localtime(time.mktime(datetime) + 86400))
        ]
        datetime = update_time()

    if local_time.tm_hour == 2 and should_update_dst:
        get_utc_offset()
        should_update_dst = False

    next_refresh_time = time.time() + REFRESH_DELAY
    while(time.time() < next_refresh_time):
        watchdog.feed()
        check_buttons()
        local_time = time.localtime()
        update_display(True)
        time.sleep(0.1)

    # if asleep:
    #     print('.', end = '')
    #     check_buttons()
    #     continue

    datetime = update_time()
    current_time = time.time()

    check_buttons()
    update_display()
    check_buttons()
    gc.collect()

    print('Moon Clock: Version {} ({:,} RAM free) @ {} moon_frame: {}, percent_illum: {:.2f}, moon_phase: {}'.format(
        VERSION, gc.mem_free(), strftime(local_time), moon_frame, percent_illum, moon_phase
    ))
