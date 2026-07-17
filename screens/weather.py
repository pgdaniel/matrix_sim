"""Weather screen: current temperature + condition icon, refetched on a timer."""

import math
import threading

import requests
from PIL import Image, ImageDraw, ImageFont

from .base import FONT_PATH, HEIGHT, Screen, WIDTH

SUN_COLOR = (255, 190, 0)
CLOUD_COLOR = (190, 190, 200)
DARK_CLOUD_COLOR = (110, 110, 125)
RAIN_COLOR = (60, 140, 255)
SNOW_COLOR = (255, 255, 255)
BOLT_COLOR = (255, 225, 0)
FOG_COLOR = (150, 150, 160)
TEXT_COLOR = (255, 255, 255)

# WMO weather codes: https://open-meteo.com/en/docs
_CODE_TO_ICON = {
    0: "sun",
    1: "partly_cloudy", 2: "partly_cloudy",
    3: "cloudy",
    45: "fog", 48: "fog",
    51: "rain", 53: "rain", 55: "rain", 56: "rain", 57: "rain",
    61: "rain", 63: "rain", 65: "rain", 66: "rain", 67: "rain",
    80: "rain", 81: "rain", 82: "rain",
    71: "snow", 73: "snow", 75: "snow", 77: "snow", 85: "snow", 86: "snow",
    95: "storm", 96: "storm", 99: "storm",
}


def icon_for_code(code):
    return _CODE_TO_ICON.get(code, "cloudy")


def get_location():
    try:
        resp = requests.get("http://ip-api.com/json/", timeout=5).json()
        return resp["lat"], resp["lon"], resp.get("city", "")
    except Exception:
        # Fallback if geolocation fails: New York City
        return 40.7128, -74.0060, "New York"


def get_weather(lat, lon):
    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,weather_code",
            "temperature_unit": "fahrenheit",
        },
        timeout=10,
    ).json()
    current = resp["current"]
    return current["temperature_2m"], icon_for_code(current["weather_code"])


def get_daily_range(lat, lon):
    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min",
            "temperature_unit": "fahrenheit",
            "timezone": "auto",
        },
        timeout=10,
    ).json()
    daily = resp["daily"]
    return daily["temperature_2m_min"][0], daily["temperature_2m_max"][0]


def draw_sun(draw, cx, cy, r):
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=SUN_COLOR)
    for angle in range(0, 360, 45):
        rad = math.radians(angle)
        x1 = cx + (r + 2) * math.cos(rad)
        y1 = cy + (r + 2) * math.sin(rad)
        x2 = cx + (r + 5) * math.cos(rad)
        y2 = cy + (r + 5) * math.sin(rad)
        draw.line((x1, y1, x2, y2), fill=SUN_COLOR, width=1)


def draw_cloud(draw, x0, y0, x1, y1, color):
    w = x1 - x0
    h = y1 - y0
    draw.rectangle((x0, y0 + h * 0.45, x1, y1), fill=color)
    draw.ellipse((x0, y0 + h * 0.10, x0 + w * 0.55, y0 + h * 0.70), fill=color)
    draw.ellipse((x0 + w * 0.35, y0, x0 + w * 0.95, y0 + h * 0.60), fill=color)
    draw.ellipse((x0 + w * 0.10, y0 + h * 0.25, x0 + w * 0.70, y0 + h * 0.80), fill=color)


def draw_icon(draw, kind, x0, y0, x1, y1):
    w = x1 - x0
    h = y1 - y0
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2

    if kind == "sun":
        draw_sun(draw, cx, cy, min(w, h) / 2 - 5)
    elif kind == "partly_cloudy":
        draw_sun(draw, x0 + w * 0.35, y0 + h * 0.30, min(w, h) / 6)
        draw_cloud(draw, x0 + w * 0.05, y0 + h * 0.35, x1, y1, CLOUD_COLOR)
    elif kind == "cloudy":
        draw_cloud(draw, x0, y0 + h * 0.10, x1, y1, DARK_CLOUD_COLOR)
    elif kind == "fog":
        step = max(2, int(h // 5))
        for yy in range(int(y0 + h * 0.15), int(y1), step):
            draw.line((x0, yy, x1, yy), fill=FOG_COLOR, width=2)
    elif kind == "rain":
        draw_cloud(draw, x0, y0, x1, y0 + h * 0.65, DARK_CLOUD_COLOR)
        for i in range(3):
            dx = x0 + w * (0.2 + 0.3 * i)
            draw.line((dx, y0 + h * 0.75, dx - 2, y1), fill=RAIN_COLOR, width=2)
    elif kind == "snow":
        draw_cloud(draw, x0, y0, x1, y0 + h * 0.60, DARK_CLOUD_COLOR)
        for i in range(3):
            dx = x0 + w * (0.2 + 0.3 * i)
            dy = y0 + h * 0.85
            draw.line((dx - 2, dy, dx + 2, dy), fill=SNOW_COLOR, width=1)
            draw.line((dx, dy - 2, dx, dy + 2), fill=SNOW_COLOR, width=1)
    elif kind == "storm":
        draw_cloud(draw, x0, y0, x1, y0 + h * 0.60, DARK_CLOUD_COLOR)
        draw.polygon(
            [(cx + 2, y0 + h * 0.55), (cx - 4, y0 + h * 0.82),
             (cx, y0 + h * 0.82), (cx - 3, y1)],
            fill=BOLT_COLOR,
        )


class WeatherScreen(Screen):
    name = "weather"

    def __init__(self, latitude=None, longitude=None, refresh_minutes=10):
        self.latitude = latitude
        self.longitude = longitude
        self.refresh_minutes = refresh_minutes
        self.city = None
        self.font = ImageFont.truetype(FONT_PATH, 16)
        self._lock = threading.Lock()
        self._temp_f = None
        self._icon_kind = None

    def start(self, stop_event, notify_update):
        if self.latitude is None or self.longitude is None:
            self.latitude, self.longitude, self.city = get_location()
        else:
            self.city = f"{self.latitude:.2f}, {self.longitude:.2f}"
        print(f"Location: {self.city} ({self.latitude:.4f}, {self.longitude:.4f})")

        def updater():
            while not stop_event.is_set():
                try:
                    temp_f, icon_kind = get_weather(self.latitude, self.longitude)
                    print(f"{self.city}: {temp_f:.0f}F, {icon_kind}")
                    with self._lock:
                        self._temp_f = temp_f
                        self._icon_kind = icon_kind
                    notify_update()
                except Exception as e:
                    print(f"Weather fetch failed: {e}")
                stop_event.wait(max(1, self.refresh_minutes) * 60)

        threading.Thread(target=updater, daemon=True).start()

    def render(self):
        with self._lock:
            temp_f, icon_kind = self._temp_f, self._icon_kind
        if temp_f is None:
            return None

        img = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        icon_size = HEIGHT
        draw_icon(draw, icon_kind, 1, 0, icon_size - 1, icon_size)

        text = f"{round(temp_f)}F"
        x0, y0, x1, y1 = self.font.getbbox(text)
        tw, th = x1 - x0, y1 - y0
        tx = icon_size + max(0, (WIDTH - icon_size - tw) // 2)
        ty = (HEIGHT - th) // 2 - y0
        draw.text((tx, ty), text, font=self.font, fill=TEXT_COLOR)

        return img
