"""Filterregels voor de gefilterde Tweakers-feed.

Elk artikel van Tweakers heeft één categorie, bijvoorbeeld
"Nieuws / Computers / Laptops": soort / hoofdonderwerp / onderwerp.

Per hoofdonderwerp, en eventueel per onderwerp, staat hieronder wat erdoor mag:
  "alles"            -> elk artikel komt door
  "niets"            -> geen enkel artikel komt door
  ["apple", "ai"]    -> alleen artikelen met een woord uit die groepen in de kop

Een regel voor een onderwerp ("Computers / Laptops") gaat voor de regel van het
hoofdonderwerp ("Computers"). Een onderwerp zonder eigen regel volgt het
hoofdonderwerp. Een hoofdonderwerp dat hier niet staat, komt helemaal door.
"""

# Woordgroepen. Er wordt alleen naar de kop gekeken, op hele woorden: "Mac"
# telt niet in "Machelen", wel in "Mac-gebruikers". Een meervoud-s mag erachter
# ("iPhones", "Macs"). Woorden van drie letters of minder moeten precies zo
# geschreven zijn (dus "AI" en niet "ai", "iOS" en niet "IOS"); langere woorden
# tellen ook met andere hoofdletters.
WOORDEN = {
    "apple": [
        "Apple", "iPhone", "iPad", "iPadOS", "Mac", "MacBook", "iMac",
        "macOS", "iOS", "watchOS", "tvOS", "visionOS", "Vision Pro",
        "AirPods", "AirTag", "HomePod", "Siri", "App Store",
    ],
    "ai": [
        "AI", "kunstmatige intelligentie", "chatbot", "taalmodel",
        "taalmodellen", "LLM",
        # Westerse modellen en bedrijven
        "ChatGPT", "GPT", "OpenAI", "Gemini", "Claude", "Anthropic",
        "Copilot", "Grok", "xAI", "Llama", "Mistral", "Perplexity",
        "Midjourney", "Sora",
        # Chinese modellen en bedrijven
        "DeepSeek", "Qwen", "Kimi", "Moonshot", "Doubao", "Ernie",
        "Hunyuan", "GLM", "Zhipu", "MiniMax", "Manus",
    ],
    "windows": [
        "Windows",
    ],
}

REGELS = {
    "Gaming": "alles",
    "IT Pro": "alles",

    "Tablets en telefoons": ["apple", "ai"],

    "Beeld en geluid": "alles",
    "Beeld en geluid / Spiegelreflexcamera's": "niets",
    "Beeld en geluid / Televisies": "niets",

    "Computers": "alles",
    "Computers / Laptops": ["apple", "ai"],
    "Computers / Monitors": ["apple", "ai"],
    "Computers / Beveiliging en antivirus": ["apple", "ai"],
    "Computers / Pc's": ["apple", "ai"],
    "Computers / Processors": ["apple", "ai"],
    "Computers / Videokaarten": ["apple", "ai"],
    "Computers / Besturingssystemen": ["apple", "ai", "windows"],
    "Computers / Officesoftware en suites": "alles",
    "Computers / Overige software": "alles",
    "Computers / Processorkoeling": "niets",
}
