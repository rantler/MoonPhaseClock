import gc

VERSION = '1.6.3.9'
print('Moon Clock - Version {0} ({1:,} RAM free)'.format(VERSION, gc.mem_free()))

import json
import math
import time

import adafruit_lis3dh
import board
import busio
import displayio
import microcontroller
import supervisor
from adafruit_bitmap_font import bitmap_font
from adafruit_display_text.label import Label
from adafruit_esp32spi import adafruit_esp32spi
from adafruit_matrixportal.matrix import Matrix
from adafruit_matrixportal.network import Network
from digitalio import DigitalInOut, Pull
from rtc import RTC

import color
from secrets import secrets

print('Imports loaded - ({0:,} RAM free)'.format(gc.mem_free()))

BIT_DEPTH = 6
REFRESH_DELAY = 10
TODAY = 0
TOMORROW = 1

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
SYMBOL_FONT.load_glyphs('\u2191\u2193\u219F\u21A1')

########################################################################################################################

def get_utc_offset_from_api():
    utc_offset = None
    try:
        print('Determining UTC offset by IP geolocation')
        dst, utc_offset = wifi.fetch_data('http://worldtimeapi.org/api/ip', json_path=[['dst'], ['utc_offset']])
    except Exception as e:
        print('Failed to fetch from worldtimeapi.org. Error: {0}'.format(e))
    return utc_offset

def get_time_from_esp():
    times = 30
    esp_time = 0
    while times > 0 and esp_time == 0:
        time.sleep(10)
        try:
            esp_time = esp.get_time()
            if esp_time == 0:
                print('o', end='')
                times -= 1
        except Exception as e:
            print('x', end='')
            times -= 1
    if times != 30: print('')
    return time.localtime(esp_time[0] + int(utc_offset.split(':')[0]) * 3600 + int(utc_offset.split(':')[1]) * 60)

def forced_asleep(): return microcontroller.nvm[0] == 1

# When forced asleep, the clock will remain sleeping until forced awake
def sleep(forced = False):
    global asleep # Are you fucking kidding me? Python is teh sux0rz! 😂
    if not asleep:
        display.show(snoozing)
        display.refresh()
        asleep = True
    if forced: microcontroller.nvm[0:1] = bytes([1])

# When forced awake, will resume sleeping at the scheduled time, if configured to do so
def wake(forced = False):
    global asleep
    if asleep:
        display.show(clock_face)
        display.refresh()
        asleep = False
    if forced: microcontroller.nvm[0:1] = bytes([0])

def check_buttons():
    if not pin_down.value: # negating to indicate button pressed because Pull.UP 😵
        while not pin_down.value: pass
        sleep(forced = True)
    if not pin_up.value:
        while not pin_up.value: pass
        wake(forced = True)

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

def update_time():
    time_struct = get_time_from_esp()
    RTC().datetime = time_struct
    return time_struct

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
    time_struct = time.localtime(event)

    if name.startswith('Sun'):
        EVENT_COLOR = clock_face[CLOCK_EVENT].color = SUN_EVENT_COLOR
        hour = 12 if time_struct.tm_hour == 0 else time_struct.tm_hour
        event_time = '{0}:{1:0>2}'.format(hour, time_struct.tm_min)
    else:
        EVENT_COLOR = clock_face[CLOCK_EVENT].color = MOON_EVENT_COLOR
        event_time = '{0}:{1:0>2}'.format(time_struct.tm_hour, time_struct.tm_min)

    clock_face[CLOCK_EVENT] = Label(SMALL_FONT, color=EVENT_COLOR, text=event_time, y=EVENT_Y)
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
    supervisor.reload() # Reboot / restart

########################################################################################################################

class EarthData():
    def __init__(self, datetime):
        url = 'https://api.met.no/weatherapi/sunrise/2.0/.json?lat={0}&lon={1}&date={2:0>2}-{3:0>2}-{4:0>2}&offset={5}'.format(
            latitude,
            longitude,
            datetime.tm_year,
            datetime.tm_mon,
            datetime.tm_mday,
            utc_offset)

        for _ in range(5): # Number of retries
            try:
                print('Fetching diurnal event data via: ' + url)
                full_data = json.loads(wifi.fetch_data(url))
                location_data = full_data['location']['time'][0]
                self.age = float(location_data['moonphase']['value']) / 100
                self.midnight = time.mktime(parse_time(location_data['moonphase']['time']))

                if 'sunrise' in location_data: self.sunrise = time.mktime(parse_time(location_data['sunrise']['time']))
                else: self.sunrise = None
                if 'sunset' in location_data: self.sunset = time.mktime(parse_time(location_data['sunset']['time']))
                else: self.sunset = None
                if 'moonrise' in location_data: self.moonrise = time.mktime(parse_time(location_data['moonrise']['time']))
                else: self.moonrise = None
                if 'moonset' in location_data: self.moonset = time.mktime(parse_time(location_data['moonset']['time']))
                else: self.moonset = None

                full_data = None
                location_data = None
                gc.collect()
                return
            except Exception as e:
                print('Fetching moon data for date via URL: {0} failed. Error: {1}'.format(url, e))
                time.sleep(15)

