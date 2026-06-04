"""
Python vulnerable dependencies sample.
CVEs present: Django 2.2.0, Pillow 8.1.0, requests 2.19.1, cryptography 2.2.2
"""
import django
import requests
from PIL import Image
from cryptography.fernet import Fernet

def fetch_url(url):
    # CVE-2018-18074: requests leaks auth headers on redirect
    return requests.get(url, auth=("user", "pass"))

def resize_image(path):
    # CVE-2021-34552: Pillow heap buffer overflow via crafted image
    return Image.open(path).resize((100, 100))
