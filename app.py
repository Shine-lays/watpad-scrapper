from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
import os
import time
from dotenv import load_dotenv
from curl_cffi import requests as cureq
from bs4 import BeautifulSoup
import requests

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- API KEY ROTATION LOGIC ---
API_KEYS = [
    os.getenv('GROQ_API_KEY_1'),
    os.getenv('GROQ_API_KEY_2'),
    os.getenv('GROQ_API_KEY_3')
]
API_KEYS = [k for k in API_KEYS if k] # Remove empty ones
current_key_index = 0

def get_current_key():
    global current_key_index
    return API_KEYS[current_key_index]

def rotate_key():
    global current_key_index
    if len(API_KEYS) > 1:
        current_key_index = (current_key_index + 1) % len(API_KEYS)
        logger.warning(f"Swapping to API Key Index: {current_key_index}")

# --- THE PROFESSIONAL SYSTEM PROMPT ---
BURMESE_SYSTEM_PROMPT = """
ROLE:
You are a world-class literary translator and professional novelist. Your specialty is localizing English Young Adult (YA) and Romance fiction from Wattpad into modern, immersive Burmese (Myanmar). 

CORE OBJECTIVE:
Your goal is to produce a "Natural Novel Style" (ဝတ္ထုဟန်). Avoid "Machine Translation" (literal word-for-word) and "Textbook Burmese" (stiff, formal, or archaic language). The reader should feel like the story was originally written in Burmese.

LINGUISTIC FRAMEWORK & RULES:

1. REGISTER & TONE:
   - NARRATION: Use modern literary Burmese. It should be descriptive and emotive, not robotic.
   - DIALOGUE: Must sound like real people talking. Use natural conversational particles at the end of sentences (e.g., 'လေ', 'ပေါ့', 'ရှင်', 'ဗျာ', 'နော်', 'ဦးမလို့လား').
   - EMOTION: If the English text is sassy, sarcastic, or dramatic, the Burmese must reflect that same energy using local slang or expressive verbs.

2. CONTEXTUAL VOCABULARY (THE "ANTI-LITERAL" RULE):
   - Descriptions of Appearance: For "Hot," "Sexy," or "Attractive," use context-heavy terms like 'ကြည့်ကောင်းပြီး ဆွဲဆောင်မှုရှိတဲ့', 'လန်းတဲ့', or 'စမတ်ကျတဲ့'.
   - Actions: Do not use dictionary-first definitions. 
     - "Scratched" (in a fight) -> 'ကုတ်ခြစ်' (NOT 'ခုပ်' which is for chopping).
     - "Smirked" -> 'မဲ့ပြုံးပြုံးသည်' or 'နှုတ်ခမ်းတစ်ဖက်တွန့်ရုံပြုံးသည်'.
     - "Rolled eyes" -> 'မျက်စိနောက်သလို ကြည့်သည်' or 'မျက်လုံးအထက်လှန်ကြည့်သည်'.
   - Clothing: Translate modern fashion naturally (e.g., 'ဂျင်းဘောင်းဘီ', 'တီရှပ်', 'အတွင်းခံ').

3. PRONOUN MANAGEMENT:
   - Correctly identify the gender and relationship between characters to choose the right pronouns. 
   - Use 'ကျွန်မ/ကျွန်တော်' for formal/standard narration, but allow characters to use 'ငါ/နင်', 'မင်း/ကိုယ်', or names in dialogue to show intimacy or rivalry.
   - Use 'သူမ' for "She" in narration, but 'ကောင်မလေး' or her name in conversational context.

4. IDIOMS & PHRASES:
   - When you encounter English idioms (e.g., "butterflies in my stomach" or "breaking the ice"), do not translate them literally. Instead, find the Burmese equivalent for that feeling (e.g., 'ရင်ထဲ တထိတ်ထိတ်ဖြစ်နေတာ').

5. FORBIDDEN OUTPUTS:
   - Never output "Machine Burmese" structures like 'ပြုလုပ်ခဲ့သည်' for every verb. Use active, natural verbs.
   - Never include English words unless they are modern loanwords commonly used in Myanmar (e.g., "Pizza," "Phone").

STRICT FORMATTING:
- Output ONLY the translated Burmese text.
- Maintain paragraph breaks exactly as they appear in the source.
- Do not provide any English explanations, notes, or introductions.
"""

def extract_wattpad_text(url: str) -> str:
    try:
        logger.info(f"Stealth-fetching: {url}")
        # Impersonate Chrome to stay under 512MB RAM & bypass Cloudflare
        r = cureq.get(url, impersonate="chrome", timeout=30)
        if r.status_code != 200:
            raise Exception(f"Wattpad Access Denied: {r.status_code}")

        soup = BeautifulSoup(r.text, 'html.parser')
        # Jump over audio players by selecting only story-id paragraphs
        all_paragraphs = soup.find_all('p', attrs={'data-p-id': True})
        
        text_parts = [p.get_text().strip() for p in all_paragraphs if len(p.get_text().strip()) > 5]
        
        if not text_parts:
            # Fallback for different Wattpad layouts
            story_body = soup.find('article') or soup.find('main')
            if story_body:
                text_parts = [p.get_text().strip() for p in story_body.find_all('p') if len(p.get_text().strip()) > 20]

        return '\n\n'.join(text_parts)
    except Exception as e:
        logger.error(f"Scraper error: {str(e)}")
        raise

def translate_chunk_with_retry(chunk: str, retries=3):
    for attempt in range(retries * len(API_KEYS)):
        current_key = get_current_key()
        try:
            response = requests.post(
                'https://api.groq.com/openai/v1/chat/completions',
                headers={'Authorization': f'Bearer {current_key}', 'Content-Type': 'application/json'},
                json={
                    'model': 'llama-3.3-70b-versatile',
                    'messages': [
                        {'role': 'system', 'content': BURMESE_SYSTEM_PROMPT},
                        {'role': 'user', 'content': f"Translate this story segment:\n\n{chunk}"}
                    ],
                    'temperature': 0.4,
                },
                timeout=90
            )

            if response.status_code == 200:
                return response.json()['choices'][0]['message']['content']
            
            # If rate limited (429) or service overloaded, rotate key and retry
            if response.status_code in [429, 503, 400]:
                rotate_key()
                time.sleep(1)
                continue
            
            logger.error(f"Groq API Error {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"Network error with key {current_key_index}: {str(e)}")
            rotate_key()
            
    return "[Translation failed for this section]"

def translate_to_burmese(text: str) -> str:
    # 1500 characters per chunk keeps us safe from most Rate Limits
    max_chunk = 1500
    chunks = [text[i:i+max_chunk] for i in range(0, len(text), max_chunk)]
    translations = []

    for i, chunk in enumerate(chunks):
        logger.info(f"Translating chunk {i+1}/{len(chunks)}")
        translated_part = translate_chunk_with_retry(chunk)
        translations.append(translated_part)
        time.sleep(0.5) # Short rest between chunks

    return '\n\n'.join(translations)

@app.route('/extract', methods=['POST'])
def extract_route():
    try:
        url = request.json.get('url')
        if not url: return jsonify({'error': 'No URL'}), 400
        text = extract_wattpad_text(url)
        return jsonify({'success': True, 'text': text})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/translate', methods=['POST'])
def translate_route():
    try:
        text = request.json.get('text', '')
        if not text: return jsonify({'error': 'No text'}), 400
        
        translated_text = translate_to_burmese(text)
        return jsonify({
            'success': True, 
            'translation': translated_text,
            'character_count': {'original': len(text), 'translated': len(translated_text)}
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
