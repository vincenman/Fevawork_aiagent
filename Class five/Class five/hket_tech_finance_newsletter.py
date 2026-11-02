"""
HKET News Newsletter Generator
===============================
Fetches news articles from HKET (Hong Kong Economic Times) for multiple categories
(tech and finance), generates AI-powered summaries, and outputs formatted
newsletters in .txt format — one file per category.

Usage:
    python hket_tech_newsletter.py

Requirements:
    - playwright, openai, python-dotenv (see requirements.txt)
    - .env file with OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL
    - Chromium browser installed: playwright install chromium
"""

import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------------------
# Configuration — loaded from .env and constants
# ---------------------------------------------------------------------------

# Load API keys from .env file (same approach as demo_crawl4ai_comments.ipynb)
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path, override=True)

# Define news categories: each has a name, listing URL, output filename, and
# a label used in the LLM summarization prompt
CATEGORIES = [
    {
        "name": "科技",
        "label": "科技新聞",
        "url": "https://inews.hket.com/sran010/%E7%A7%91%E6%8A%80?mtc=80042",
        "output_file": "hket_tech_newsletter.txt",
        # Tech listing page loads fine with networkidle
        "wait_until": "networkidle",
    },
    {
        "name": "財經",
        "label": "財經新聞",
        "url": "https://inews.hket.com/sran009/%E5%8D%B3%E5%B8%82%E8%B2%A1%E7%B6%93?mtc=b0101",
        "output_file": "hket_finance_newsletter.txt",
        # Finance listing page has persistent network activity; use domcontentloaded
        "wait_until": "domcontentloaded",
    },
]

# Output directory
OUTPUT_DIR = Path(__file__).parent / "output"

# Browser settings (matching the Playwright demo notebook pattern)
HEADLESS = True
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Maximum number of articles to process per category (set to 0 for no limit)
MAX_ARTICLES = 0


# ---------------------------------------------------------------------------
# Step 1: Fetch article links from the listing page using Playwright
# ---------------------------------------------------------------------------

def fetch_article_links(url: str, wait_until: str = "networkidle") -> list[dict]:
    """
    Use Playwright (sync API) to load an HKET listing page and extract
    unique article links. Filters out non-article links (ads, event pages, etc.)
    by checking that the href contains '/article/' and the link text is meaningful.

    Args:
        url: The listing page URL.
        wait_until: Playwright wait strategy — "networkidle" for pages that
                    finish loading, "domcontentloaded" for pages with persistent
                    network activity (e.g. finance page with live tickers).

    Returns a list of dicts with 'title' and 'url' keys.
    """
    print(f"  Loading listing page: {url}")

    with sync_playwright() as p:
        # Launch a headless Chromium browser
        browser = p.chromium.launch(headless=HEADLESS)
        # Create a browser context with locale and user-agent (matching demo pattern)
        context = browser.new_context(
            locale="zh-HK",
            viewport={"width": 1440, "height": 900},
            user_agent=USER_AGENT,
        )
        page = context.new_page()

        try:
            # Navigate to the listing page with the appropriate wait strategy
            page.goto(url, wait_until=wait_until, timeout=60000)
            # Extra wait to ensure dynamic content has loaded
            page.wait_for_timeout(3000)

            # Find all <a> tags whose href contains '/article/' (the article URL pattern)
            link_elements = page.query_selector_all('a[href*="/article/"]')

            seen_urls = set()
            articles = []

            for link in link_elements:
                href = (link.get_attribute("href") or "").strip()
                text = (link.inner_text() or "").strip()

                # Skip links with short/no text (navigation, icons) and duplicates
                if not href or not text or len(text) < 15:
                    continue
                if href in seen_urls:
                    continue

                # Build full URL (some hrefs are relative paths starting with '/')
                full_url = f"https://inews.hket.com{href}" if href.startswith("/") else href

                # Only include actual news articles from inews.hket.com
                # (exclude event.hket.com, dynamic.hket.com, paper.hket.com promo links)
                if "inews.hket.com" not in full_url:
                    continue

                seen_urls.add(href)
                articles.append({"title": text, "url": full_url})

            print(f"  Found {len(articles)} unique article links")

        finally:
            # Always close browser resources to avoid leaks
            context.close()
            browser.close()

    return articles


# ---------------------------------------------------------------------------
# Step 2: Fetch article content from each article page
# ---------------------------------------------------------------------------

