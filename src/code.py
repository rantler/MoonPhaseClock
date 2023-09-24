import gc

VERSION = '1.6.7.0'
print('Moon Clock: Version {0} ({1:,} RAM free)'.format(VERSION, gc.mem_free()))

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
REFRESH_DELAY = 5
BIT_DEPTH = 6
TODAY = 0
TOMORROW = 1
NUM_EVENTS = 8

TODAY_RISE = '\u2191'   # ↑
TODAY_SET = '\u2193'    # ↓
TOMORROW_RISE = '\u219F'# ↟
TOMORROW_SET = '\u21A1' # ↡

COLOR_BRIGHTNESS = 0.5
MOON_EVENT_COLOR = color.adjust_brightness(0xB8BFC9, COLOR_BRIGHTNESS) # (grey blue)
MOON_PHASE_COLOR = color.adjust_brightness(0x9B24F9, COLOR_BRIGHTNESS) # (purple)
SUN_EVENT_COLOR = color.adjust_brightness(0xFBDE2C, COLOR_BRIGHTNESS) # (sun yellow)
TIME_COLOR = color.adjust_brightness(0xA00000, COLOR_BRIGHTNESS) # (red)
DATE_COLOR = color.adjust_brightness(0x46BBDF, COLOR_BRIGHTNESS) # (aqua)

LARGE_FONT = bitmap_font.load_font('/fonts/helvB12.bdf')
SMALL_FONT = bitmap_font.load_font('/fonts/helvR10.bdf')
SYMBOL_FONT = bitmap_font.load_font('/fonts/6x10.bdf')
LARGE_FONT.load_glyphs('0123456789:')
SMALL_FONT.load_glyphs('0123456789:/.%')
SYMBOL_FONT.load_glyphs('\u2191\u2193\u219F\u21A1') # ↑ ↓ ↟ ↡

# NOTE! These values correspond to the _order_ of the clock_face.append() calls below. See comments there
CLOCK_MOON_PHASE = 5
CLOCK_TIME = 6
CLOCK_DATE = 7
# Element 8 is a symbol indicating next rise or set - Color is overridden by event colors
CLOCK_GLYPH = 8
# Element 9 is the time of (or time to) next rise/set event - Color is overridden by event colors
CLOCK_EVENT = 9
CLOCK_DATE = 10

current_event = NUM_EVENTS
asleep = False
latitude = None
longitude = None
utc_offset = None

########################################################################################################################

# From "Astronomical Algorithms" by Jean Meeus, section 48
def moon_phase_angle_to_illumination_percentage(phase_angle):
    return ((1 - math.cos(math.radians(phase_angle))) / 2 ) * 100

def get_utc_offset_from_api():
    try:
        watchdog.feed()
        utc_url = 'http://worldtimeapi.org/api/ip'
        print('Determining UTC offset by IP geolocation via: {0}'.format(utc_url))
        dst, _utc_offset = wifi.fetch_data(utc_url, json_path = [['dst'], ['utc_offset']])
        print('DST = {0}, UTC offset = {1}'.format(dst, _utc_offset))
        watchdog.feed()
    except Exception as e:
        print('Failed to fetch from worldtimeapi.org. Error: {0}'.format(e))
    return _utc_offset

def get_timestamp_from_esp32_wifi():
    # Often the get_time function just fails for a while, so you have call it again and again 🤷‍♂️
    retries = 50
    esp_time = 0
    while retries > 0 and esp_time == 0:
        time.sleep(1)
        try:
            esp_time = esp.get_time()
            if esp_time == 0:
                print('.', end = '')
                retries -= 1
        except Exception as e:
            print('!', end = '')
            retries -= 1
    if esp_time != 0:
        return time.localtime(esp_time[0] + int(utc_offset.split(':')[0]) * 3600 + int(utc_offset.split(':')[1]) * 60)
    else:
        print(' FAILED!')
        return None

def forced_asleep(): return nvm[0] == 1

# When forced asleep, the clock will remain sleeping until forced awake
def sleep(forced = False):
    global asleep
    if not asleep:
        display.show(snoozing)
        display.refresh()
        asleep = True
    if forced: nvm[0:1] = bytes([1])

# When forced awake, will resume sleeping at the scheduled time, if configured to do so
def wake(forced = False):
    global asleep, datetime
    if asleep:
        display.show(clock_face)
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
    time_struct = get_timestamp_from_esp32_wifi()
    if time_struct != None:
        RTC().datetime = time_struct
        return time_struct
    else:
        return RTC().datetime

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
        utc_offset)

