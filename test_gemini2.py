import sys
from google import genai
from jatayu.config import get_config

def main():
    config = get_config()
    client = genai.Client(api_key=config['gemini_api_key'])
    
    print("Listing available models...")
    try:
        models = client.models.list()
        for m in models:
            if 'generateContent' in m.supported_actions and 'flash' in m.name:
                print(f"Model: {m.name}")
    except Exception as e:
        print("Failed:", e)

if __name__ == "__main__":
    main()