def fetch_article_content(article_url: str) -> str:
    """
    Use Playwright to load a single article page and extract the main content
    from the <article> HTML element. Returns the full article text as a string.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(
            locale="zh-HK",
            viewport={"width": 1440, "height": 900},
            user_agent=USER_AGENT,
        )
        page = context.new_page()

        try:
            page.goto(article_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2000)

            # The article body is inside an <article> HTML5 element
            article_el = page.query_selector("article")
            if not article_el:
                return ""

            # Extract all <p> paragraphs within the article, skipping short/meta lines
            paragraphs = article_el.query_selector_all("p")
            content_parts = []
            for p in paragraphs:
                text = p.inner_text().strip()
                # Skip metadata lines like "發布時間：..." and very short fragments
                if text and len(text) > 15:
                    content_parts.append(text)

            return "\n".join(content_parts)

        finally:
            context.close()
            browser.close()


# ---------------------------------------------------------------------------
# Step 3: Summarize article content using OpenRouter LLM API
# ---------------------------------------------------------------------------

def summarize_article(title: str, content: str, category_label: str = "新聞") -> str:
    """
    Use OpenRouter API (OpenAI-compatible client) to generate a concise
    Chinese-language summary of the article content.

    Args:
        title: The article title.
        content: The article body text.
        category_label: Label used in the prompt (e.g. "科技新聞", "財經新聞").

    Returns a 2-3 sentence Traditional Chinese summary string.
    """
    # Read API credentials from environment (loaded from .env)
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip()
    model = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-v4-pro").strip()

    if not api_key:
        return "[Summary skipped: OPENROUTER_API_KEY not set in .env]"

    # Truncate content to avoid exceeding token limits (keep ~3000 chars)
    truncated = content[:3000] if len(content) > 3000 else content

    # Build the summarization prompt — category_label tailors the assistant's role
    prompt = (
        f"你是一個{category_label}摘要助手。請用繁體中文，以2-3句簡潔摘要以下新聞的重點。\n\n"
        f"標題：{title}\n\n"
        f"內文：{truncated}\n\n"
        "摘要："
    )

    # Create OpenAI client pointed at OpenRouter (same pattern as demo notebook)
    client = OpenAI(api_key=api_key, base_url=base_url)

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=300,
        extra_headers={
            "HTTP-Referer": "http://localhost",
            "X-Title": "HKET Newsletter",
        },
    )

    summary = (response.choices[0].message.content or "").strip()
    return summary


# ---------------------------------------------------------------------------
# Step 4: Generate the newsletter .txt output
# ---------------------------------------------------------------------------

def generate_newsletter(articles: list[dict], category_name: str, source_url: str) -> str:
    """
    Build the final newsletter text with the format:
        Topic: <title>
        URL: <url>
        Summary: <AI-generated summary>

    Args:
        articles: List of article dicts with 'title', 'url', 'summary' keys.
        category_name: Display name for the header (e.g. "科技", "財經").
        source_url: The listing page URL for the source line.
    """
    lines = []
    lines.append("=" * 70)
    lines.append(f"HKET {category_name}新聞摘要")
    lines.append(f"生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"來源：{source_url}")
    lines.append("=" * 70)
    lines.append("")

    for i, article in enumerate(articles, 1):
        title = article["title"]
        url = article["url"]
        summary = article.get("summary", "")

        lines.append(f"【{i}】")
        lines.append(f"Topic: {title}")
        lines.append(f"URL: {url}")
        lines.append(f"Summary: {summary}")
        lines.append("")

    lines.append("=" * 70)
    lines.append("— 本摘要由 AI 自動生成，僅供參考 —")
    lines.append("=" * 70)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Process a single category: fetch links → fetch content → summarize → save
# ---------------------------------------------------------------------------

def process_category(category: dict) -> None:
    """
    Run the full pipeline for one news category:
    1. Fetch article links from the listing page.
    2. Fetch the full content of each article.
    3. Generate AI summaries via OpenRouter.
    4. Save the formatted newsletter to a .txt file.
    """
    name = category["name"]
    label = category["label"]
    url = category["url"]
    output_file = OUTPUT_DIR / category["output_file"]
    wait_until = category["wait_until"]

    print(f"\n{'─' * 50}")
    print(f"Category: {name} ({label})")
    print(f"{'─' * 50}")

    # Step 1: Fetch article links from the listing page
    articles = fetch_article_links(url, wait_until=wait_until)

    if not articles:
        print(f"  No articles found for {name}. Skipping.")
        return

    # Limit to MAX_ARTICLES to control API usage (0 = no limit)
    if MAX_ARTICLES > 0:
        articles = articles[:MAX_ARTICLES]

    # Step 2: Fetch content for each article
    print(f"  Fetching content for {len(articles)} articles...")
    for i, article in enumerate(articles):
        print(f"    [{i+1}/{len(articles)}] {article['title'][:60]}...")
        content = fetch_article_content(article["url"])
        article["content"] = content
        if not content:
            print(f"      ⚠ No content extracted")

    # Step 3: Summarize each article via LLM
    print(f"  Generating AI summaries...")
    for i, article in enumerate(articles):
        print(f"    [{i+1}/{len(articles)}] Summarizing: {article['title'][:60]}...")
        summary = summarize_article(article["title"], article.get("content", ""), label)
        article["summary"] = summary

    # Step 4: Generate and save the newsletter
    newsletter_text = generate_newsletter(articles, name, url)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file.write_text(newsletter_text, encoding="utf-8")

    print(f"  ✅ Saved: {output_file.resolve()} ({len(articles)} articles)")


# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------

def main():
    print("=" * 50)
    print("HKET News Newsletter Generator")
    print("=" * 50)

    for category in CATEGORIES:
        process_category(category)

    print(f"\n{'=' * 50}")
    print("All categories processed.")
    print(f"Output directory: {OUTPUT_DIR.resolve()}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()