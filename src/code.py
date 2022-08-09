import gc

VERSION = '1.6.1.5'
print('VERSION {0} ({1:,} RAM)'.format(VERSION, gc.mem_free()))

import json
import math
import time

import adafruit_lis3dh
import board
import busio
import displayio
import supervisor
from adafruit_bitmap_font import bitmap_font
from adafruit_display_text.label import Label
from adafruit_matrixportal.matrix import Matrix
from adafruit_matrixportal.network import Network
from digitalio import DigitalInOut, Pull
from rtc import RTC

import color
print('Imports loaded')

from secrets import secrets
print('Secrets loaded')

HOURS_BETWEEN_SYNC = 8  # Number of hours between syncs with time server
SECONDS_PER_HOUR = 3600 # Number of seconds in one hour = 60 * 60
SECONDS_PER_DAY = 86400 # Number of seconds in one hour = 60 * 60
COUNTDOWN = False       # If set, show time to vs time of rise/set events
BIT_DEPTH = 6           # Ideally 6, but can set lower if RAM is tight
REFRESH_DELAY = 10      # Seconds to wait between screen updates. Should be 5 >= n <= 60
GLOBAL_BRIGHTNESS = 0.5 # Text brightness value ranging between 0.0 - 1.0

MOON_EVENT_COLOR = color.adjust_brightness(0xB8BFC9, GLOBAL_BRIGHTNESS) # (grey blue)
MOON_PERCENT_COLOR = color.adjust_brightness(0x9B24F9, GLOBAL_BRIGHTNESS) # (purple)
SUN_EVENT_COLOR = color.adjust_brightness(0xFBDE2C, GLOBAL_BRIGHTNESS) # (sun yellow)
TIME_COLOR = color.adjust_brightness(0xA00000, GLOBAL_BRIGHTNESS) # (red)
DATE_COLOR = color.adjust_brightness(0x46BBDF, GLOBAL_BRIGHTNESS) # (aqua)

# The meteorological data for TODAY and TOMORROW is kept in the PERIOD array.
PERIOD = [None, None]
TODAY = 0
TOMORROW = 1

TODAY_RISE = '\u2191'   # ↑
TODAY_SET = '\u2193'    # ↓
TOMORROW_RISE = '\u219F'# ↟
TOMORROW_SET = '\u21A1' # ↡

pin_down = DigitalInOut(board.BUTTON_DOWN)
pin_down.switch_to_input(pull=Pull.UP) # Pull.DOWN doesn't fucking work!
pin_up = DigitalInOut(board.BUTTON_UP)
pin_up.switch_to_input(pull=Pull.UP)

ASLEEP = False

def sleep():
    global ASLEEP # Are you fucking kidding me? Python is teh sux0rz! 😂
    DISPLAY.show(SLEEPING)
    DISPLAY.refresh()
    ASLEEP = True

def wake():
    global ASLEEP
    DISPLAY.show(CLOCK_FACE)
    DISPLAY.refresh()
    ASLEEP = False

def check_buttons():
    if not pin_down.value: # negating to indicate button pressed because Pull.UP 😵
        sleep()
    if not pin_up.value:
        wake()

def parse_time(timestring, dst=-1):
    date_time = timestring.split('T')
    year_month_day = date_time[0].split('-')
    hour_minute_second = date_time[1].split('+')[0].split('-')[0].split(':')

    return time.struct_time(( # Note: Extra parenthesis are needed because struct_time() now takes a tuple
        int(year_month_day[0]),
        int(year_month_day[1]),
        int(year_month_day[2]),
        int(hour_minute_second[0]),
        int(hour_minute_second[1]),
        int(hour_minute_second[2].split('.')[0]),
        -1, # day of week
        -1, # day of year
        dst # 1 = Yes, 0 = No, -1 = Unknown
    ))

