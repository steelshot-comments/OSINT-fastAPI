import re
import requests
from bs4 import BeautifulSoup

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

def check_google_result(url):
    try:
        response = requests.get(url, headers=headers, timeout=5)
        html = response.text.lower()
        # Check for phrases that imply no result
        if ("did not match any documents" in html or
            "your search - " in html and " - did not match any documents" in html):
            return False
        soup = BeautifulSoup(html, "html.parser")
        # Check if any result links exist
        for a in soup.find_all("a"):
            href = a.get("href", "")
            if "/url?q=" in href:
                return True
        return False
    except Exception as e:
        return False