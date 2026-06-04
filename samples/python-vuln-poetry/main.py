"""
Python Poetry sample — vulnerable dependencies.
CVEs: urllib3 1.26.4, setuptools 57.0.0, lxml 4.6.3, aiohttp 3.8.0
"""
import urllib3
from lxml import html
import aiohttp
import asyncio


def clean_html(content: str) -> str:
    # CVE-2021-43818: lxml cleaner XSS bypass
    doc = html.fromstring(content)
    return html.tostring(doc).decode()


async def fetch(url: str) -> str:
    # CVE-2023-37276: aiohttp HTTP request smuggling
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.text()


if __name__ == "__main__":
    # CVE-2023-43804: urllib3 leaks cookie headers
    http = urllib3.PoolManager()
    r = http.request("GET", "http://example.com")
    print(r.status)
