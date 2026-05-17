import re
import requests
import logging
from urllib.parse import quote, urlparse, parse_qs, urlencode, urlunparse

logger = logging.getLogger(__name__)

class AliExpressScraper:
    def __init__(self, scraper_api_key=None):
        self.scraper_api_key = scraper_api_key
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def is_aliexpress(self, url):
        url_lower = url.lower()
        return 'aliexpress.' in url_lower or 'a.aliexpress.' in url_lower

    def add_affiliate(self, url, ali_id):
        """Add AliExpress affiliate tracking ID to URL"""
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        # Remove existing affiliate params
        for key in list(query.keys()):
            if key in ['aff_fcid', 'aff_platform', 'sk', 'aff_trace_key']:
                del query[key]

        # Add affiliate parameters
        query['aff_fcid'] = [ali_id]
        query['aff_platform'] = ['default']
        query['aff_trace_key'] = [ali_id]
        query['sk'] = ['_dSI7LJ']
        query['terminal_id'] = ['3ac645b9bf6342ee8eb9bdd1e5e4f8a2']

        new_query = urlencode(query, doseq=True)

        new_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        ))

        return new_url

    def extract_product_id(self, url):
        """Extract AliExpress product ID from URL"""
        # Pattern 1: /item/123456789.html
        m = re.search(r'/item/(\d+)\.html', url)
        if m:
            return m.group(1)

        # Pattern 2: ?item_id=123456789
        m = re.search(r'[?&]item_id=(\d+)', url)
        if m:
            return m.group(1)

        # Pattern 3: /p/123456789
        m = re.search(r'/p/(\d+)', url)
        if m:
            return m.group(1)

        return None

    def scrape_product(self, url):
        """Scrape AliExpress product details"""
        try:
            # Method 1: Using ScraperAPI (recommended for production)
            if self.scraper_api_key:
                api_url = f"http://api.scraperapi.com?api_key={self.scraper_api_key}&url={quote(url)}&country_code=us"
                r = self.session.get(api_url, timeout=30)
                html = r.text
            else:
                # Method 2: Direct request (may be blocked)
                r = self.session.get(url, timeout=15, headers={
                    'User-Agent': 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36',
                    'Accept-Language': 'en-US,en;q=0.9'
                })
                html = r.text

            # Extract title
            title = "Unknown Product"

            # Try multiple title patterns
            title_patterns = [
                r'"subject":"([^"]+)"',
                r'"title":"([^"]+)"',
                r'<h1[^>]*class="product-title[^"]*"[^>]*>(.*?)</h1>',
                r'<meta property="og:title" content="([^"]+)"',
                r'"productTitle":"([^"]+)"'
            ]

            for p in title_patterns:
                m = re.search(p, html, re.S)
                if m:
                    title = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                    if title and len(title) > 3:
                        break

            # Extract price - try multiple patterns
            price = None
            currency = 'USD'

            price_patterns = [
                # JSON patterns
                r'"minAmount":{"value":"([0-9.]+)"',
                r'"salePrice":{"amount":"([0-9.]+)"',
                r'"price":"([0-9.,]+)"',
                r'"discountPrice":"([0-9.,]+)"',
                # HTML patterns
                r'class="price-current"[^>]*>([0-9.,]+)',
                r'class="product-price-value"[^>]*>([0-9.,]+)',
                r'data-price="([0-9.,]+)"'
            ]

            for p in price_patterns:
                m = re.search(p, html)
                if m:
                    price_str = m.group(1).replace(',', '').replace('$', '')
                    try:
                        price = float(price_str)
                        if price > 0:
                            break
                    except:
                        continue

            # Extract image
            image = None
            img_patterns = [
                r'"imagePath":"([^"]+)"',
                r'"imgUrl":"([^"]+)"',
                r'<meta property="og:image" content="([^"]+)"',
                r'"mainImage":"([^"]+)"'
            ]

            for p in img_patterns:
                m = re.search(p, html)
                if m:
                    image = m.group(1)
                    if image.startswith('//'):
                        image = 'https:' + image
                    break

            # Detect currency
            if 'USD' in html or '$' in html[:5000]:
                currency = 'USD'
            elif 'EUR' in html or '€' in html[:5000]:
                currency = 'EUR'
            elif 'GBP' in html or '£' in html[:5000]:
                currency = 'GBP'

            if price and price > 0:
                return {
                    'title': title,
                    'price': price,
                    'currency': currency,
                    'image': image,
                    'platform': 'aliexpress'
                }

            logger.warning(f"Could not extract price from {url}")
            return None

        except Exception as e:
            logger.error(f"AliExpress scrape error: {e}")
            return None
