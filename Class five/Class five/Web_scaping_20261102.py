"""Web scraping example with exactly 5 topics — top 10 links + insights + Telegram.

This script demonstrates a simple web scraping workflow using:
1. HTTP requests
2. HTML parsing
3. Link extraction
4. Dynamic content handling
5. Saving the extracted data

It is a rewritten version of the earlier HKET newsletter scraper, simplified to
focus on five topic areas only. For each topic the top 10 article links are
saved, a keyword-based insight section is appended to the text output, and
the results are sent to a Telegram chat.
"""

from __future__ import annotations

import asyncio
import csv
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import telegram


TOPICS: List[Dict[str, str]] = [
    {
        "name": "Technology",
        "url": "https://inews.hket.com/sran010/%E7%A7%91%E6%8A%80?mtc=80042",
    },
    {
        "name": "Finance",
        "url": "https://inews.hket.com/sran009/%E5%8D%B3%E5%B8%82%E8%B2%A1%E7%B6%93?mtc=b0101",
    },
    {
        "name": "Business",
        "url": "https://inews.hket.com/sran013/%E5%95%86%E6%A5%AD?mtc=80042",
    },
    {
        "name": "Lifestyle",
        "url": "https://inews.hket.com/sran011/%E7%94%9F%E6%B4%BB?mtc=80042",
    },
    {
        "name": "International",
        "url": "https://inews.hket.com/sran012/%E5%9C%8B%E9%9A%9B?mtc=80042",
    },
]

OUTPUT_DIR = Path(__file__).resolve().parent

# ── Telegram configuration (loaded from .env) ──────────────────────────────
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path, override=True)

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_KEY", "").strip().strip("'\"")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "").strip().strip("'\"")

# ── Stop words (Chinese + English) to exclude from keyword analysis ─────────
STOP_WORDS: set[str] = {
    # Chinese
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "個", "上", "也", "很", "到", "說", "要", "去", "你", "會", "著",
    "沒有", "看", "好", "自己", "這", "他", "她", "它", "們", "與", "及",
    "或", "為", "以", "被", "讓", "從", "對", "等", "能", "可", "將",
    "其", "中", "而", "但", "所", "如", "更", "最", "之", "年", "月", "日",
    "新", "大", "小", "多", "後", "前", "時", "來", "還", "已", "並",
    "於", "向", "把", "被", "讓", "用", "做", "作", "過", "出", "開",
    "第", "兩", "三", "四", "五", "六", "七", "八", "九", "十",
    # English
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "with",
    "and", "or", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "can",
    "could", "should", "may", "might", "shall", "this", "that", "these",
    "those", "it", "its", "they", "them", "their", "we", "us", "our",
    "you", "your", "he", "she", "him", "her", "his", "not", "no",
    "but", "from", "as", "by", "up", "down", "out", "off", "over",
    "just", "also", "very", "too", "so", "if", "then", "than",
}


