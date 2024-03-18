import datetime
import errno
import hashlib
import io
import json
import math
import os
import pathlib
import tempfile
import time

from ical.calendar_stream import IcsCalendarStream
from PIL import Image, ImageDraw, ImageFont
import requests
import swiftclient.client
try:
    import xattr
except ImportError:
    xattr = None

class FontCache(dict):
    def __missing__(self, sz):
        self[sz] = ImageFont.load_default(sz)
        return self[sz]

fonts = FontCache()
del FontCache

CACHE_DIR = pathlib.Path(tempfile.gettempdir()) / 'status-cache'
DEFAULT_TTL = 3600
WEATHER_TTL = DEFAULT_TTL
TRANSIT_TTL = 60
CALENDAR_TTL = 300

def cached_get(url, ttl=None):
    ttl = DEFAULT_TTL if ttl is None else ttl
    f = CACHE_DIR / hashlib.md5(url.encode('ascii')).hexdigest()[:8]
    if ttl:
        try:
            st = os.stat(f)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise
            cached = False
        else:
            cached = ((time.time() - st.st_mtime) < ttl)

        if cached:
            with open(f, 'rb') as fp:
                return fp.read()
        # Else, make request & cache it
    data = requests.get(url).content
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(f, 'wb') as fp:
        fp.write(data)
        if xattr:
            xattr.setxattr(fp, b'user.url', url.encode('utf8'))
    return data

def cached_json(url, ttl=None):
    data = cached_get(url, ttl)
    try:
        return json.loads(data)
    except ValueError:
        # cache is bad?
        return json.loads(cached_get(url, 0))

def get_transit_schedules(stops):
    result = {}
    for stop_code, lines in stops.items():
        if isinstance(lines, str):
            lines = [lines]
        data = cached_json(f'https://www.sfmta.com/umo/stopcodes/{stop_code}/predictions', TRANSIT_TTL)
        result[stop_code] = {
            'name': data[0]['stop']['name'],
            'lines': [],
        }
        for line in lines:
            l = [x for x in data if x['route']['id'] == line]
            if not l:
                # TODO: warn?
                continue
            result[stop_code]['lines'].append({
                'title': l[0]['route']['title'],
                'arrivals': [
                    {
                        'minutes': b['minutes'],
                        'to': b['direction']['name'],
                    }
                    for b in l[0]['values']
                ],
            })
    return result


#weather = cached_json('https://wttr.in/94116?format=j1', WEATHER_TTL)
lat, lon = 37.74, -122.5
weather = cached_json(f'https://api.weather.gov/points/{lat},{lon}', WEATHER_TTL)
weather = cached_json(weather['properties']['forecast'], WEATHER_TTL)
#transit = get_transit_schedules({
#    16633: ['LBUS', 'L'],
#    16454: '23',
#    #16994: ['K', 'L', 'M', 'S'],
#})
schedule = IcsCalendarStream.calendar_from_ics(cached_get(
    os.environ['ICAL_URL'], CALENDAR_TTL).decode('utf8'))


im = Image.new('1', (800, 600), 1)
d = ImageDraw.Draw(im)

if False:
    # wttr weather
    d.text((50, 10), weather['current_condition'][0]['temp_F'] + '\N{DEGREE SIGN}F', font=fonts[100])
    desc = ', '.join(x['value'] for x in weather['current_condition'][0]['weatherDesc'])
    d.text((10, 120), desc, font=fonts[24])

    d.text((30, 140), time.strftime("%I:%M"), font=fonts[100])

    w = 10
    relative_day = {
        0: 'Today',
        1: 'Tomorrow',
        2: 'Next Day',
    }
    for i, f in enumerate(weather['weather']):
        d.text((w, 250), relative_day.get(i, f['date']), font=fonts[12])
        d.text((w, 265), f"{f['mintempF']} - {f['maxtempF']}", font=fonts[12])
        w += 90

    d.text((10, 280), 'Weather as of ' + weather['current_condition'][0]['localObsDateTime'], font=fonts[10])

