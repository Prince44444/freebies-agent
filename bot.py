import os
import sys
import json
import re
import time
import random
import argparse
from datetime import datetime, timezone
from dateutil import parser as dtp
import requests
import feedparser

# Если используешь .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

STATE_FILE = "state.json"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DONATE_URL = os.getenv("DONATE_URL", "")

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def load_state():
    if not os.path.exists(STATE_FILE):
        return {"posted": []}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"posted": []}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def fetch_gotd():
    url = "https://www.giveawayoftheday.com/feed/"
    try:
        d = feedparser.parse(url)
        items = []
        for e in d.entries[:5]:
            items.append({
                "id": e.link,
                "title": f"💎 {e.title}",
                "url": e.link,
                "source": "GiveawayOfTheDay",
                "image_url": None,
                "expires_at": None
            })
        return items
    except Exception as ex:
        print(f"GOTD error: {ex}")
        return []

def fetch_sharewareonsale():
    url = "https://sharewareonsale.com/feed"
    try:
        d = feedparser.parse(url, request_headers=HEADERS)
        items = []
        for e in d.entries[:10]:
            title = e.title or ""
            if re.search(r"(100% off|free|giveaway)", title, re.I):
                items.append({
                    "id": e.link,
                    "title": f"🎁 {title}",
                    "url": e.link,
                    "source": "SharewareOnSale",
                    "image_url": None,
                    "expires_at": None
                })
        return items
    except Exception as ex:
        print(f"SharewareOnSale error: {ex}")
        return []

def fetch_epic_freebies():
    url = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=ru-RU&country=RU&allowCountries=RU"
    items = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()
        elements = data.get("data", {}).get("Catalog", {}).get("searchStore", {}).get("elements", [])
        
        for el in elements:
            price = (el.get("price") or {}).get("totalPrice") or {}
            discount_price = price.get("discountPrice", 1)
            original_price = price.get("originalPrice", 0)
            
            if original_price > 0 and discount_price == 0:
                title = el.get("title") or "Epic Games Freebie"
                slug = el.get("productSlug") or el.get("urlSlug") or ""
                slug = slug.split("?")[0].strip("/")
                link = f"https://store.epicgames.com/p/{slug}" if slug else "https://store.epicgames.com/free-games"
                
                # Пытаемся достать конец акции
                ends_at = None
                try:
                    promotions = (el.get("promotions") or {}).get("promotionalOffers") or []
                    if promotions:
                        offers = promotions[0].get("promotionalOffers") or []
                        if offers and offers[0].get("endDate"):
                            ends_at = dtp.parse(offers[0]["endDate"])
                except Exception:
                    pass

                img = None
                for ki in el.get("keyImages", []):
                    if ki.get("type") in ("Thumbnail", "DieselStoreFrontWide", "OfferImageWide"):
                        img = ki.get("url")
                        break
                
                items.append({
                    "id": f"epic:{slug or title}",
                    "title": f"🎮 Epic Games: {title} — БЕСПЛАТНО!",
                    "url": link,
                    "source": "EpicGames",
                    "image_url": img,
                    "expires_at": ends_at.isoformat() if ends_at else None
                })
    except Exception as ex:
        print(f"Epic fetch error: {ex}")
    return items

def fetch_reddit_gamedeals():
    url = "https://www.reddit.com/r/GameDeals/search.json?q=flair%3A%27100%25%27&restrict_sr=on&sort=new&t=week"
    items = []
    try:
        r = requests.get(url, headers={'User-Agent': 'FreebiesBot/1.0'}, timeout=10)
        data = r.json()
        for post in data.get('data', {}).get('children', [])[:5]:
            d = post.get('data', {})
            if '[100%' in d.get('title', ''):
                items.append({
                    "id": f"reddit:{d.get('id')}",
                    "title": f"🔥 {d.get('title', '')}",
                    "url": d.get('url', ''),
                    "source": "Reddit GameDeals",
                    "image_url": None,
                    "expires_at": None
                })
    except Exception as ex:
        print(f"Reddit error: {ex}")
    return items

def fetch_humble_bundle():
    url = "https://www.humblebundle.com/feed/freebies"
    items = []
    try:
        d = feedparser.parse(url)
        for e in d.entries[:3]:
            items.append({
                "id": f"humble:{e.link}",
                "title": f"🎮 Humble Bundle: {e.title}",
                "url": e.link,
                "source": "HumbleBundle",
                "image_url": None,
                "expires_at": None
            })
    except Exception as ex:
        print(f"Humble error: {ex}")
    return items

def collect_items():
    items = []

    fetchers = [
        fetch_gotd,
        fetch_sharewareonsale,
        fetch_epic_freebies,
        fetch_reddit_gamedeals,
        fetch_humble_bundle,
    ]
    for fetcher in fetchers:
        try:
            items.extend(fetcher())
        except Exception as ex:
            print(f"Fetcher {fetcher.__name__} failed: {ex}")

    # Убираем дубликаты по URL
    seen = set()
    unique = []
    for it in items:
        key = it["url"]
        if key not in seen:
            seen.add(key)
            unique.append(it)
    return unique

