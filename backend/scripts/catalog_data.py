"""Catalog, name and rhythm data for the seed script.

This module is deliberately outside app/ - vertical names are allowed in the seed
because the seed is data, not behaviour.
"""
from __future__ import annotations

FIRST_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Krishna",
    "Ishaan", "Rohan", "Kabir", "Ansh", "Dhruv", "Yash", "Manav", "Nikhil",
    "Priya", "Ananya", "Diya", "Aadhya", "Saanvi", "Meera", "Kavya", "Ishita",
    "Neha", "Pooja", "Sneha", "Ritika", "Anjali", "Shreya", "Nisha", "Divya",
    "Ramesh", "Suresh", "Mahesh", "Rajesh", "Deepak", "Sanjay", "Vikram", "Amit",
    "Sunita", "Kavita", "Rekha", "Seema", "Geeta", "Lata", "Usha", "Asha",
]

LAST_NAMES = [
    "Sharma", "Verma", "Patel", "Gupta", "Joshi", "Mehta", "Nair", "Reddy",
    "Iyer", "Chauhan", "Yadav", "Mishra", "Tiwari", "Deshmukh", "Kulkarni",
    "Shah", "Agarwal", "Bansal", "Kapoor", "Rathore", "Pillai", "Ghosh",
    "Chatterjee", "Naik", "Bhatt", "Solanki", "Thakur", "Rana", "Malhotra",
]

STORES = [
    {
        "vertical": "grocery",
        "name": "Sharma Kirana Bazaar",
        "city": "Indore",
        "gstin": "23ABCDE1234F1Z5",
        "whatsapp_number": "+919812345601",
        "language": "hi-en",
    },
    {
        "vertical": "pharmacy",
        "name": "Jeevan Medical Store",
        "city": "Nagpur",
        "gstin": "27FGHIJ5678K1Z9",
        "whatsapp_number": "+919812345602",
        "language": "hi-en",
    },
    {
        "vertical": "apparel",
        "name": "Rangoli Fashion House",
        "city": "Jaipur",
        "gstin": "08KLMNO9012P1Z3",
        "whatsapp_number": "+919812345603",
        "language": "hi-en",
    },
]

