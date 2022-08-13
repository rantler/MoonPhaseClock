# Moon Phase Clock

Made for Adafruit Matrix Portal: displays current time, lunar phase and time of next moonrise/sunrise or moonset/sunset.
Requires WiFi internet access. Uses IP geolocation if UTC offset and/or lat/lon not provided in `secrets.py`.

Written by Phil 'PaintYourDragon' Burgess for Adafruit Industries. MIT license, all text above must be included in any
redistribution.

## Supported buttons

* `UP` button forces the clock to wake
* `DOWN` button forces the clock to sleep
* `RESET` button resets the board - double-click to prepare for loading new UF2 firmware

-----
Additional features, documentation, and other changes by Randy Anter (tantalusrur@gmail.com).

* Support for portrait/landscape for event time format
* Add support for moon/sun rise/set for today/tomorrow
* Add support or sleep mode during certain hours of the night
* Add global-ish brightness control (fake, but somewhat helpful)
* Code simplification, formatting and readability improvements

## Initial setup

### Installing the CircuitPython firmware

Download the CircuitPython firmware here <https://circuitpython.org/board/matrixportal_m4/>. This build of the clock
uses version `7.3.2` which can be found in the file named `adafruit-circuitpython-matrixportal_m4-en_US-7.3.2.uf2`.

Once downloaded, the `bin/reflash` script can be used to erase the filesystem and upload the firmware.

### Installing the libraries

In addition to the firmware, you'll also need to download the appropriate version of the shared libraries. This build of
the clock uses version `7.x` of the libraries which can be found here
<https://github.com/adafruit/Adafruit_CircuitPython_Bundle/releases/download/20220727/adafruit-circuitpython-bundle-7.x-mpy-20220727.zip>.
There may be a newer version but check to make sure that it is compatible with version `7.3.2` of the firmware to ensure
compatibility.

The libraries contained in this archive will be used by the `bin/build` script when creating the `build` image to be
loaded onto the board. Please modify this script as needed to set the correct `LIB_PATH` in the script.

### Setup secrets for WiFi connectivity

The following required properties in the `secrets.yml` file _must be_ set in order to function correctly:

* `ssid` - A floating point value representing your location, i.e., 'MyWiFiNetwork'
* `password` - A floating point value representing your location, i.e. 'WiFiPassword'

The following _optional_ properties can sometimes be helpful to set manually are shown below. If any of these properties
are not present in the `secrets.py` file, they will be looked up dynamically as needed.

* `sleep_hour` - An integer value representing the hour at which the clock should sleep<sup>*</sup>
* `wake_hour` - An integer value representing the hour at which the clock should awake<sup>*</sup>
* `latitude` - A floating point value representing your location, i.e. 47.57
* `longitude` - A floating point value representing your location, i.e. -122.38
* `utc_offset` - A string value representing the difference from GMT / UTC in your timezone, i.e. '-08:00' in PST

<sup>*</sup>_Both `sleep_hour` and `wake_hour` must be present if either one is present in order to take effect._

### Using the build tools

There are some simple scripts in the `bin` directory that can be used to create a `build` from the files in the `src`
directory as well as a `deploy` script that copies the files from the `build` directory to the device using the `rsync`
program. There is also a simple `shell` command that starts up a `screen` session to monitor the logs and interact with
the Python REPL.

## Developer notes

### `EarthData` class

Class holding lunar data for a given day (`00:00:00` to `23:59:59`). App uses two of these -- one for the current day,
and one for the following day -- then some interpolations and such can be made.

Initialize EarthData object elements (see above) from a `time.struct_time`, hours to skip ahead (typically 0 or 24), and
a UTC offset (as a formatted string) and a query to the MET Norway Sunrise API which provides lunar data.

Sample URLs:

* <https://api.met.no/weatherapi/sunrise/2.0/documentation>
* <https://api.met.no/weatherapi/sunrise/2.0/.json?lat=47.56&lon=-122.39&date=2020-11-28&offset=-08:00>