def update_time(timezone=None):
    try:
        if timezone: # Use provided timezone if present
            time_url = 'http://worldtimeapi.org/api/timezone/' + timezone
            print('Determining time using provided timezone. URL: ', time_url)
        else: # Use IP geolocation
            time_url = 'http://worldtimeapi.org/api/ip'
            print('Determining time by IP geolocation. URL: ', time_url)

        datetime, dst, utc_offset = NETWORK.fetch_data(time_url, json_path=[['datetime'], ['dst'], ['utc_offset']])
        time_struct = parse_time(datetime, dst)
        RTC().datetime = time_struct
        return time_struct, utc_offset
    except Exception as e:
        print('Failed to set time. Error: {0}'.format(e))

def hh_mm(time_struct):
    hour = 12 if time_struct.tm_hour % 12 == 0 else time_struct.tm_hour % 12
    return '{0}:{1:0>2}'.format(hour, time_struct.tm_min)

def strftime(time_struct):
    return '{0:0>2}/{1:0>2}/{2:0>2} {3:0>2}:{4:0>2}:{5:0>2} {6}'.format(
        time_struct.tm_year,
        time_struct.tm_mon,
        time_struct.tm_mday,
        time_struct.tm_hour,
        time_struct.tm_min,
        time_struct.tm_sec,
        UTC_OFFSET)

