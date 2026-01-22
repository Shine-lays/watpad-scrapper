from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import logging
import os
import time
import asyncio
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv('GROQ_API_KEY')

async def extract_wattpad_text_async(url: str) -> str:
    browser = None
    try:
        logger.info(f"Starting Playwright browser for: {url}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox'],
            )
            context = await browser.new_context()
            page = await context.new_page()

            await page.set_user_agent(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )

            await page.goto(url, wait_until='domcontentloaded', timeout=60000)
            await page.wait_for_timeout(2000)

            await page.evaluate("""
                async () => {
                    await new Promise((resolve) => {
                        let totalHeight = 0;
                        const distance = 100;
                        const timer = setInterval(() => {
                            window.scrollBy(0, distance);
                            totalHeight += distance;
                            if (totalHeight >= document.body.scrollHeight) {
                                clearInterval(timer);
                                window.scrollTo(0, 0);
                                resolve();
                            }
                        }, 150);
                    });
                }
            """)

            logger.info("Extracting text from rendered page...")
            text_parts = []

            elements = await page.query_selector_all('[data-p-id]')
            for elem in elements:
                text = await elem.text_content()
                if text and text.strip():
                    text_parts.append(text.strip())

            if text_parts:
                await context.close()
                return '\n\n'.join(text_parts)

            article = await page.query_selector('article, main, [role="main"]')
            if article:
                paragraphs = await article.query_selector_all('p')
                for p in paragraphs:
                    text = await p.text_content()
                    if text and text.strip() and len(text.strip()) > 20:
                        text_parts.append(text.strip())

            if text_parts:
                await context.close()
                return '\n\n'.join(text_parts)

            selectors = ['.part-content', '.story-content', '.chapter-content', '[class*="story"]']
            for selector in selectors:
                container = await page.query_selector(selector)
                if container:
                    paragraphs = await container.query_selector_all('p')
                    if paragraphs:
                        for p in paragraphs:
                            text = await p.text_content()
                            if text and text.strip() and len(text.strip()) > 20:
                                text_parts.append(text.strip())
                        if text_parts:
                            await context.close()
                            return '\n\n'.join(text_parts)

            all_paragraphs = await page.query_selector_all('p')
            for p in all_paragraphs:
                text = await p.text_content()
                if text and len(text.strip()) > 30:
                    if not any(x in text.lower() for x in ['advertisement', 'sponsored', 'follow', 'share', 'vote', 'comment', 'terms', 'privacy']):
                        text_parts.append(text.strip())

            if text_parts:
                await context.close()
                return '\n\n'.join(text_parts)

            all_text = await page.inner_text('body')
            await context.close()
            return all_text if all_text else ''

    except Exception as e:
        logger.error(f"Extraction error: {str(e)}")
        raise
    finally:
        if browser:
            await browser.close()

def extract_wattpad_text(url: str) -> str:
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(extract_wattpad_text_async(url))
        loop.close()
        return result
    except Exception as e:
        logger.error(f"Sync wrapper error: {str(e)}")
        raise

def translate_to_burmese(text: str) -> str:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY not configured")

    max_chunk = 2500
    chunks = [text[i:i+max_chunk] for i in range(0, len(text), max_chunk)]

    translations = []

    for i, chunk in enumerate(chunks):
        logger.info(f"Translating chunk {i+1}/{len(chunks)}")

        response = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {GROQ_API_KEY}',
                'Content-Type': 'application/json',
            },
            json={
                'model': 'mixtral-8x7b-32768',
                'messages': [
                    {
                        'role': 'system',
                        'content': 'You are a professional translator. Translate the given text to Burmese (Myanmar language). Maintain formatting and preserve line breaks. Only provide the translation without explanations.'
                    },
                    {
                        'role': 'user',
                        'content': f'Translate this to Burmese:\n\n{chunk}'
                    }
                ],
                'temperature': 0.3,
                'max_tokens': 2048,
            },
            timeout=60
        )

        if response.status_code != 200:
            try:
                error_data = response.json()
                raise Exception(f"Groq API error: {error_data.get('error', {}).get('message', 'Unknown error')}")
            except:
                raise Exception("Groq API error: Unknown error (non-json response)")

        result = response.json()
        translated_chunk = result['choices'][0]['message']['content']
        translations.append(translated_chunk)

        time.sleep(0.5)

    return '\n\n'.join(translations)

@app.route('/extract', methods=['POST'])
def extract_only():
    try:
        data = request.json
        url = data.get('url')

        if not url:
            return jsonify({'error': 'URL is required'}), 400

        if 'wattpad.com' not in url:
            return jsonify({'error': 'Invalid Wattpad URL'}), 400

        extracted_text = extract_wattpad_text(url)

        if not extracted_text or len(extracted_text) < 100:
            return jsonify({'error': 'Could not extract sufficient text from the story.'}), 400

        return jsonify({
            'success': True,
            'text': extracted_text,
            'character_count': len(extracted_text),
            'url': url
        }), 200

    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/translate', methods=['POST'])
def translate_only():
    try:
        data = request.json
        text = data.get('text')

        if not text:
            return jsonify({'error': 'Text is required'}), 400

        translated_text = translate_to_burmese(text)

        return jsonify({
            'success': True,
            'translation': translated_text,
            'character_count': {
                'original': len(text),
                'translated': len(translated_text)
            }
        }), 200

    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