| Property | Description |
| ---- | ---- |
| `age` | Moon phase 'age' at midnight (start of period) from 0.0 (new moon) to 0.5 (full moon) to 1.0 (next new moon).
| `midnight` | Epoch time in seconds at midnight (start of period).
| `moonrise` | Epoch time of moon rise within this 24-hour period.
| `moonset` | Epoch time of moon set within this 24-hour period.
| `sunrise` | Epoch time of sun rise within this 24-hour period.
| `sunset` | Epoch time of sun set within this 24-hour period.

### `parse_time` method

Given a string of the format `YYYY-MM-DDTHH:MM:SS.SS-HH:MM` and optional `DST` flag, convert to and return a
`time.struct_time` since `strptime()` isn't available here. Callers can invoke `time.mktime()` on the result if epoch
seconds is needed instead. Time string is assumed local time. If seconds value includes a decimal
fraction it's ignored.

### `update_time` method

Returns current local time as a `time.struct_time`. This may throw an exception on the `fetch_data()` call.

### `hh_mm` method

Simple time formatter that take a `time_struct` and formats a 12 or 24 hour formatted string which is used to display
the current time on the clock.

### `strftime` method

Poor man's string formatting function since `stftime` isn't available in the Python `time` library used in
CircuitPython.

### `display_event` method

Used to format and display the different diurnal events such as moonrise, or sunset. The single-arrow glyphs represent
today's events, while the double-arrow glyphs represent tomorrow's events.

### Fonts

Not all glyphs are necessarily defined in the symbol font, so check with Font Forge or some other font utility if you
can't find the glyph you're looking for.

The bounding box calculated by the `adafruit_display_text` module when a label is added to a `displayio.Group`, i.e. via
the `append` method, is only calcated at that moment. If you want to know the bounding box of dynamically changing text,
you'll need to reassign the label such that it contains the new text for which you'd like to know the bounding box. For
example, what is done with the date positioning as shown below (i.e. `bounding_box[2]`):

```py
CLOCK_FACE[CLOCK_MONTH] = Label(SMALL_FONT, color=DATE_COLOR, text=str(NOW.tm_mon), y=TIME_Y + 10)
CLOCK_FACE[CLOCK_MONTH].x = CENTER_X - 2 - CLOCK_FACE[10].bounding_box[2]
```

### Image conversion

Note, the BMP images must be 8-bit indexed color or they will not render. You can use
[ImageMagick](https://imagemagick.org/index.php), or [ImageScience](https://github.com/seattlerb/image_science) to
convert an existing BMP file to 8-bit indexed while also resizing it using a command like this one:

```sh
convert splash-portrait.bmp -depth 8 -resize 64x32 temp.bmp; mv temp.bmp splash-portrait.bmp
```

### Sleeping

In order to reduce the brightness of the display at night, the sleeping image is extremely dark and may appear totally
black on your computer display depending on your settings. The gamma level of the LED panel is extremely high, so even
very dark colors can appear bright. You can change the hours during which the display sleeps with in the `settings.py`,
or disable sleep mode entirely by setting the `sleep_hour` to a value higher than `24`.

> Note: Fine adjustment of the global brightness of the LED panel is not possible without the use of some kind of PWM
> library, which at the time of this writing does not exist.

### Memory limitations

Memory size of this project is approaching the limits of
[CircuitPython](https://learn.adafruit.com/welcome-to-circuitpython?view=all#what-is-a-memoryerror-3020684-8) so be
aware that additional code changes can sometimes behave inconsistently and/or result in a `MemoryError`. In my
experience, the overall size of the `code.py` file can be no larger than 19K or you'll start encountering spurious
memory allocation errors. It seems that using the `format` function rather than string concatenation helps reduce
runtime memory use somewhat. Runtime free memory low water mark at the time of this writing is about 4KB with the high
water mark being around 7KB.

## Helpful hints

To use the `screen` utility on Mac OS you can do this:

```sh
screen /dev/tty.usbmodem1461 115200 ; reset
```

> Note: The `reset` command that will be automatically run upon exiting is to fix any terminal output weirdness that can
> be caused when `screen` exits.

To erase the file system on the M4, you can run this in the REPL:

```py
import storage
storage.erase_filesystem()
```

This will completely erase whatever was in the file system prior, and set it up with a default `boot.py` file.