def display_event(name, event, icon):
    time_struct = time.localtime(event)

    if name.startswith('Sun'):
        EVENT_COLOR = CLOCK_FACE[CLOCK_EVENT].color = SUN_EVENT_COLOR
        hour = 12 if time_struct.tm_hour == 0 else time_struct.tm_hour
        event_time = '{0}:{1:0>2}'.format(hour, time_struct.tm_min)
    else:
        EVENT_COLOR = CLOCK_FACE[CLOCK_EVENT].color = MOON_EVENT_COLOR
        event_time = '{0}:{1:0>2}'.format(time_struct.tm_hour, time_struct.tm_min)

    CLOCK_FACE[CLOCK_EVENT] = Label(SMALL_FONT, color=EVENT_COLOR, text=event_time, y=EVENT_Y)
    CLOCK_FACE[CLOCK_EVENT].x = max(CLOCK_GLYPH_X + 6, CENTER_X - CLOCK_FACE[CLOCK_EVENT].bounding_box[2] // 2)
    CLOCK_FACE[CLOCK_EVENT].y = EVENT_Y

    CLOCK_FACE[CLOCK_GLYPH].color = EVENT_COLOR
    CLOCK_FACE[CLOCK_GLYPH].text = icon
    CLOCK_FACE[CLOCK_GLYPH].y = EVENT_Y - 2
    CLOCK_FACE[CLOCK_GLYPH].x = CLOCK_GLYPH_X

def log_exception_and_restart(e):
    msg = "{0}: [VERSION {1}] (RAM {2:,}) - {3}\n".format(strftime(time.localtime()), VERSION, gc.mem_free(), e)
    try:
        log = open('exceptions.log', 'a')   # Can fail if filesystem is read-only or full
        log.write(msg)
        log.flush()
        log.close()
    except Exception as e:
        print(msg)
        print(str(e))
    supervisor.reload() # Reboot / restart

class EarthData():
    def __init__(self, datetime):
        url = 'https://api.met.no/weatherapi/sunrise/2.0/.json?lat={0}&lon={1}&date={2:0>2}-{3:0>2}-{4:0>2}&offset={5}'.format(
            LATITUDE,
            LONGITUDE,
            datetime.tm_year,
            datetime.tm_mon,
            datetime.tm_mday,
            UTC_OFFSET)

        for _ in range(5): # Number of retries
            try:
                print('Fetching diurnal event data via: ', url)
                full_data = json.loads(NETWORK.fetch_data(url))
                location_data = full_data['location']['time'][0]

                self.age = float(location_data['moonphase']['value']) / 100
                self.midnight = time.mktime(parse_time(location_data['moonphase']['time']))

                if 'sunrise' in location_data:
                    self.sunrise = time.mktime(parse_time(location_data['sunrise']['time']))
                else:
                    self.sunrise = None
                if 'sunset' in location_data:
                    self.sunset = time.mktime(parse_time(location_data['sunset']['time']))
                else:
                    self.sunset = None
                if 'moonrise' in location_data:
                    self.moonrise = time.mktime(parse_time(location_data['moonrise']['time']))
                else:
                    self.moonrise = None
                if 'moonset' in location_data:
                    self.moonset = time.mktime(parse_time(location_data['moonset']['time']))
                else:
                    self.moonset = None
                return
            except Exception as e:
                print('Fetching moon data for date via URL: {0} failed. Error: {1}'.format(url, e))
                time.sleep(15)

MATRIX = Matrix(bit_depth=BIT_DEPTH)
DISPLAY = MATRIX.display
ACCEL = adafruit_lis3dh.LIS3DH_I2C(busio.I2C(board.SCL, board.SDA), address=0x19)
ACCEL.acceleration # Dummy read to blow out any startup residue
time.sleep(0.1)
DISPLAY.rotation = (int(((math.atan2(-ACCEL.acceleration.y, -ACCEL.acceleration.x) + math.pi) /
    (math.pi * 2) + 0.875) * 4) % 4) * 90
if DISPLAY.rotation in (0, 180):
    LANDSCAPE_MODE = True
    SPLASH = 'splash-landscape.bmp'
else:
    SPLASH = 'splash-portrait.bmp'
    LANDSCAPE_MODE = False

LARGE_FONT = bitmap_font.load_font('/fonts/helvB12.bdf')
SMALL_FONT = bitmap_font.load_font('/fonts/helvR10.bdf')
SYMBOL_FONT = bitmap_font.load_font('/fonts/6x10.bdf')
LARGE_FONT.load_glyphs('0123456789:')
SMALL_FONT.load_glyphs('0123456789:/.%')
SYMBOL_FONT.load_glyphs('\u2191\u2193\u219F\u21A1')

CLOCK_FACE = displayio.Group()
SLEEPING = displayio.Group()

# Element 0 is the splash screen image (1 of 4), later replaced with the moon phase bitmap.
CLOCK_IMAGE = 0
try:
    CLOCK_FACE.append(
        displayio.TileGrid(displayio.OnDiskBitmap(open(SPLASH, 'rb')), pixel_shader=displayio.ColorConverter())
    )

    SLEEPING.append(
        displayio.TileGrid(displayio.OnDiskBitmap(open('sleeping.bmp', 'rb')), pixel_shader=displayio.ColorConverter())
    )
except Exception as e:
    print('Error loading image(s): {0}'.format(e))
    CLOCK_FACE.append(Label(SMALL_FONT, color=0xFF0000, text='OOPS'))
    CLOCK_FACE[CLOCK_IMAGE].x = (DISPLAY.width - CLOCK_FACE[CLOCK_IMAGE].bounding_box[2] + 1) // 2 # Integer division
    CLOCK_FACE[CLOCK_IMAGE].y = DISPLAY.height // 2 - 1 # Integer division

# Elements 1-4 are a black outline around the moon percentage with text labels offset by 1 pixel. Initial text
# value must be long enough for longest anticipated string later since the bounding box is calculated here.
for i in range(4):
    CLOCK_FACE.append(Label(SMALL_FONT, color=0, text='99.9%', y=-99))

PHASE_PERCENT = 5
CLOCK_FACE.append(Label(SMALL_FONT, color=MOON_PERCENT_COLOR, text='99.9%', y=-99))
CLOCK_TIME = 6
CLOCK_FACE.append(Label(LARGE_FONT, color=TIME_COLOR, text='24:59', y=-99))
CLOCK_DATE = 7
CLOCK_FACE.append(Label(SMALL_FONT, color=DATE_COLOR, text='12/31', y=-99))
# Element 8 is a symbol indicating next rise or set - Color is overridden by event colors
CLOCK_GLYPH = 8
CLOCK_FACE.append(Label(SYMBOL_FONT, color=0x00FF00, text='x', y=-99))
# Element 9 is the time of (or time to) next rise/set event - Color is overridden by event colors
CLOCK_EVENT = 9
CLOCK_FACE.append(Label(SMALL_FONT, color=0x00FF00, text='24:59', y=-99))

CLOCK_MONTH = 10
CLOCK_FACE.append(Label(SMALL_FONT, color=DATE_COLOR, text='12', y=-99))
CLOCK_SLASH = 11
CLOCK_FACE.append(Label(SMALL_FONT, color=DATE_COLOR, text='/', y=-99))
CLOCK_DAY = 12
CLOCK_FACE.append(Label(SMALL_FONT, color=DATE_COLOR, text='2', y=-99))

DISPLAY.show(CLOCK_FACE)
DISPLAY.refresh()

NETWORK = Network(status_neopixel=board.NEOPIXEL, debug=False)
NETWORK.connect() # Logs "Connecting to AP ...""

# Try to read the latitude/longitude from the secrets. If not present, use IP geolocation
try:
    LATITUDE = secrets['latitude']
    LONGITUDE = secrets['longitude']
    print('Lat/lon determined from secrets: ', LATITUDE, LONGITUDE)
except KeyError:
    LATITUDE, LONGITUDE = NETWORK.fetch_data(
        'http://www.geoplugin.net/json.gp', json_path=[['geoplugin_latitude'], ['geoplugin_longitude']]
    )
    print('Lat/lon determined by IP geolocation: ', LATITUDE, LONGITUDE)

# Try to read the timezone from the secrets. If not present, it will be set below using IP geolocation
try:
    TIMEZONE = secrets['timezone'] # e.g. 'America/Los_Angeles'
    print('Timezone determined from secrets: ', LATITUDE, LONGITUDE)
except:
    TIMEZONE = None

# Try to read the UTC offset from the secrets. If not present, it will be set below
try:
    UTC_OFFSET = secrets['offset']
    print('UTC offset determined from secrets: ', UTC_OFFSET)
except:
    UTC_OFFSET = None

try:
    if UTC_OFFSET == None:
        DATETIME, UTC_OFFSET = update_time(TIMEZONE)
    else:
        DATETIME, _ignored = update_time(TIMEZONE)
    print('Setting initial clock time. UTC offset: {0}'.format(UTC_OFFSET))
except Exception as e:
    log_exception_and_restart('Error setting initial clock time: {0}'.format(e))
    # supervisor.reload() # Reboot / restart

LAST_SYNC = time.mktime(DATETIME)
PERIOD[TODAY] = EarthData(DATETIME)
PERIOD[TOMORROW] = EarthData(time.localtime(time.mktime(DATETIME) + SECONDS_PER_DAY))
CURRENT_DIURNAL_EVENT = 8

while True:
    try:
        gc.collect()
        LOCAL_TIME = time.localtime()

        if secrets['sleep_hour'] != None and secrets['wake_hour'] != None:
            if LOCAL_TIME.tm_hour >= secrets['sleep_hour'] and LOCAL_TIME.tm_hour < secrets['wake_hour'] and not ASLEEP:
                print("Current hour is {0} and sleep_hour is {1}. Going to sleep...".format(LOCAL_TIME.tm_hour, secrets['sleep_hour']))
                sleep()
            if LOCAL_TIME.tm_hour >= secrets['wake_hour'] and ASLEEP:
                print("\nCurrent hour is {0} and wake_hour is {1}. Waking up...".format(LOCAL_TIME.tm_hour, secrets['wake_hour']))
                wake()

        refresh_time = time.time() + REFRESH_DELAY
        while(time.time() < refresh_time):
            check_buttons()

        if ASLEEP:
            print(".", end="")
            continue

        # Periodically sync with time server since on-board clock is inaccurate
        NOW = time.time()
        if NOW - LAST_SYNC > HOURS_BETWEEN_SYNC * SECONDS_PER_HOUR:
            print('Syncing with time server')

            try:
                DATETIME, _ignored = update_time(TIMEZONE)
                LAST_SYNC = time.mktime(DATETIME)
                continue # Time may have changed; refresh NOW value

            except Exception as e:
                log_exception_and_restart('Error syncing with time server: {0}'.format(e))
                # supervisor.reload() # Reboot / restart

        # Reboot at midnight to update time and free up memory
        # if NOW >= PERIOD[TOMORROW].midnight:
        #     supervisor.reload() # Reboot / restart

        # Determine weighting of tomorrow's phase vs today's, using current time
        RATIO = ((NOW - PERIOD[TODAY].midnight) / (PERIOD[TOMORROW].midnight - PERIOD[TODAY].midnight))

        if PERIOD[TODAY].age < PERIOD[TOMORROW].age:
            AGE = (PERIOD[TODAY].age + (PERIOD[TOMORROW].age - PERIOD[TODAY].age) * RATIO) % 1.0
        else:
            # Handle age wraparound (1.0 -> 0.0). If tomorrow's age is less than today's, it indicates a new moon
            # crossover. Add 1 to tomorrow's age when computing age delta.
            AGE = (PERIOD[TODAY].age + (PERIOD[TOMORROW].age + 1 - PERIOD[TODAY].age) * RATIO) % 1.0

        # AGE can be used for direct lookup to moon bitmap (0 to 99). The images are pre-rendered for a linear
        # timescale. Note that the solar terminator moves nonlinearly across sphere.
        FRAME = int(AGE * 100) % 100 # Bitmap 0 to 99

        # Then use some trig to get percentage lit
        if AGE <= 0.5: # New -> first quarter -> full
            PERCENT = (1 - math.cos(AGE * 2 * math.pi)) * 50
        else:          # Full -> last quarter -> new
            PERCENT = (1 + math.cos((AGE - 0.5) * 2 * math.pi)) * 50

        NEXT_MOON_EVENT = PERIOD[1].midnight + 100000 # Force first match
        for DAY in reversed(PERIOD):
            if DAY.moonrise and NEXT_MOON_EVENT >= DAY.moonrise >= NOW:
                NEXT_MOON_EVENT = DAY.moonrise
                MOON_RISEN = False
            if DAY.moonset and NEXT_MOON_EVENT >= DAY.moonset >= NOW:
                NEXT_MOON_EVENT = DAY.moonset
                MOON_RISEN = True

        if LANDSCAPE_MODE:     # Horizontal 'landscape' orientation
            CENTER_X = 48      # Text along right
            MOON_Y = 0         # Moon at left
            TIME_Y = 6         # Time at top right
            EVENT_Y = 27       # Rise/set at bottom right
            EVENTS_24 = True   # In landscape mode, there's enough room for 24 event hour times
            CLOCK_GLYPH_X = 30
        else:                  # Vertical 'portrait' orientation
            EVENTS_24 = True   # In portrait mode, there's only room for 12 event hour times
            CENTER_X = 16      # Text down center
            CLOCK_GLYPH_X = 0
            if MOON_RISEN:
                MOON_Y = 0     # Moon at top
                EVENT_Y = 38   # Rise/set in middle
                TIME_Y = 49    # Time/date at bottom
            else:
                TIME_Y = 6     # Time/date at top
                EVENT_Y = 26   # Rise/set in middle
                MOON_Y = 32    # Moon at bottom

        try:
            FILENAME = 'moon/moon{0:0>2}.bmp'.format(FRAME)
            BITMAP = displayio.OnDiskBitmap(open(FILENAME, 'rb'))
            tile_grid = displayio.TileGrid(BITMAP, pixel_shader=displayio.ColorConverter())
            tile_grid.x = 0
            tile_grid.y = MOON_Y
            CLOCK_FACE[CLOCK_IMAGE] = tile_grid
        except Exception as e:
            print('Error loading bitmap: {0}'.format(e))

        if PERCENT >= 99.95:
            STRING = '100%'
        else:
            STRING = '{:.1f}%'.format(PERCENT + 0.05)

        # Set PHASE_PERCENT first, use its size and position for painting the outlines below
        CLOCK_FACE[PHASE_PERCENT].text = STRING
        CLOCK_FACE[PHASE_PERCENT].x = 16 - CLOCK_FACE[PHASE_PERCENT].bounding_box[2] // 2 # Integer division
        CLOCK_FACE[PHASE_PERCENT].y = MOON_Y + 16

        for i in range(1, 5):
            CLOCK_FACE[i].text = CLOCK_FACE[PHASE_PERCENT].text

        # Paint the black outline text labels for the current moon percentage
        CLOCK_FACE[1].x, CLOCK_FACE[1].y = CLOCK_FACE[PHASE_PERCENT].x, CLOCK_FACE[PHASE_PERCENT].y - 1
        CLOCK_FACE[2].x, CLOCK_FACE[2].y = CLOCK_FACE[PHASE_PERCENT].x - 1, CLOCK_FACE[PHASE_PERCENT].y
        CLOCK_FACE[3].x, CLOCK_FACE[3].y = CLOCK_FACE[PHASE_PERCENT].x + 1, CLOCK_FACE[PHASE_PERCENT].y
        CLOCK_FACE[4].x, CLOCK_FACE[4].y = CLOCK_FACE[PHASE_PERCENT].x, CLOCK_FACE[PHASE_PERCENT].y + 1

        if CURRENT_DIURNAL_EVENT == 8:
            display_event('Sunrise today', PERIOD[TODAY].sunrise, TODAY_RISE)
            CURRENT_DIURNAL_EVENT -= 1
        elif CURRENT_DIURNAL_EVENT == 7:
            display_event('Sunset today', PERIOD[TODAY].sunset, TODAY_SET)
            CURRENT_DIURNAL_EVENT -= 1
        elif CURRENT_DIURNAL_EVENT == 6:
            display_event('Moonrise today', PERIOD[TODAY].moonrise, TODAY_RISE)
            CURRENT_DIURNAL_EVENT -= 1
        elif CURRENT_DIURNAL_EVENT == 5:
            display_event('Moonset today', PERIOD[TODAY].moonset, TODAY_SET)
            CURRENT_DIURNAL_EVENT -= 1
        elif CURRENT_DIURNAL_EVENT == 4:
            display_event('Sunrise tomorrow', PERIOD[TOMORROW].sunrise, TOMORROW_RISE)
            CURRENT_DIURNAL_EVENT -= 1
        elif CURRENT_DIURNAL_EVENT == 3:
            display_event('Sunset tomorrow', PERIOD[TOMORROW].sunset, TOMORROW_SET)
            CURRENT_DIURNAL_EVENT -= 1
        elif CURRENT_DIURNAL_EVENT == 2:
            display_event('Moonrise tomorrow', PERIOD[TOMORROW].moonrise, TOMORROW_RISE)
            CURRENT_DIURNAL_EVENT -= 1
        elif CURRENT_DIURNAL_EVENT == 1:
            display_event('Moonset tomorrow', PERIOD[TOMORROW].moonset, TOMORROW_SET)
            CURRENT_DIURNAL_EVENT = 8

        STRING = hh_mm(LOCAL_TIME)
        CLOCK_FACE[CLOCK_TIME].text = STRING
        CLOCK_FACE[CLOCK_TIME].x = CENTER_X - CLOCK_FACE[CLOCK_TIME].bounding_box[2] // 2
        CLOCK_FACE[CLOCK_TIME].y = TIME_Y

        CLOCK_FACE[CLOCK_MONTH] = Label(SMALL_FONT, color=DATE_COLOR, text=str(LOCAL_TIME.tm_mon), y=TIME_Y + 10)
        CLOCK_FACE[CLOCK_MONTH].x = CENTER_X - 1 - CLOCK_FACE[CLOCK_MONTH].bounding_box[2]
        CLOCK_FACE[CLOCK_SLASH].text = '/'
        CLOCK_FACE[CLOCK_SLASH].x = CENTER_X
        CLOCK_FACE[CLOCK_SLASH].y = TIME_Y + 10
        CLOCK_FACE[CLOCK_DAY].text = str(LOCAL_TIME.tm_mday)
        CLOCK_FACE[CLOCK_DAY].x = CENTER_X + 4
        CLOCK_FACE[CLOCK_DAY].y = TIME_Y + 10
        DISPLAY.refresh()
        print('Local time is {0} - VERSION {1} ({2:,} RAM)'.format(strftime(LOCAL_TIME), VERSION, gc.mem_free()))
    except Exception as e:
        log_exception_and_restart('Unexpected exception: {0}'.format(e))