########################################################################################################################

# Setup force sleep and wake buttons
pin_down = DigitalInOut(board.BUTTON_DOWN)
pin_down.switch_to_input(pull = Pull.UP) # Pull.DOWN doesn't fucking work!
pin_up = DigitalInOut(board.BUTTON_UP)
pin_up.switch_to_input(pull = Pull.UP)

# Turn off forced-sleep when we first boot up
microcontroller.nvm[0:1] = bytes([0])

# Setup LED matrix, orientation, and display groups
display = Matrix(bit_depth = BIT_DEPTH).display
accelerometer = adafruit_lis3dh.LIS3DH_I2C(busio.I2C(board.SCL, board.SDA), address = 0x19)
accelerometer.acceleration # Dummy read to clear any existing data
time.sleep(0.1)
display.rotation = (int(((math.atan2(-accelerometer.acceleration.y, -accelerometer.acceleration.x) + math.pi) / (math.pi * 2) + 0.875) * 4) % 4) * 90
landscape_orientation = display.rotation in (0, 180)
clock_face = displayio.Group()
snoozing = displayio.Group()

# Element 0 is the splash screen image (1 of 2), later replaced with the moon phase image and clock face.
try:
    splash_screen_image = 'splash-landscape.bmp' if landscape_orientation else 'splash-portrait.bmp'
    clock_face.append(displayio.TileGrid(displayio.OnDiskBitmap(open(splash_screen_image, 'rb')), pixel_shader=displayio.ColorConverter()))
    snoozing.append(displayio.TileGrid(displayio.OnDiskBitmap(open('sleeping.bmp', 'rb')), pixel_shader=displayio.ColorConverter()))
except Exception as e:
    print('Error loading image(s): {0}'.format(e))
    clock_face.append(Label(SMALL_FONT, color=0xFF0000, text='OOPS!'))
    clock_face[0].x = (display.width - clock_face[0].bounding_box[2] + 1) // 2 # Integer division
    clock_face[0].y = display.height // 2 - 1 # Integer division

# Show splash screen while continuing to boot up
display.show(clock_face)
display.refresh()

# Append each element to the clock_face display group. They are numbered according to "append order", so take care...

# Elements 1-4 are a black outline around the moon percentage with text labels offset by 1 pixel. Initial text
# value must be long enough for longest anticipated string later since the bounding box is calculated here.
for i in range(4): clock_face.append(Label(SMALL_FONT, color=0, text='99.9%', y=-99))

CLOCK_MOON_PHASE = 5
clock_face.append(Label(SMALL_FONT, color=MOON_PHASE_COLOR, text='99.9%', y=-99))
CLOCK_TIME = 6
clock_face.append(Label(LARGE_FONT, color=TIME_COLOR, text='24:59', y=-99))
CLOCK_DATE = 7
clock_face.append(Label(SMALL_FONT, color=DATE_COLOR, text='12/31', y=-99))
# Element 8 is a symbol indicating next rise or set - Color is overridden by event colors
CLOCK_GLYPH = 8
clock_face.append(Label(SYMBOL_FONT, color=0x00FF00, text='x', y=-99))
# Element 9 is the time of (or time to) next rise/set event - Color is overridden by event colors
CLOCK_EVENT = 9
clock_face.append(Label(SMALL_FONT, color=0x00FF00, text='24:59', y=-99))
CLOCK_MONTH = 10
clock_face.append(Label(SMALL_FONT, color=DATE_COLOR, text='12', y=-99))
CLOCK_SLASH = 11
clock_face.append(Label(SMALL_FONT, color=DATE_COLOR, text='/', y=-99))
CLOCK_DAY = 12
clock_face.append(Label(SMALL_FONT, color=DATE_COLOR, text='2', y=-99))

# Setup and connect to WiFi access point
esp32_cs = DigitalInOut(board.ESP_CS)
esp32_ready = DigitalInOut(board.ESP_BUSY)
esp32_reset = DigitalInOut(board.ESP_RESET)
spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
esp = adafruit_esp32spi.ESP_SPIcontrol(spi, esp32_cs, esp32_ready, esp32_reset)
wifi = Network(status_neopixel=board.NEOPIXEL, esp=esp, external_spi=spi, debug=False)
wifi.connect() # Logs "Connecting to AP ...""
# TODO: Reconnect to WiFi after temporary connection loss in main clock loop

