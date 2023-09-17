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
Additional features, documentation, and other changes by Randy Anter (<tantalusrur@gmail.com>).

* Support for portrait/landscape for event time format
* Add support for moon/sun rise/set for today/tomorrow
* Add support or sleep mode during certain hours of the night
* Add global-ish brightness control (fake, but somewhat helpful)
* Code simplification, formatting and readability improvements
* Updated to use version 3.0 of the Sunrise JSON [API](https://docs.api.met.no/doc/formats/SunriseJSON)
* Provide `bin/reflash` script to handle uploading new Firmware and code to the board

## Initial setup

### Installing the CircuitPython firmware

Download the CircuitPython firmware here <https://circuitpython.org/board/matrixportal_m4/>. This build of the clock
uses version `8.2.5` which can be found in the file named `adafruit-circuitpython-matrixportal_m4-en_US-8.2.5.uf2`.

Once downloaded, the `bin/reflash` script can be used to erase the filesystem and upload the firmware and clock code.

### Installing the libraries

In addition to the firmware, you'll also need to download the appropriate version of the shared libraries. This build of
the clock uses version `8.2.5` of the libraries which can be found at
[circuitpython.org](https://circuitpython.org/board/matrixportal_m4/) or on
[GitHub](https://github.com/adafruit/Adafruit_CircuitPython_Bundle/releases). There may be a newer version but check to
make sure that it is compatible with version `8.x` of the firmware to ensure compatibility.

The libraries contained in this archive will be used by the `bin/build` script when creating the `build` image to be
loaded onto the board. _Please modify this script as needed to set the correct `LIB_PATH` in the script._

### Setup secrets for WiFi connectivity

First, copy or rename the `secrets-example.py` file to `secrets.py`, then update the following required properties in
the in order for the clock to function correctly:

* `ssid` - A floating point value representing your location, i.e., 'MyWiFiNetwork'
* `password` - A floating point value representing your location, i.e. 'WiFiPassword'

The following _optional_ properties can sometimes be helpful to set manually are shown below. If any of these properties
are not present in the `secrets.py` file, they will be looked up dynamically as needed.

* `sleep_hour` - An integer value representing the hour at which the clock should sleep
* `wake_hour` - An integer value representing the hour at which the clock should awake
  * _Both `sleep_hour` and `wake_hour` must be present in order to take effect_
* `latitude` - A floating point value representing your location, i.e. 47.57
* `longitude` - A floating point value representing your location, i.e. -122.38
* `utc_offset` - A string value representing the difference from GMT / UTC in your timezone, i.e. '-08:00' in PST
  * _If you leave this blank, the UTC offset will be determined by geolocation based on your IP address_

### Using the build tools

There are some simple scripts in the `bin` directory that can be used to create a `build` from the files in the `src`
directory as well as a `deploy` script that copies the files from the `build` directory to the device using the `rsync`
program. There is also a simple `shell` command that starts up a `screen` session to monitor the logs and interact with
the Python REPL.

## Developer notes

### `SolarEphemera` class

This class holds the sun and moon ephemera for a given day (`00:00:00` to `23:59:59`). The clock uses two instances --
one for the current day, and one for the following day.

Sample URLs:

* <https://api.met.no/weatherapi/sunrise/3.0/documentation>
* <https://api.met.no/weatherapi/sunrise/3.0/moon?lat=47.608&lon=-122.335&date=2023-09-16&offset=-07:00>

#### Properties that are used in the API response

| Property | Description |
| ---- | ---- |
| `moonrise` | Epoch time of moon rise within this 24-hour period.
| `moonset` | Epoch time of moon set within this 24-hour period.
| `sunrise` | Epoch time of sun rise within this 24-hour period.
| `sunset` | Epoch time of sun set within this 24-hour period.
| `moonphase` | Moon phase in degrees which ranges from 0 to 360 (180 is full moon)

-----

### `parse_time` method

Given a string of the format `2023-09-16T20:02-07:00` it will convert to and return a `time.struct_time` since
`strptime()` isn't available here. Callers can invoke `time.mktime()` on the result if epoch seconds is needed instead.
Time string is assumed local time. The _seconds_ value is always `0` since it is not provided in the MET API Sunrise
JSON response.

### `update_time` method

Returns current local time as a `time.struct_time`. It determines the current timestamp by using the ESP32 WiFi
interface.

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
the `append` method, is only calculated at that moment. If you want to know the bounding box of dynamically changing
text, you'll need to reassign the label such that it contains the new text for which you'd like to know the bounding
box. For example, what is done with the date positioning as shown below (i.e. `bounding_box[2]`):

```py
clock_face[CLOCK_EVENT] = Label(SMALL_FONT, color = EVENT_COLOR, text = event_time, y = EVENT_Y)
clock_face[CLOCK_EVENT].x = max(CLOCK_GLYPH_X + 6, CENTER_X - clock_face[CLOCK_EVENT].bounding_box[2] // 2)
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
or disable sleep mode entirely by omitting either the `sleep_hour` or `wake_hour` values.

> Note: Fine adjustment of the global brightness of the LED panel is not possible without the use of some kind of PWM
> library, which at the time of this writing does not exist for the Matrix Portal M4 board.

### Memory limitations

Memory size of this project is approaching the limits of
[CircuitPython](https://learn.adafruit.com/welcome-to-circuitpython?view=all#what-is-a-memoryerror-3020684-8) so be
aware that additional code changes can sometimes behave inconsistently and/or result in a `MemoryError`. In my
experience, the overall size of the `code.py` file can be no larger than around 19K or you'll start encountering
spurious memory allocation errors. It seems that using the `format` function rather than string concatenation helps
reduce runtime memory use somewhat. Your mileage may vary...

| Event | RAM free |
| --- | ---: |
| boot | 142,496 |
| after imports | 74,064 |
| after all code loaded | 29,504 |

### Watchdog

Due to intermittent [errors](https://github.com/adafruit/circuitpython/issues/6205) that are purportedly caused by
interaction between the ESP32 and the LED matrix, this code now employs a watchdog timer that automatically resets the
board if any network requests timeout. It can sometimes take several restarts before the WiFi network is stable.

_Note: The **maximum** timeout value for the watchdog appears to be around 12 seconds._

## Helpful hints

To use the `screen` utility on Mac OS you can do this:

```sh
screen /dev/tty.usbmodem1461 115200 ; reset
```

> Note: The `reset` command that will be automatically run upon exiting is to fix any terminal output weirdness that can
> be caused when `screen` exits.

To erase the file system on the M4, you can manually run this code in the REPL:

```py
import storage
storage.erase_filesystem()
```

This will completely erase whatever was in the file system prior, and set it up with a default `boot.py` file.