def display_event(name, event, icon):
    if event == None:
        return

    time_struct = time.localtime(event)

    if name.startswith('Sun'):
        EVENT_COLOR = clock_face[CLOCK_EVENT].color = SUN_EVENT_COLOR
        hour = 12 if time_struct.tm_hour == 0 else time_struct.tm_hour
        event_time = '{0}:{1:0>2}'.format(hour, time_struct.tm_min)
    else:
        EVENT_COLOR = clock_face[CLOCK_EVENT].color = MOON_EVENT_COLOR
        event_time = '{0}:{1:0>2}'.format(time_struct.tm_hour, time_struct.tm_min)

    clock_face[CLOCK_EVENT] = Label(SMALL_FONT, color = EVENT_COLOR, text = event_time, y = EVENT_Y)
    clock_face[CLOCK_EVENT].x = max(CLOCK_GLYPH_X + 6, CENTER_X - clock_face[CLOCK_EVENT].bounding_box[2] // 2)
    clock_face[CLOCK_EVENT].y = EVENT_Y

    clock_face[CLOCK_GLYPH].color = EVENT_COLOR
    clock_face[CLOCK_GLYPH].text = icon
    clock_face[CLOCK_GLYPH].y = EVENT_Y - 2
    clock_face[CLOCK_GLYPH].x = CLOCK_GLYPH_X

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
    except: utc_offset = get_utc_offset_from_api()

########################################################################################################################

class SolarEphemera():
    global latitude, longitude, utc_offset
    def __init__(self, datetime):
        sun_url = 'https://api.met.no/weatherapi/sunrise/3.0/sun?lat={0}&lon={1}&date={2:0>2}-{3:0>2}-{4:0>2}&offset={5}'.format(
            latitude,
            longitude,
            datetime.tm_year,
            datetime.tm_mon,
            datetime.tm_mday,
            utc_offset)
        moon_url = 'https://api.met.no/weatherapi/sunrise/3.0/moon?lat={0}&lon={1}&date={2:0>2}-{3:0>2}-{4:0>2}&offset={5}'.format(
            latitude,
            longitude,
            datetime.tm_year,
            datetime.tm_mon,
            datetime.tm_mday,
            utc_offset)

        print('Fetching daily sun event data via: ' + sun_url)
        try:
            sun_response = json.loads(wifi.fetch_data(sun_url))
            watchdog.feed()
        except Exception as e:
            print('Request failed. Trying again...')
            watchdog.feed()
            time.sleep(3)
            sun_response = json.loads(wifi.fetch_data(sun_url))

        print('Fetching daily moon event data via: ' + moon_url)
        try:
            moon_response = json.loads(wifi.fetch_data(moon_url))
            watchdog.feed()
        except Exception as e:
            print('Request failed. Trying again...')
            watchdog.feed()
            time.sleep(3)
            moon_response = json.loads(wifi.fetch_data(moon_url))

        self.sunrise = None
        self.sunset = None
        self.moonset = None
        self.moonrise = None
        self.moonphase = float(moon_response['properties']['moonphase'])
        self.datetime = datetime

        if 'sunrise' in sun_response['properties'] and sun_response['properties']['sunrise']['time'] != None:
            self.sunrise = time.mktime(parse_time(sun_response['properties']['sunrise']['time']))
        else:
            print('Bad API response - missing sunrise property')
        if 'sunset' in sun_response['properties'] and sun_response['properties']['sunset']['time'] != None:
            self.sunset = time.mktime(parse_time(sun_response['properties']['sunset']['time']))
        else:
            print('Bad API response - missing sunset property')
        if 'moonrise' in moon_response['properties'] and moon_response['properties']['moonrise']['time'] != None:
            self.moonrise = time.mktime(parse_time(moon_response['properties']['moonrise']['time']))
        else:
            print('Bad API response - missing moonrise property')
        if 'moonset' in moon_response['properties'] and moon_response['properties']['moonset']['time'] != None:
            self.moonset = time.mktime(parse_time(moon_response['properties']['moonset']['time']))
        else:
            print('Bad API response - missing moonset property')
        return

########################################################################################################################

# Setup force sleep and wake buttons
pin_down = DigitalInOut(board.BUTTON_DOWN)
pin_down.switch_to_input(pull = Pull.UP) # Pull.DOWN doesn't fucking work!
pin_up = DigitalInOut(board.BUTTON_UP)
pin_up.switch_to_input(pull = Pull.UP)

# Turn off forced-sleep when we first boot up
nvm[0:1] = bytes([0])

# Setup LED matrix, orientation, and display groups
display = Matrix(bit_depth = BIT_DEPTH).display
accelerometer = LIS3DH_I2C(busio.I2C(board.SCL, board.SDA), address = 0x19)
accelerometer.acceleration # Dummy read to clear any existing data - really necessary? 🤷‍♂️
time.sleep(0.1)
display.rotation = (int(((math.atan2(-accelerometer.acceleration.y, -accelerometer.acceleration.x) + math.pi) / (math.pi * 2) + 0.875) * 4) % 4) * 90
landscape_orientation = display.rotation in (0, 180)
clock_face = displayio.Group()
snoozing = displayio.Group()

########################################################################################################################
# Append each element to the clock_face display group. They are numbered according to "append order", so take care...
########################################################################################################################

# Element 0 is the splash screen image (1 of 2), later replaced with the moon phase image and clock face.
try:
    splash_screen_image = 'splash-landscape.bmp' if landscape_orientation else 'splash-portrait.bmp'
    clock_face.append(displayio.TileGrid(displayio.OnDiskBitmap(open(splash_screen_image, 'rb')), pixel_shader = displayio.ColorConverter()))
    snoozing.append(displayio.TileGrid(displayio.OnDiskBitmap(open('sleeping.bmp', 'rb')), pixel_shader = displayio.ColorConverter()))
except Exception as e:
    print('Error loading image(s): {0}'.format(e))
    clock_face.append(Label(SMALL_FONT, color = 0xFF0000, text = 'ERROR!'))
    clock_face[0].x = (display.width - clock_face[0].bounding_box[2] + 1) // 2 # `//` is Integer division
    clock_face[0].y = display.height // 2 - 1

# Show splash screen while continuing to boot up
display.show(clock_face)
display.refresh()

# Elements 1-4 are a black outline around the moon percentage with text labels offset by 1 pixel. Initial text
# value must be long enough for longest anticipated string later since the bounding box is calculated here.
for i in range(4): clock_face.append(Label(SMALL_FONT, color = 0, text = '99.9%', y = -99))

# See CLOCK_MOON_PHASE and other constants defined above that correspond to the order of these clock_face.append calls.
clock_face.append(Label(SMALL_FONT, color = MOON_PHASE_COLOR, text = '99.9%', y = -99))
clock_face.append(Label(LARGE_FONT, color = TIME_COLOR, text = '24:59', y = -99))
clock_face.append(Label(SMALL_FONT, color = DATE_COLOR, text = '12/31', y = -99))
clock_face.append(Label(SYMBOL_FONT, color = 0x00FF00, text = 'x', y = -99))
clock_face.append(Label(SMALL_FONT, color = 0x00FF00, text = '24:59', y = -99))
clock_face.append(Label(SMALL_FONT, color = DATE_COLOR, text = '12', y = -99))

# Setup and connect to WiFi access point
esp32_cs = DigitalInOut(board.ESP_CS)
esp32_ready = DigitalInOut(board.ESP_BUSY)
esp32_reset = DigitalInOut(board.ESP_RESET)
spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
esp = adafruit_esp32spi.ESP_SPIcontrol(spi, esp32_cs, esp32_ready, esp32_reset)
wifi = Network(status_neopixel = board.NEOPIXEL, esp = esp, external_spi = spi, debug = False)
wifi.connect() # Logs "Connecting to AP"

# Setup watchdog to reset the board whenever a request times out or some other runtime delay or exception occurs
watchdog.timeout = WATCHDOG_TIMEOUT
watchdog.mode = WatchDogMode.RESET

# Get UTC and Lat/Lon values if they are not found in secrets.py
get_utc_offset()
get_lat_long()

try:
    print('Setting initial clock time. UTC offset is {0}'.format(utc_offset))
    datetime = update_time()
    print('')
except Exception as e: log_exception_and_restart('Error setting initial clock time: {0}'.format(e))

days = [
    SolarEphemera(datetime),
    SolarEphemera(time.localtime(time.mktime(datetime) + 86400))
]

########################################################################################################################

while True:
    try:
        display.rotation = (int(((math.atan2(-accelerometer.acceleration.y, -accelerometer.acceleration.x) + math.pi) / (math.pi * 2) + 0.875) * 4) % 4) * 90
        landscape_orientation = display.rotation in (0, 180)
        watchdog.feed()
        local_time = time.localtime()

        if secrets['sleep_time'] != None and secrets['wake_time'] != None: sleep_or_wake()

        # When we've transitioned to tomorrow, refetch ephemera, and DST (which changes over at around 2:00 AM)
        if local_time.tm_mday == days[TOMORROW].datetime.tm_mday:
            get_utc_offset()
            datetime = update_time()
            days = [
                SolarEphemera(datetime),
                SolarEphemera(time.localtime(time.mktime(datetime) + 86400))
            ]
            datetime = update_time()

        next_refresh_time = time.time() + REFRESH_DELAY
        while(time.time() < next_refresh_time):
            watchdog.feed()
            check_buttons()
            time.sleep(1)

        if asleep:
            print('.', end = '')
            check_buttons()
            continue

        # Sync WiFi time since on-board clock is inaccurate
        datetime = update_time()
        current_time = time.time()

        check_buttons()

        moon_frame = int((days[TODAY].moonphase / 360) * 100) % 100 # Bitmap 0 to 99
        percent = moon_phase_angle_to_illumination_percentage(days[TODAY].moonphase)

        if landscape_orientation:
            MOON_Y = 0         # Moon at the left
            CENTER_X = 48      # Text on the right
            TIME_Y = 6         # Time at top right
            DATE_Y = 16
            EVENT_Y = 27       # Events at bottom right
            CLOCK_GLYPH_X = 30 # Rise/set indicator
        else:                  # Vertical orientation
            CENTER_X = 16      # Text down center
            CLOCK_GLYPH_X = 0  # Rise/set indicator
            MOON_Y = 0         # Moon at the top
            TIME_Y = 37
            DATE_Y = 47
            EVENT_Y = 57
            # MOON_Y = 32      # Moon at the bottom
            # TIME_Y = 6
            # DATE_Y = 16
            # EVENT_Y = 26

        try:
            bitmap = displayio.OnDiskBitmap(open('moon/moon{0:0>2}.bmp'.format(moon_frame), 'rb'))
            tile_grid = displayio.TileGrid(bitmap, pixel_shader=displayio.ColorConverter())
            tile_grid.x = 0
            tile_grid.y = MOON_Y
            clock_face[0] = tile_grid
        except Exception as e: print('Error loading bitmap: {0}'.format(e))

        check_buttons()

        # Set CLOCK_MOON_PHASE first, use its size and position for painting the outlines below in elements 1-4
        clock_face[CLOCK_MOON_PHASE].text = '100%' if percent >= 99.95 else '{:.1f}%'.format(percent + 0.05)
        clock_face[CLOCK_MOON_PHASE].x = 16 - clock_face[CLOCK_MOON_PHASE].bounding_box[2] // 2 # Integer division
        clock_face[CLOCK_MOON_PHASE].y = MOON_Y + 16
        for i in range(1, 5): clock_face[i].text = clock_face[CLOCK_MOON_PHASE].text

        # Paint the black outline text labels for the current moon percentage by offsetting by 1 pixel in each direction
        clock_face[1].x, clock_face[1].y = clock_face[CLOCK_MOON_PHASE].x, clock_face[CLOCK_MOON_PHASE].y - 1
        clock_face[2].x, clock_face[2].y = clock_face[CLOCK_MOON_PHASE].x - 1, clock_face[CLOCK_MOON_PHASE].y
        clock_face[3].x, clock_face[3].y = clock_face[CLOCK_MOON_PHASE].x + 1, clock_face[CLOCK_MOON_PHASE].y
        clock_face[4].x, clock_face[4].y = clock_face[CLOCK_MOON_PHASE].x, clock_face[CLOCK_MOON_PHASE].y + 1

        if current_event == NUM_EVENTS: display_event('Sunrise today', days[TODAY].sunrise, TODAY_RISE)
        elif current_event == 7: display_event('Sunset today', days[TODAY].sunset, TODAY_SET)
        elif current_event == 6: display_event('Moonrise today', days[TODAY].moonrise, TODAY_RISE)
        elif current_event == 5: display_event('Moonset today', days[TODAY].moonset, TODAY_SET)
        elif current_event == 4: display_event('Sunrise tomorrow', days[TOMORROW].sunrise, TOMORROW_RISE)
        elif current_event == 3: display_event('Sunset tomorrow', days[TOMORROW].sunset, TOMORROW_SET)
        elif current_event == 2: display_event('Moonrise tomorrow', days[TOMORROW].moonrise, TOMORROW_RISE)
        elif current_event == 1: display_event('Moonset tomorrow', days[TOMORROW].moonset, TOMORROW_SET)

        # Each time through the main loop, we show a different event (in reverse order), wrapping around at the end
        current_event = current_event - 1 if current_event > 1 else NUM_EVENTS

        clock_face[CLOCK_TIME].text = hh_mm(local_time)
        clock_face[CLOCK_TIME].x = CENTER_X - clock_face[CLOCK_TIME].bounding_box[2] // 2
        clock_face[CLOCK_TIME].y = TIME_Y

        clock_face[CLOCK_DATE].text = '{0}-{1:0>2}'.format(local_time.tm_mon, local_time.tm_mday)
        clock_face[CLOCK_DATE].x = CENTER_X - clock_face[CLOCK_DATE].bounding_box[2] // 2
        clock_face[CLOCK_DATE].y = DATE_Y

        check_buttons()
        display.refresh()
        gc.collect()

        print('Moon Clock: Version {1} ({2:,} RAM free) @ {0} [frame: {3}, illum %: {4:.2f}, phase°: {5}]'
            .format(strftime(local_time), VERSION, gc.mem_free(), moon_frame, percent, days[TODAY].moonphase))
    except Exception as e:
        print(e)
        log_exception_and_restart('Unexpected exception: {0}'.format(e))
