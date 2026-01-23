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
# IMPORTANT: Allow your Vercel frontend to talk to this backend
CORS(app, resources={r"/*": {"origins": "*"}}) 

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv('GROQ_API_KEY')

def extract_wattpad_text(url: str) -> str:
    try:
        logger.info(f"Fetching story from: {url}")
        
        # Impersonate Chrome to bypass Cloudflare on 512MB RAM
        r = cureq.get(url, impersonate="chrome", timeout=30)
        
        if r.status_code != 200:
            raise Exception(f"Wattpad blocked the request (Status {r.status_code})")

        soup = BeautifulSoup(r.text, 'html.parser')
        
        # FIX: Instead of looking for a container, we grab ALL paragraphs 
        # that have the Wattpad 'data-p-id' attribute. This "jumps over" audio players.
        all_paragraphs = soup.find_all('p', attrs={'data-p-id': True})
        
        text_parts = []
        for p in all_paragraphs:
            text = p.get_text().strip()
            # Ignore very short snippets or ads
            if len(text) > 5:
                text_parts.append(text)

        # Fallback if data-p-id fails (sometimes happens on mobile versions)
        if not text_parts:
            logger.info("data-p-id not found, trying fallback story selectors...")
            story_body = soup.find('article') or soup.find('main')
            if story_body:
                for p in story_body.find_all('p'):
                    text = p.get_text().strip()
                    if len(text) > 20:
                        text_parts.append(text)

        if not text_parts:
            raise Exception("Could not find any story text on this page.")

        full_text = '\n\n'.join(text_parts)
        logger.info(f"Successfully extracted {len(full_text)} characters.")
        return full_text

    except Exception as e:
        logger.error(f"Scraper error: {str(e)}")
        raise

def translate_to_burmese(text: str) -> str:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY is not set.")

    # Optimized for Llama 3.3 / 3.1 chunk sizes
    max_chunk = 2000
    chunks = [text[i:i+max_chunk] for i in range(0, len(text), max_chunk)]
    translations = []

    for i, chunk in enumerate(chunks):
        logger.info(f"Translating chunk {i+1}/{len(chunks)}...")
        try:
            response = requests.post(
                'https://api.groq.com/openai/v1/chat/completions',
                headers={
                    'Authorization': f'Bearer {GROQ_API_KEY}',
                    'Content-Type': 'application/json'
                },
                json={
                    # UPDATED MODEL ID: Mixtral is dead, Llama 3.3 is the new king
                    'model': 'llama-3.3-70b-versatile', 
                    'messages': [
                        {'role': 'system', 'content': 'You are a professional Myanmar translator. Translate the English story text into natural, literary Burmese. Provide ONLY the translation.'},
                        {'role': 'user', 'content': chunk}
                    ],
                    'temperature': 0.3,
                },
                timeout=90
            )
            
            result = response.json()
            
            if response.status_code == 200:
                translations.append(result['choices'][0]['message']['content'])
            else:
                # This will now show you the ACTUAL error from Groq in your logs
                error_msg = result.get('error', {}).get('message', 'Unknown error')
                logger.error(f"Groq API Error: {error_msg}")
                translations.append(f"[Error: {error_msg}]")
            
            time.sleep(0.5) 
        except Exception as e:
            logger.error(f"Translation failed: {str(e)}")
            translations.append(f"[Translation Failed: {str(e)}]")

    return '\n\n'.join(translations)

@app.route('/extract', methods=['POST'])
def extract_route():
    try:
        data = request.get_json()
        url = data.get('url')
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        text = extract_wattpad_text(url)
        return jsonify({
            'success': True,
            'text': text,
            'character_count': len(text)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/translate', methods=['POST'])
def translate_route():
    try:
        data = request.get_json()
        text = data.get('text')
        if not text:
            return jsonify({'error': 'No text provided'}), 400
        
        burmese_text = translate_to_burmese(text)
        
        # We must return exactly what the frontend code expects
        return jsonify({
            'success': True,
            'translation': burmese_text,
            'character_count': {
                'original': len(text),
                'translated': len(burmese_text)
            }
        })
    except Exception as e:
        logger.error(f"Translation Route Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