if True:
    # NWS weather
    h = 20
    for pred in weather['properties']['periods'][:6:2]:
        d.text((20, h), pred['name'], font=fonts[20])
        h += 20
        d.text((20, h), str(pred['temperature']) + '\N{DEGREE SIGN}' + pred['temperatureUnit'], font=fonts[60])
        h += 60
        if len(pred['shortForecast']) < 20:
            d.text((20, h), pred['shortForecast'], font=fonts[20])
        else:
            d.text((20, h), pred['shortForecast'], font=fonts[12])
        h += 40

    h = 20
    for pred in weather['properties']['periods'][1:6:2]:
        d.text((200, h), pred['name'], font=fonts[20])
        h += 20
        d.text((200, h), str(pred['temperature']) + '\N{DEGREE SIGN}' + pred['temperatureUnit'], font=fonts[60])
        h += 60
        d.text((200, h), pred['shortForecast'], font=fonts[20])
        h += 40

    #d.text((200, 500 - 20), time.strftime("%I:%M"), anchor="mm", font=fonts[100])
    # centered at (200, 480), radius 100
    d.ellipse(((100, 380), (300, 580)), outline='black', width=2)
    for x in range(12):
        rad = x * math.pi / 6
        if x % 3 == 0:
            d.line((
                (200 + 88 * math.sin(rad), 480 - 88 * math.cos(rad)),
                (200 + 96 * math.sin(rad), 480 - 96 * math.cos(rad)),
            ), width=3)
        else:
            d.line((
                (200 + 92 * math.sin(rad), 480 - 92 * math.cos(rad)),
                (200 + 96 * math.sin(rad), 480 - 96 * math.cos(rad)),
            ))
    now = datetime.datetime.now()
    rad = now.minute / 60 * 2 * math.pi
    d.line((
        (200, 480),
        (200 + 85 * math.sin(rad), 480 - 85 * math.cos(rad)),
    ), width=4)
    rad = (now.hour + now.minute / 60) / 12 * 2 * math.pi
    d.line((
        (200, 480),
        (200 + 65 * math.sin(rad), 480 - 65 * math.cos(rad)),
    ), width=8)

W, H = 360, 600
if False:
    h = -10
    for stop in transit.values():
        h += 22
        for line in stop['lines']:
            h += 32

    x, y, h = 20, H - h - 20, 0
    for stop in transit.values():
        d.text((x, y + h), stop['name'], font=fonts[12])
        h += 12
        for i, line in enumerate(stop['lines']):
            h += 2
            d.line([(x + (0 if i == 0 else 5), y+h), (x+W, y+h)])
            h += 1

            d.text((x + 10, y + h), line['title'], font=fonts[12])
            arrivals = ', '.join(format(b['minutes'], '2d') for b in line['arrivals'])
            d.text((x + W - 100, y + h), arrivals, font=fonts[24])
            h += 16

            d.text((x + 10, y + h), 'to ' + line['arrivals'][0]['to'], font=fonts[10])
            h += 13
        h += 10

x, y, h = 410, 20, -10
had_events = False
last = (None, None)
now = datetime.datetime.now().astimezone()
for e in schedule.timeline.overlapping(now, now + datetime.timedelta(days=7)):
    had_events = True
    if isinstance(e.dtstart, datetime.datetime):
        curr = max(now, e.dtstart.astimezone()).date()
        t = e.dtstart.astimezone().strftime("%I:%M%p").lstrip('0')
        end = e.dtend.astimezone().date()
    else:
        curr = max(now.date(), e.dtstart)
        t = ''
        end = e.dtend - datetime.timedelta(days=1)  # fencepost

    if last != (curr, end):
        h += 10
        dt = curr.strftime("%a, %b %d")
        if curr.month != end.month:
            dt += ' - ' + end.strftime("%b %d")
        elif curr != end:
            dt += ' - ' + end.strftime("%d")
        d.text((x, y + h), dt, font=fonts[30])
        h += 31
        d.line([(x, y + h), (x + W, y + h)], width=2)
        h += 2
    last = (curr, end)
    d.text((x + 10, y + h), e.summary, font=fonts[20])
    d.text((x + 350, y + h), t, anchor='ra', font=fonts[20])
    h += 21

if last is None:
    d.text((x, y + h), "Nothing scheduled!", font=fonts[20])

buffer = io.BytesIO()
im.save(buffer, format="bmp")
buffer.seek(0)

conn = swiftclient.client.Connection(
    os.environ['ST_AUTH'],
    os.environ['ST_USER'],
    os.environ['ST_KEY'],
)
conn.put_object('public', 'now.bmp', buffer, headers={'Refresh': '30'})