# category -> (sku prefix, gst rate, price band, base item names)
CATALOG: dict[str, dict[str, dict]] = {
    "grocery": {
        "Staples": {
            "prefix": "STP", "gst": 5, "price": (45, 320),
            "items": ["Basmati Rice", "Wheat Atta", "Toor Dal", "Chana Dal", "Sugar",
                      "Poha", "Suji", "Besan", "Moong Dal", "Rajma"],
        },
        "Spices": {
            "prefix": "SPC", "gst": 5, "price": (30, 180),
            "items": ["Haldi Powder", "Mirchi Powder", "Dhania Powder", "Garam Masala",
                      "Jeera", "Rai", "Kali Mirch", "Elaichi"],
        },
        "Snacks": {
            "prefix": "SNK", "gst": 12, "price": (10, 90),
            "items": ["Aloo Bhujia", "Salted Chips", "Masala Peanuts", "Khakhra",
                      "Biscuit Pack", "Namkeen Mix", "Chikki", "Rusk"],
        },
        "Beverages": {
            "prefix": "BEV", "gst": 12, "price": (20, 260),
            "items": ["Tea Leaves", "Filter Coffee", "Mango Drink", "Soda Bottle",
                      "Lemon Squash", "Health Drink Powder"],
        },
        "Dairy": {
            "prefix": "DRY", "gst": 5, "price": (25, 240),
            "items": ["Toned Milk", "Curd Cup", "Paneer Block", "Butter", "Ghee",
                      "Cheese Slices", "Lassi"],
        },
        "Personal Care": {
            "prefix": "PRC", "gst": 18, "price": (35, 260),
            "items": ["Bath Soap", "Shampoo Sachet", "Toothpaste", "Hair Oil",
                      "Talc Powder", "Face Wash"],
        },
        "Cleaning": {
            "prefix": "CLN", "gst": 18, "price": (28, 210),
            "items": ["Detergent Powder", "Dishwash Bar", "Floor Cleaner",
                      "Toilet Cleaner", "Scrub Pad"],
        },
    },
    "pharmacy": {
        "Analgesics": {
            "prefix": "ANL", "gst": 12, "price": (12, 140),
            "items": ["Paracetamol 500", "Ibuprofen 400", "Diclofenac Gel",
                      "Aceclofenac 100", "Muscle Relax Spray"],
        },
        "Antibiotics": {
            "prefix": "ABT", "gst": 12, "price": (45, 420),
            "items": ["Amoxicillin 500", "Azithromycin 500", "Cefixime 200",
                      "Ofloxacin 200", "Doxycycline 100"],
        },
        "Vitamins": {
            "prefix": "VIT", "gst": 12, "price": (60, 560),
            "items": ["Vitamin D3 Sachet", "B-Complex Capsule", "Calcium Tablet",
                      "Multivitamin Syrup", "Iron Folic Tablet", "Zinc Tablet"],
        },
        "Diabetes Care": {
            "prefix": "DIA", "gst": 5, "price": (85, 720),
            "items": ["Metformin 500", "Glimepiride 2", "Sugar Test Strips",
                      "Insulin Pen Needle", "Diabetic Foot Cream"],
        },
        "Skin Care": {
            "prefix": "SKN", "gst": 18, "price": (70, 480),
            "items": ["Moisturising Lotion", "Antifungal Cream", "Sunscreen Gel",
                      "Calamine Lotion", "Medicated Soap"],
        },
        "Baby Care": {
            "prefix": "BBY", "gst": 12, "price": (95, 640),
            "items": ["Baby Lotion", "Diaper Pack", "Baby Powder", "ORS Sachet",
                      "Baby Wipes"],
        },
        "Devices": {
            "prefix": "DEV", "gst": 12, "price": (180, 2400),
            "items": ["Digital Thermometer", "BP Monitor", "Nebuliser Mask",
                      "Weighing Scale", "Pulse Oximeter"],
        },
    },
    "apparel": {
        "Kurta Sets": {
            "prefix": "KRT", "gst": 12, "price": (699, 3200),
            "items": ["Cotton Kurta Set", "Chikankari Kurta", "Anarkali Suit",
                      "Straight Kurta", "Palazzo Set"],
        },
        "Sarees": {
            "prefix": "SAR", "gst": 12, "price": (899, 8500),
            "items": ["Bandhani Saree", "Chiffon Saree", "Silk Saree",
                      "Cotton Handloom Saree", "Georgette Saree"],
        },
        "Shirts": {
            "prefix": "SHT", "gst": 12, "price": (549, 2200),
            "items": ["Formal Shirt", "Casual Check Shirt", "Linen Shirt",
                      "Printed Shirt", "Half Sleeve Shirt"],
        },
        "Trousers": {
            "prefix": "TRS", "gst": 12, "price": (749, 2600),
            "items": ["Chino Trouser", "Formal Trouser", "Denim Jeans",
                      "Cargo Pant", "Track Pant"],
        },
        "Kidswear": {
            "prefix": "KID", "gst": 5, "price": (299, 1400),
            "items": ["Kids Frock", "Kids Shirt Set", "Kids Ethnic Kurta",
                      "Kids Jeans", "Kids Party Dress"],
        },
        "Ethnic Wear": {
            "prefix": "ETH", "gst": 12, "price": (1299, 9500),
            "items": ["Sherwani", "Lehenga Choli", "Nehru Jacket",
                      "Dhoti Kurta", "Indo Western Set"],
        },
        "Accessories": {
            "prefix": "ACC", "gst": 18, "price": (149, 1200),
            "items": ["Dupatta", "Leather Belt", "Stole", "Potli Bag", "Scarf"],
        },
    },
}

BRANDS = ["Anand", "Gopal", "Shree", "Sunrise", "Vardhman", "Kisan", "Nutri", "Prakash"]
COLOURS = ["Maroon", "Indigo", "Mustard", "Emerald", "Ivory", "Rust", "Teal", "Black"]
FABRICS = ["Cotton", "Silk", "Linen", "Rayon", "Georgette", "Denim"]
SIZES = ["XS", "S", "M", "L", "XL", "XXL", "Free"]
SEASONS = ["Summer", "Winter", "Festive", "All Season"]
PACK_SIZES = ["100 g", "250 g", "500 g", "1 kg", "200 ml", "500 ml", "1 litre", "6 pc"]
COMPOSITIONS = [
    "Paracetamol IP 500mg", "Amoxicillin 500mg", "Azithromycin 500mg",
    "Cholecalciferol 60000 IU", "Metformin HCl 500mg", "Cetirizine 10mg",
    "Pantoprazole 40mg", "Calcium Carbonate 500mg",
]

