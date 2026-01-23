from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import logging
import os
import time
from dotenv import load_dotenv
from curl_cffi import requests as cureq
from bs4 import BeautifulSoup

load_dotenv()

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv('GROQ_API_KEY')

def extract_wattpad_text(url: str) -> str:
    try:
        logger.info(f"Stealth-fetching URL: {url}")
        
        # This impersonates a real Chrome browser at the network level
        # Uses very little RAM compared to Playwright
        r = cureq.get(url, impersonate="chrome", timeout=30)
        
        if r.status_code != 200:
            raise Exception(f"Wattpad returned status {r.status_code}")

        soup = BeautifulSoup(r.text, 'html.parser')
        text_parts = []

        # --- YOUR EXACT SCRAPING LOGIC REBUILT FOR BEAUTIFULSOUP ---
        
        # 1. data-p-id (The standard Wattpad story format)
        elements = soup.find_all(attrs={"data-p-id": True})
        for elem in elements:
            t = elem.get_text().strip()
            if t:
                text_parts.append(t)

        # 2. Fallback: article/main
        if not text_parts:
            container = soup.find(['article', 'main']) or soup.find(attrs={"role": "main"})
            if container:
                for p in container.find_all('p'):
                    t = p.get_text().strip()
                    if len(t) > 20:
                        text_parts.append(t)

        # 3. Fallback: Content Selectors
        if not text_parts:
            selectors = ['.part-content', '.story-content', '.chapter-content']
            for selector in selectors:
                container = soup.select_one(selector)
                if container:
                    for p in container.find_all('p'):
                        t = p.get_text().strip()
                        if len(t) > 20:
                            text_parts.append(t)
                    if text_parts: break

        # 4. Last Resort: All long paragraphs
        if not text_parts:
            for p in soup.find_all('p'):
                t = p.get_text().strip()
                if len(t) > 30:
                    if not any(x in t.lower() for x in ['advertisement', 'sponsored', 'follow', 'share', 'vote', 'comment']):
                        text_parts.append(t)

        if text_parts:
            return '\n\n'.join(text_parts)
        
        # If all fails, just grab the body text
        return soup.get_text(separator='\n\n', strip=True)

    except Exception as e:
        logger.error(f"Scraper error: {str(e)}")
        raise

def translate_to_burmese(text: str) -> str:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY missing")

    chunks = [text[i:i+2500] for i in range(0, len(text), 2500)]
    translations = []

    for chunk in chunks:
        response = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {GROQ_API_KEY}'},
            json={
                'model': 'mixtral-8x7b-32768',
                'messages': [
                    {'role': 'system', 'content': 'Translate to Burmese. Provide only translation.'},
                    {'role': 'user', 'content': chunk}
                ],
                'temperature': 0.3
            },
            timeout=60
        )
        if response.status_code == 200:
            translations.append(response.json()['choices'][0]['message']['content'])
        time.sleep(0.5)

    return '\n\n'.join(translations)

@app.route('/extract', methods=['POST'])
def extract_only():
    try:
        url = request.json.get('url')
        if not url or 'wattpad.com' not in url:
            return jsonify({'error': 'Invalid URL'}), 400
        
        text = extract_wattpad_text(url)
        return jsonify({'success': True, 'text': text, 'url': url})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/translate', methods=['POST'])
def translate_only():
    try:
        text = request.json.get('text')
        if not text: return jsonify({'error': 'No text'}), 400
        return jsonify({'success': True, 'translation': translate_to_burmese(text)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