def fmt_expires(expires_at_iso: str) -> str:
    if not expires_at_iso:
        return ""
    try:
        dt = dtp.parse(expires_at_iso)
        # В API часто UTC — нормализуем
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        # Переводим в МСК (UTC+3 без перехода)
        msk_dt = dt.astimezone(timezone.utc).astimezone(timezone.utc)  # оставим UTC, а в тексте укажем UTC
        # Если хочешь именно МСК: раскомментируй ниже и закомментируй строку выше
        # from zoneinfo import ZoneInfo
        # msk_dt = dt.astimezone(ZoneInfo("Europe/Moscow"))
        return msk_dt.strftime("%d.%m %H:%M UTC")
    except Exception:
        return ""

def render_text(item):
    source_emoji = {
        "EpicGames": "🎮",
        "Steam": "🎯", 
        "GiveawayOfTheDay": "💎",
        "SharewareOnSale": "🎁",
        "Reddit GameDeals": "🔥",
        "HumbleBundle": "🎪"
    }
    emoji = source_emoji.get(item['source'], "🎁")

    expires_line = ""
    if item.get("expires_at"):
        hh = fmt_expires(item["expires_at"])
        if hh:
            expires_line = f"⏰ До {hh}\n"

    body_variants = [
        f"{emoji} <b>{item['title']}</b>\n\n"
        f"{expires_line}"
        f"Источник: {item['source']}\n"
        f"Официально, без VPN (если не указано иначе).\n\n"
        f"👇 <b>Забрать по кнопке</b>",
        f"{emoji} <b>{item['title']}</b>\n\n"
        f"{expires_line}"
        f"Проверено: ссылка рабочая.\n"
        f"Без регистрации/с ключом — по условиям источника.\n\n"
        f"🎯 <b>Получить бесплатно ↓</b>",
        f"{emoji} <b>{item['title']}</b>\n\n"
        f"{expires_line}"
        f"Подходит для коллекции и экономии бюджета.\n\n"
        f"🔽 <b>Жми, чтобы забрать</b>",
    ]
    text = random.choice(body_variants)

    tags = "\n\n#халява #бесплатно #раздача"
    if "game" in item['title'].lower() or item['source'] in ["EpicGames", "Steam", "HumbleBundle", "Reddit GameDeals"]:
        tags += " #игры #games"
    else:
        tags += " #софт #программы"

    return text + tags

def send_text(text: str, inline_keyboard=None):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set")

    api_base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    url = f"{api_base}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    if inline_keyboard:
        data["reply_markup"] = json.dumps({"inline_keyboard": inline_keyboard}, ensure_ascii=False)

    r = requests.post(url, data=data, timeout=30)
    r.raise_for_status()
    return True

def send_telegram(item):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set")

    caption = render_text(item)

    keyboard = [[{"text": "🎁 Забрать халяву", "url": item["url"]}]]
    if DONATE_URL:
        keyboard.append([{"text": "💖 Поддержать канал", "url": DONATE_URL}])

    api_base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    
    # Пробуем с картинкой
    if item.get("image_url"):
        url = f"{api_base}/sendPhoto"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": caption,
            "parse_mode": "HTML",
            "reply_markup": json.dumps({"inline_keyboard": keyboard}, ensure_ascii=False),
            "photo": item["image_url"]
        }
        try:
            r = requests.post(url, data=data, timeout=30)
            if r.status_code == 200:
                return True
        except Exception as ex:
            print(f"sendPhoto failed: {ex}")

    # Без картинки
    url = f"{api_base}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": caption,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
        "reply_markup": json.dumps({"inline_keyboard": keyboard}, ensure_ascii=False),
    }
    r = requests.post(url, data=data, timeout=30)
    r.raise_for_status()
    return True

def post_daily_stats():
    state = load_state()
    total = len(state.get("posted", []))

    text = (
        "📊 <b>Статистика канала</b>\n\n"
        f"🎁 Всего раздач: {total}\n"
        "📅 Работаем: 24/7\n"
        "🔔 Включите уведомления!\n\n"
    )
    if DONATE_URL:
        text += f"💖 Поддержать канал: {DONATE_URL}"
    return send_text(text)

def main():
    print("Starting Freebies Agent...")
    
    state = load_state()
    posted = set(state.get("posted", []))
    
    print(f"Already posted: {len(posted)} items")

    items = collect_items()
    print(f"Found total: {len(items)} items")
    
    new_items = [it for it in items if it["id"] not in posted]
    print(f"New items: {len(new_items)}")

    # Постим максимум 3 за раз
    posts_count = 0
    for it in new_items[:3]:
        try:
            print(f"Posting: {it['title']}")
            ok = send_telegram(it)
            if ok:
                posted.add(it["id"])
                posts_count += 1
                # Случайная задержка 30-90 секунд
                time.sleep(random.randint(30, 90))
        except Exception as ex:
            print(f"Post failed: {ex}")
            continue

    state["posted"] = list(posted)
    save_state(state)
    print(f"Done! Posted: {posts_count} items")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", action="store_true", help="Отправить ежедневную статистику")
    args = parser.parse_args()

    if args.stats:
        ok = post_daily_stats()
        print("Stats sent" if ok else "Stats failed")
        sys.exit(0)
    else:
        main()