# ═══════════════════════════════════════════════════════════════════════════
#  Core scraping helpers (using Playwright for JS-rendered pages)
# ═══════════════════════════════════════════════════════════════════════════

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def fetch_articles_from_url(url: str) -> List[Dict[str, str]]:
    """Use Playwright to load an HKET listing page and extract article links."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="zh-HK",
            viewport={"width": 1440, "height": 900},
            user_agent=USER_AGENT,
        )
        page = context.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)

            # Debug: print page title and some text to verify content loaded
            print(f"  Page title: {page.title()[:100]}")

            # Try multiple selectors for article links
            articles = []
            seen_urls = set()

            # Method 1: Look for links containing /article/
            link_elements = page.query_selector_all('a[href*="/article/"]')
            print(f"  Found {len(link_elements)} links with /article/")

            for link in link_elements:
                href = (link.get_attribute("href") or "").strip()
                text = (link.inner_text() or "").strip()

                if not href or not text or len(text) < 15:
                    continue
                if href in seen_urls:
                    continue

                full_url = f"https://inews.hket.com{href}" if href.startswith("/") else href
                if "inews.hket.com" not in full_url:
                    continue

                seen_urls.add(href)
                articles.append({"title": text, "url": full_url})

            # Method 2: If no articles found, try looking for news-item links
            if not articles:
                print("  Trying alternative selectors...")
                for selector in ["a.gtm-link", "a[class*='title']", "h3 a", "h2 a", ".news-title a"]:
                    alt_links = page.query_selector_all(selector)
                    if alt_links:
                        print(f"  Selector '{selector}' found {len(alt_links)} links")
                        for link in alt_links:
                            href = (link.get_attribute("href") or "").strip()
                            text = (link.inner_text() or "").strip()
                            if href and text and len(text) > 10 and href not in seen_urls:
                                full_url = f"https://inews.hket.com{href}" if href.startswith("/") else href
                                seen_urls.add(href)
                                articles.append({"title": text, "url": full_url})

            return articles

        finally:
            context.close()
            browser.close()


# ═══════════════════════════════════════════════════════════════════════════
#  Keyword analysis & insight generation
# ═══════════════════════════════════════════════════════════════════════════

def tokenize(text: str) -> List[str]:
    """Split text into meaningful tokens (Chinese characters + English words)."""
    tokens: List[str] = []
    for match in re.finditer(r"[\u4e00-\u9fff]+|[a-zA-Z]+", text):
        token = match.group().lower()
        if token not in STOP_WORDS and len(token) >= 2:
            tokens.append(token)
    return tokens


def generate_insights(topic_name: str, articles: List[Dict[str, str]]) -> str:
    """Analyse the top 10 article titles and return a human-readable insight block."""
    if not articles:
        return ""

    titles = [a["title"] for a in articles]

    # ── Count keyword frequency across all titles ──────────────────────
    all_tokens: List[str] = []
    for t in titles:
        all_tokens.extend(tokenize(t))
    keyword_counts = Counter(all_tokens)
    top_keywords = keyword_counts.most_common(10)

    # ── Detect brand / company mentions ────────────────────────────────
    brand_pattern = re.compile(
        r"Apple|iPhone|iPad|Mac|Meta|Google|Microsoft|Amazon|Samsung|"
        r"OpenAI|ChatGPT|Threads|Instagram|WhatsApp|Facebook|Reddit|"
        r"Cloudflare|Jabra|Sanrio|Momax|HKET|HKCERT|國泰|香港|中國|美國",
        re.IGNORECASE,
    )
    brand_mentions: Counter[str] = Counter()
    for t in titles:
        for m in brand_pattern.finditer(t):
            brand_mentions[m.group()] += 1

    # ── Detect topic categories ────────────────────────────────────────
    topic_keywords: dict[str, list[str]] = {
        "AI / Technology": ["ai", "人工智能", "chatgpt", "llm", "model", "robot", "自動化"],
        "Cybersecurity": ["安全", "漏洞", "hack", "attack", "privacy", "保安", "網絡"],
        "Finance / Economy": ["股", "價", "經濟", "投資", "market", "stock", "fund", "銀行"],
        "Product Launch": ["推出", "登場", "上市", "launch", "release", "新", "發表"],
        "Social Media": ["threads", "instagram", "facebook", "whatsapp", "social", "reddit"],
    }
    topic_hits: Counter[str] = Counter()
    for t in titles:
        t_lower = t.lower()
        for cat, kws in topic_keywords.items():
            if any(kw in t_lower for kw in kws):
                topic_hits[cat] += 1

    # ── Build the insight text ─────────────────────────────────────────
    lines: List[str] = []
    lines.append("")
    lines.append("=" * 70)
    lines.append("INSIGHTS -- Top 10 Article Analysis")
    lines.append("=" * 70)
    lines.append("")

    # 1. Overview
    lines.append("[Overview]")
    lines.append(f"   Category        : {topic_name}")
    lines.append(f"   Articles fetched : {len(articles)} (showing top 10)")
    lines.append(f"   Generated at    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    # 2. Top keywords
    lines.append("[Top Keywords in Titles]")
    for kw, count in top_keywords:
        bar = "#" * count
        lines.append(f"   {kw:>12}  {bar}  ({count})")
    lines.append("")

    # 3. Brand / company mentions
    if brand_mentions:
        lines.append("[Brand / Company Mentions]")
        for brand, count in brand_mentions.most_common(8):
            lines.append(f"   {brand:>14}  {'#' * count}  ({count})")
        lines.append("")

    # 4. Topic distribution
    if topic_hits:
        lines.append("[Topic Distribution]")
        for cat, count in topic_hits.most_common():
            bar = "#" * count
            lines.append(f"   {cat:>22}  {bar}  ({count})")
        lines.append("")

    # 5. Narrative summary
    lines.append("[Summary]")
    if top_keywords:
        top_3 = [kw for kw, _ in top_keywords[:3]]
        lines.append(f"   The top 10 articles in [{topic_name}] are dominated by "
                     f"keywords such as")
        lines.append(f"   [{', '.join(top_3)}], suggesting a focus on "
                     f"recent product launches,")
        lines.append(f"   corporate announcements, and technology trends relevant to "
                     f"Hong Kong readers.")
    lines.append("")

    lines.append("=" * 70)
    lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
#  Output writers
# ═══════════════════════════════════════════════════════════════════════════

TOP_N = 10


def write_csv(topic_name: str, articles: List[Dict[str, str]]) -> None:
    """Save the top 10 articles to a CSV file."""
    file_path = OUTPUT_DIR / f"{topic_name.lower().replace(' ', '_')}_articles.csv"
    top10 = articles[:TOP_N]
    with file_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=["title", "url"])
        writer.writeheader()
        writer.writerows(top10)

    print(f"Saved {len(top10)} entries to: {file_path}")


def write_text(topic_name: str, articles: List[Dict[str, str]]) -> None:
    """Save the top 10 articles + insights to a text file."""
    file_path = OUTPUT_DIR / f"{topic_name.lower().replace(' ', '_')}_articles.txt"
    top10 = articles[:TOP_N]

    lines: List[str] = [
        f"Topic: {topic_name}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Total articles found: {len(articles)} (showing top {TOP_N})",
        "",
    ]

    for idx, article in enumerate(top10, start=1):
        lines.append(f"{idx:>2}. {article['title']}")
        lines.append(f"    URL: {article['url']}")

    # Append insights
    lines.append(generate_insights(topic_name, top10))

    file_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Text file saved: {file_path}")


# ═══════════════════════════════════════════════════════════════════════════
#  Telegram sender
# ═══════════════════════════════════════════════════════════════════════════

async def send_to_telegram(topic_name: str) -> None:
    """Send the text file for one topic to the configured Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("  [!] Telegram credentials missing -- skipping Telegram send.")
        return

    file_path = OUTPUT_DIR / f"{topic_name.lower().replace(' ', '_')}_articles.txt"
    if not file_path.exists():
        print(f"  [!] File not found: {file_path}")
        return

    bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
    chat_id = TELEGRAM_CHAT_ID

    try:
        # Send a short caption first
        caption = (
            f"HKET News -- {topic_name}\n"
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"Top 10 articles + insights"
        )
        await bot.send_message(chat_id=chat_id, text=caption, read_timeout=15)

        # Send the text file as a document
        with open(file_path, "rb") as f:
            await bot.send_document(
                chat_id=chat_id,
                document=f,
                filename=file_path.name,
                read_timeout=30,
            )

        print(f"  [OK] Sent to Telegram: {file_path.name}")
    except Exception as exc:
        print(f"  [X] Failed to send to Telegram ({topic_name}): {exc}")


async def send_all_to_telegram() -> None:
    """Send all 5 topic files to Telegram."""
    print("\n" + "=" * 50)
    print("Sending files to Telegram...")
    print("=" * 50)

    for topic in TOPICS:
        await send_to_telegram(topic["name"])

    print("All files sent to Telegram.")


# ═══════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    """Collect data for the 5 topics and save the output."""
    print("Starting web scraping tasks...")

    for topic in TOPICS:
            topic_name = topic["name"]
            url = topic["url"]
            print(f"\n=== {topic_name} ===")
            print(f"Fetching: {url}")

            try:
                articles = fetch_articles_from_url(url)
                print(f"Found {len(articles)} article(s).")

                if articles:
                    write_csv(topic_name, articles)
                    write_text(topic_name, articles)
                else:
                    print("No valid articles found for this topic.")

            except Exception as exc:
                print(f"Error loading {topic_name}: {exc}")

    print("\nDone. All 5 topics processed.")

    # Send results to Telegram
    asyncio.run(send_all_to_telegram())


if __name__ == "__main__":
    main()