# Basket rhythm per vertical: how a sale in this trade actually looks.
RHYTHM = {
    "grocery": {
        "transactions": 4000,
        "basket": (3, 8),
        "line_qty": (1, 4),
        "discount_chance": 0.12,
        "month_weights": {m: 1.0 for m in range(1, 13)} | {10: 1.35, 11: 1.3, 3: 1.1},
        "category_loyalty": 0.35,
        "repeat_gap_days": (5, 20),
    },
    "pharmacy": {
        "transactions": 4000,
        "basket": (1, 3),
        "line_qty": (1, 2),
        "discount_chance": 0.05,
        "month_weights": {m: 1.0 for m in range(1, 13)} | {7: 1.25, 8: 1.3, 1: 1.15},
        "category_loyalty": 0.8,
        "repeat_gap_days": (25, 40),
    },
    "apparel": {
        "transactions": 4000,
        "basket": (1, 3),
        "line_qty": (1, 2),
        "discount_chance": 0.35,
        "month_weights": {m: 0.7 for m in range(1, 13)}
        | {10: 2.6, 11: 2.4, 4: 1.6, 5: 1.4, 12: 1.5},
        "category_loyalty": 0.3,
        "repeat_gap_days": (60, 160),
    },
}

# Reminder rules from the brief, section 6.
REMINDER_RULES = [
    {
        "kind": "reorder_due",
        "signal": "last_purchase_in_category",
        "offset_days": 0,
        "channel": "whatsapp",
        "verticals": ["grocery", "pharmacy", "cosmetics"],
    },
    {
        "kind": "revisit_due",
        "signal": "last_visit_any",
        "offset_days": 0,
        "channel": "whatsapp",
        "verticals": ["apparel", "optical", "electronics"],
    },
    {
        "kind": "pickup_ready",
        "signal": "job_status_ready",
        "offset_days": 0,
        "channel": "whatsapp",
        "verticals": ["apparel", "optical", "electronics", "bakery"],
    },
    {
        "kind": "review_request",
        "signal": "transaction_completed",
        "offset_days": 0,
        "channel": "whatsapp",
        "verticals": ["grocery", "pharmacy", "cosmetics", "apparel", "optical",
                      "electronics", "bakery", "hardware"],
    },
    {
        "kind": "winback",
        "signal": "segment_inactive",
        "offset_days": 0,
        "channel": "whatsapp",
        "verticals": ["grocery", "pharmacy", "cosmetics", "apparel", "optical",
                      "electronics", "bakery", "hardware"],
    },
    {
        "kind": "occasion",
        "signal": "customer_dob_or_anniversary",
        "offset_days": 0,
        "channel": "whatsapp",
        "verticals": ["grocery", "pharmacy", "cosmetics", "apparel", "optical",
                      "electronics", "bakery"],
    },
]

# Fallback copy. One row per (vertical, kind) so a store always has a message
# even when every LLM provider is down.
GENERIC_TEMPLATES = {
    "reorder_due": (
        "Namaste {customer_name}, it has been {days} days since your last {category} "
        "purchase at {store_name}. Shall we keep your usual items ready?",
        "Remind the customer their regular purchase cycle is due and offer to keep items ready.",
    ),
    "revisit_due": (
        "Hello {customer_name}, it has been {days} days since your last visit to "
        "{store_name}. New arrivals are in - do come by.",
        "Invite the customer back after a long gap and mention new arrivals.",
    ),
    "pickup_ready": (
        "Hello {customer_name}, your order at {store_name} is ready for pickup. "
        "We are open till 9 pm.",
        "Tell the customer their order is ready and give pickup timing.",
    ),
    "review_request": (
        "Thank you for shopping at {store_name}, {customer_name}. If we served you well, "
        "a quick Google review would mean a lot: {review_url}",
        "Thank the customer for the purchase and ask for a Google review, politely, once.",
    ),
    "winback": (
        "We have missed you, {customer_name}. It has been {days} days since your last "
        "visit to {store_name}. Come say hello.",
        "Win back a customer who has gone quiet. Warm, no pressure, no invented offer.",
    ),
    "occasion": (
        "Happy {occasion}, {customer_name}. Warm wishes from all of us at {store_name}.",
        "Wish the customer for their special day. Two short lines, no selling.",
    ),
}

# Vertical-specific overrides where the trade needs different words.
TEMPLATE_OVERRIDES = {
    ("pharmacy", "reorder_due"): (
        "Namaste {customer_name}, your last {category} purchase at {store_name} was "
        "{days} days ago. Please check with your doctor if a refill is due.",
        "Remind about a refill cycle. No health advice, no discount claim, defer to the doctor.",
    ),
    ("apparel", "revisit_due"): (
        "Hello {customer_name}, {days} days since your last visit to {store_name}. "
        "The new season racks are out - sizes go fast.",
        "Invite the customer back for the new season collection. Festive and welcoming.",
    ),
    ("grocery", "winback"): (
        "{customer_name} ji, {days} days since your last order at {store_name}. "
        "Shall we pack your monthly staples again?",
        "Warm neighbourly win-back offering to pack the usual monthly list.",
    ),
    ("bakery", "pickup_ready"): (
        "Hello {customer_name}, your order at {store_name} is fresh out of the oven "
        "and ready for pickup.",
        "Tell the customer the fresh order is ready for pickup today.",
    ),
}
