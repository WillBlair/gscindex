"""
Major Shipping Ports Data
==========================
Definitions for the 37 major global shipping ports tracked by the dashboard.

Each entry contains:
    - name: Port city name
    - lat, lon: Coordinates for weather lookups and map markers
    - direct_keywords: Terms that match this port specifically (full penalty)
    - regional_keywords: Broader terms for the region (half penalty)
"""

from __future__ import annotations

MAJOR_PORTS: list[tuple[str, float, float, list[str]]] = [
    # ── North America ───────────────────────────────────────
    ("Houston",       29.76,  -95.37,
     ["houston", "gulf coast port"]),
    ("New York",      40.68,  -74.04,
     ["new york port", "newark port", "port authority", "east coast port"]),
    ("Boston",        42.36,  -71.05,
     ["boston port", "massport", "east coast port"]),
    ("Los Angeles",   33.75, -118.27,
     ["los angeles", "long beach", "san pedro", "west coast port"]),
    ("Savannah",      32.08,  -81.09,
     ["savannah port", "east coast port"]),
    ("Vancouver",     49.29, -123.11,
     ["vancouver port"]),
    # ── Central & South America ─────────────────────────────
    ("Colon",          9.36,  -79.90,
     ["panama canal", "colon port"]),
    ("Balboa",         8.95,  -79.56,
     ["balboa", "panama canal"]),
    ("Cristobal",      9.35,  -79.90,
     ["cristobal", "panama canal"]),
    ("Manzanillo",    19.05, -104.32,
     ["manzanillo"]),
    ("Santos",       -23.96,  -46.33,
     ["santos port"]),
    ("Buenos Aires", -34.60,  -58.38,
     ["buenos aires"]),
    # ── Europe ──────────────────────────────────────────────
    ("Rotterdam",     51.92,    4.48,
     ["rotterdam", "europoort", "northern europe port"]),
    ("Hamburg",       53.55,    9.99,
     ["hamburg", "northern europe port"]),
    ("Antwerp",       51.27,    4.39,
     ["antwerp", "northern europe port"]),
    ("Felixstowe",    51.96,    1.35,
     ["felixstowe", "uk port"]),
    ("Piraeus",       37.94,   23.65,
     ["piraeus", "mediterranean port"]),
    ("Algeciras",     36.13,   -5.45,
     ["algeciras", "strait of gibraltar", "mediterranean port"]),
    ("Gdansk",        54.35,   18.65,
     ["gdansk", "baltic port"]),
    # ── East Asia ───────────────────────────────────────────
    ("Shanghai",      31.23,  121.47,
     ["shanghai", "yangshan", "chinese port"]),
    ("Shekou",        22.48,  113.91,
     ["shekou", "shenzhen", "chinese port"]),
    ("Dalian",        38.92,  121.61,
     ["dalian", "chinese port"]),
    ("Hong Kong",     22.29,  114.17,
     ["hong kong", "chinese port"]),
    ("Busan",         35.10,  129.03,
     ["busan", "korean port"]),
    ("Qingdao",       36.07,  120.38,
     ["qingdao", "chinese port"]),
    ("Tokyo",         35.65,  139.84,
     ["tokyo", "japanese port"]),
    ("Kaohsiung",     22.62,  120.31,
     ["kaohsiung"]),
    # ── Southeast Asia ──────────────────────────────────────
    ("Singapore",      1.35,  103.82,
     ["singapore", "malacca strait", "strait of malacca"]),
    ("Laem Chabang",  13.08,  100.88,
     ["laem chabang"]),
    ("Port Klang",     3.00,  101.39,
     ["port klang"]),
    # ── South Asia ──────────────────────────────────────────
    ("Mumbai",        19.08,   72.88,
     ["mumbai", "nhava sheva", "jnpt", "indian port"]),
    ("Chennai",       13.08,   80.29,
     ["chennai", "indian port"]),
    ("Colombo",        6.93,   79.84,
     ["colombo"]),
    # ── Middle East ─────────────────────────────────────────
    ("Dubai",         25.28,   55.30,
     ["dubai", "jebel ali", "persian gulf", "gulf state", "hormuz"]),
    ("Khalifa Port",  24.84,   54.65,
     ["khalifa", "abu dhabi", "persian gulf", "hormuz"]),
    ("Hamad Port",    25.01,   51.61,
     ["hamad port", "qatar", "persian gulf", "hormuz"]),
    ("Salalah",       16.94,   54.00,
     ["salalah", "oman"]),
    ("Jeddah",        21.49,   39.19,
     ["jeddah", "red sea"]),
    # ── Africa ──────────────────────────────────────────────
    ("Durban",       -29.86,   31.02,
     ["durban"]),
    ("Cape Town",    -33.91,   18.43,
     ["cape town"]),
    ("Beira",        -19.83,   34.84,
     ["beira", "mozambique"]),
    ("Mombasa",       -4.04,   39.67,
     ["mombasa"]),
    ("Djibouti",      11.59,   43.15,
     ["djibouti", "horn of africa", "red sea"]),
    ("Lagos",          6.45,    3.39,
     ["lagos", "apapa"]),
    ("Conakry",        9.51,  -13.71,
     ["conakry", "guinea"]),
    ("Casablanca",    33.60,   -7.59,
     ["casablanca", "morocco"]),
    ("Port Said",     31.26,   32.30,
     ["port said", "suez canal", "suez", "red sea"]),
    # ── Oceania ─────────────────────────────────────────────
    ("Sydney",       -33.86,  151.20,
     ["sydney port"]),
    ("Melbourne",    -37.81,  144.96,
     ["melbourne port"]),
]