# Try to read the latitude/longitude from the secrets. If not present, then use IP geolocation
try:
    latitude = secrets['latitude']
    longitude = secrets['longitude']
    print('Lat/lon determined from secrets: {0}, {1}'.format(latitude, longitude))
except KeyError:
    latitude, longitude = wifi.fetch_data('http://www.geoplugin.net/json.gp', json_path=[['geoplugin_latitude'], ['geoplugin_longitude']])
    print('Lat/lon determined from IP geolocation: {0}, {1}'.format(latitude, longitude))

# Try to read the UTC offset from the secrets. If not present, it will be set below via API call
try:
    utc_offset = secrets['utc_offset']
    print('UTC offset determined from secrets: ' + utc_offset)
# Probably should refetch this every day at around 2:00 AM since that's when DST changes
except: utc_offset = get_utc_offset_from_api()

try:
    datetime = update_time()
    print('Setting initial clock time. UTC offset is {0}'.format(utc_offset))
except Exception as e: log_exception_and_restart('Error setting initial clock time: {0}'.format(e))

days = [
    EarthData(datetime),
    EarthData(time.localtime(time.mktime(datetime) + 86400)) # seconds in a day
]
current_clock_event = 8
asleep = False

########################################################################################################################

while True:
    try:
        gc.collect()
        local_time = time.localtime()

        if secrets['sleep_hour'] != None and secrets['wake_hour'] != None:
            if local_time.tm_hour >= secrets['sleep_hour'] and local_time.tm_hour < secrets['wake_hour'] and not asleep:
                print("Current hour is {0} and sleep_hour is {1}. Going to sleep...".format(local_time.tm_hour, secrets['sleep_hour']))
                sleep()
            if local_time.tm_hour >= secrets['wake_hour'] and asleep and not forced_asleep():
                print("\nCurrent hour is {0} and wake_hour is {1}. Waking up...".format(local_time.tm_hour, secrets['wake_hour']))
                wake()

        refresh_time = time.time() + REFRESH_DELAY
        while(time.time() < refresh_time): check_buttons()

        if asleep:
            print('.', end = '') # Really? "end = ''"? Are you fucking kidding me python? wtf...
            continue

        # Sync WiFi time since on-board clock is inaccurate
        datetime = update_time()
        current_time = time.time()

        check_buttons()

        # Determine weighting of tomorrow's phase vs today's, using current time
        ratio = (current_time - days[TODAY].midnight) / (days[TOMORROW].midnight - days[TODAY].midnight)

        if days[TODAY].age < days[TOMORROW].age:
            age = (days[TODAY].age + (days[TOMORROW].age - days[TODAY].age) * ratio) % 1.0
        else:
            # Handle age wraparound (1.0 -> 0.0). If tomorrow's age is less than today's, it indicates a new moon
            # crossover. Add 1 to tomorrow's age when computing age delta.
            age = (days[TODAY].age + (days[TOMORROW].age + 1 - days[TODAY].age) * ratio) % 1.0

        # age can be used for direct lookup to moon bitmap (0 to 99). The images are pre-rendered for a linear
        # timescale. Note that the solar terminator moves nonlinearly across sphere.
        moon_frame = int(age * 100) % 100 # Bitmap 0 to 99

        # Then use some trig to get percentage illuminated
        if age <= 0.5: # New -> first quarter -> full
            percent = (1 - math.cos(age * 2 * math.pi)) * 50
        else:          # Full -> last quarter -> new
            percent = (1 + math.cos((age - 0.5) * 2 * math.pi)) * 50

        next_moon_event = days[TOMORROW].midnight + 100000 # Force first match
        for day in reversed(days):
            if day.moonrise and next_moon_event >= day.moonrise >= current_time:
                next_moon_event = day.moonrise
                moon_risen = False
            if day.moonset and next_moon_event >= day.moonset >= current_time:
                next_moon_event = day.moonset
                moon_risen = True

        if landscape_orientation:
            CENTER_X = 48      # Text along right
            MOON_Y = 0         # Moon at left
            TIME_Y = 6         # Time at top right
            EVENT_Y = 27       # Rise/set at bottom right
            CLOCK_GLYPH_X = 30
        else:                  # Vertical 'portrait' orientation
            CENTER_X = 16      # Text down center
            CLOCK_GLYPH_X = 0
            if moon_risen:
                MOON_Y = 0     # Moon at top
                EVENT_Y = 38   # Rise/set in middle
                TIME_Y = 49    # Time/date at bottom
            else:
                TIME_Y = 6     # Time/date at top
                EVENT_Y = 26   # Rise/set in middle
                MOON_Y = 32    # Moon at bottom

        try:
            bitmap = displayio.OnDiskBitmap(open('moon/moon{0:0>2}.bmp'.format(moon_frame), 'rb'))
            tile_grid = displayio.TileGrid(bitmap, pixel_shader=displayio.ColorConverter())
            tile_grid.x = 0
            tile_grid.y = MOON_Y
            clock_face[0] = tile_grid
        except Exception as e: print('Error loading bitmap: {0}'.format(e))

        check_buttons()

        # Set CLOCK_MOON_PHASE first, use its size and position for painting the outlines below
        clock_face[CLOCK_MOON_PHASE].text = '100%' if percent >= 99.95 else '{:.1f}%'.format(percent + 0.05)
        clock_face[CLOCK_MOON_PHASE].x = 16 - clock_face[CLOCK_MOON_PHASE].bounding_box[2] // 2 # Integer division
        clock_face[CLOCK_MOON_PHASE].y = MOON_Y + 16
        # Elements 1-4 are the black outline, while element 5 (CLOCK_MOON_PHASE) is the visible percentage text
        for i in range(1, 5): clock_face[i].text = clock_face[CLOCK_MOON_PHASE].text

        # Paint the black outline text labels for the current moon percentage by offsetting by 1 pixel in each direction
        clock_face[1].x, clock_face[1].y = clock_face[CLOCK_MOON_PHASE].x, clock_face[CLOCK_MOON_PHASE].y - 1
        clock_face[2].x, clock_face[2].y = clock_face[CLOCK_MOON_PHASE].x - 1, clock_face[CLOCK_MOON_PHASE].y
        clock_face[3].x, clock_face[3].y = clock_face[CLOCK_MOON_PHASE].x + 1, clock_face[CLOCK_MOON_PHASE].y
        clock_face[4].x, clock_face[4].y = clock_face[CLOCK_MOON_PHASE].x, clock_face[CLOCK_MOON_PHASE].y + 1

        if current_clock_event == 8:   display_event('Sunrise today', days[TODAY].sunrise, TODAY_RISE)
        elif current_clock_event == 7: display_event('Sunset today', days[TODAY].sunset, TODAY_SET)
        elif current_clock_event == 6: display_event('Moonrise today', days[TODAY].moonrise, TODAY_RISE)
        elif current_clock_event == 5: display_event('Moonset today', days[TODAY].moonset, TODAY_SET)
        elif current_clock_event == 4: display_event('Sunrise tomorrow', days[TOMORROW].sunrise, TOMORROW_RISE)
        elif current_clock_event == 3: display_event('Sunset tomorrow', days[TOMORROW].sunset, TOMORROW_SET)
        elif current_clock_event == 2: display_event('Moonrise tomorrow', days[TOMORROW].moonrise, TOMORROW_RISE)
        elif current_clock_event == 1: display_event('Moonset tomorrow', days[TOMORROW].moonset, TOMORROW_SET)

        # Each time through the main loop, we show a different event (in reverse order), wrapping around at the end
        current_clock_event -= 1 if current_clock_event == 1 else 8

        clock_face[CLOCK_TIME].text = hh_mm(local_time)
        clock_face[CLOCK_TIME].x = CENTER_X - clock_face[CLOCK_TIME].bounding_box[2] // 2
        clock_face[CLOCK_TIME].y = TIME_Y

        clock_face[CLOCK_MONTH] = Label(SMALL_FONT, color=DATE_COLOR, text=str(local_time.tm_mon), y=TIME_Y + 10)
        clock_face[CLOCK_MONTH].x = CENTER_X - 1 - clock_face[CLOCK_MONTH].bounding_box[2]
        clock_face[CLOCK_SLASH].text = '/'
        clock_face[CLOCK_SLASH].x = CENTER_X
        clock_face[CLOCK_SLASH].y = TIME_Y + 10
        clock_face[CLOCK_DAY].text = str(local_time.tm_mday)
        clock_face[CLOCK_DAY].x = CENTER_X + 4
        clock_face[CLOCK_DAY].y = TIME_Y + 10

        check_buttons()

        display.refresh()
        print('Moon Clock - local time is {0} - Version {1} ({2:,} RAM free)'.format(strftime(local_time), VERSION, gc.mem_free()))
    except Exception as e: log_exception_and_restart('Unexpected exception: {0}'.format(e))
