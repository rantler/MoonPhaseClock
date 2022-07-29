# Converts an RGB color value to HSL. Conversion formula
# adapted from http://en.wikipedia.org/wiki/HSL_color_space.
# Assumes r, g, and b are contained in the set [0, 255] and
# returns h, s, and l in the set [0.0, 1.0].
#
# @param   {number}  r       The red color value
# @param   {number}  g       The green color value
# @param   {number}  b       The blue color value
# @return  {Array}           The HSL representation
def rgb_to_hsl(r, g, b):
    r = r / 255.0
    g = g / 255.0
    b = b / 255.0
    _max = max(r, g, b)
    _min = min(r, g, b)
    h = 0
    s = 0
    l = (_max + _min) / 2

    if (_max == _min):
        h = s = 0 # achromatic
    else:
        d = _max - _min
        s = d / (2 - _max - _min) if (l > 0.5) else d / (_max + _min)
        if (_max == r):
            h = (g - b) / d + (6 if g < b else 0)
        if (_max == g):
            h = (b - r) / d + 2
        if (_max == b):
            h = (r - g) / d + 4
        h = h / 6

    return [round(h, 4), round(s, 4), round(l, 4)]

# Converts an HSL color value to RGB. Conversion formula
# adapted from http://en.wikipedia.org/wiki/HSL_color_space.
# Assumes h, s, and l are contained in the set [0.0, 1.0] and
# returns r, g, and b in the set [0, 255].
#
# @param   {number}  h       The hue value
# @param   {number}  s       The saturation value
# @param   {number}  l       The lightness value
# @return  {Array}           The RGB representation
def hsl_to_rgb(h, s, l):
    r = 0
    g = 0
    b = 0

    def hue_to_rgb(p, q, t):
        if (t < 0):
            t += 1
        if (t > 1):
            t -= 1
        if (t < 1.0/6):
            return p + (q - p) * 6.0 * t
        if (t < 1.0/2):
            return q
        if (t < 2.0/3):
            return p + (q - p) * (2.0/3 - t) * 6.0
        return p

    if (s == 0):
        r = g = b = l # achromatic
    else:
        q = l * (1 + s) if l < 0.5 else l + s - l * s
        p = 2 * l - q
        r = hue_to_rgb(p, q, h + 1.0/3)
        g = hue_to_rgb(p, q, h)
        b = hue_to_rgb(p, q, h - 1.0/3)

    return [int(round(r * 255)), int(round(g * 255)), int(round(b * 255))]

# Adjusts overall brightness of the color value by a percentage and returns
# the resulting RGB color value.
#
# @param   {number}  color   The color value e.g. 0x336699
# @param   {number}  value   The saturation value as a percentage e.g. 0.5
# @return  {Array}           The RGB representation of the result
def set_brightness(color, value):
    r = (color & 0xFF0000) >> 16
    g = (color & 0xFF00) >> 8
    b = color & 0xFF
    h, s, l = rgb_to_hsl(r, g, b)

    return hsl_to_rgb(h, s, l * value)
