"""
ProfitPal Calligraphy Generator
===============================

Renders Dennis J's personal letter in beautiful blackletter/calligraphic style 
onto a parchment-like image and saves as PNG and PDF.

Perfect for:
- Website introduction page background
- Printed materials  
- Marketing presentations
- Premium branding materials

Requirements:
    pip install pillow

Font recommendations (free):
    - UnifrakturCook (Google Fonts)
    - Old English Text MT 
    - Cloister Black
    - BlackletterTextura

Usage:
    1. Download a blackletter TTF/OTF font
    2. Set FONT_PATH to your font file
    3. Run: python profitpal_calligraphy.py
    4. Files will be saved as PNG (web) and PDF (print)
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import textwrap
from datetime import datetime
import random
import math

# ==================== PROFITPAL SETTINGS ====================
FONT_PATH = "PinyonScript-Regular.ttf"  # <- Download from Google Fonts
OUTPUT_PNG = "profitpal_letter.png"
OUTPUT_PDF = "profitpal_letter.pdf"

# Canvas settings - optimized for web and print
CANVAS_WIDTH = 1800            # pixels (good for web display)
CANVAS_HEIGHT = 2600           # pixels (portrait format)
MARGIN_LEFT = 140              # left margin
MARGIN_RIGHT = 140             # right margin  
MARGIN_TOP = 180               # top margin
MARGIN_BOTTOM = 200            # bottom margin

# Typography settings
FONT_SIZE = 58                 # main text size (readable blackletter)
TITLE_FONT_SIZE = 96          # title size
SIGNATURE_FONT_SIZE = 72      # signature size
LINE_SPACING = 1.15           # line height multiplier
WRAP_WIDTH = 28               # characters per line (shorter for readability)

# Colors - Professional ProfitPal theme
TEXT_COLOR = (20, 15, 10)           # Dark ink color
PARCHMENT_BASE = (248, 243, 235)    # Warm parchment color
TITLE_COLOR = (139, 69, 19)         # Brown for title
SIGNATURE_COLOR = (101, 67, 33)     # Darker brown for signature

# Effects
ADD_AGE_SPOTS = True           # Vintage aging effect
ADD_VIGNETTE = True           # Edge darkening
ADD_DECORATIVE_BORDER = True  # Ornamental border
SIGNATURE_ROTATION = -2.1     # Slight rotation for handwritten feel

# Professional spacing
PARAGRAPH_SPACING = 45        # Space between paragraphs
SIGNATURE_SPACING = 60        # Extra space before signature
# =============================================================

# Dennis J's Letter Text - Professional Business Version
LETTER_TEXT = """You've discovered my service online and found your way here. Allow me to share the story behind ProfitPal. While the market offers numerous similar platforms, very few were built from genuine passion and personal necessity.

The foundation was laid over 10 years ago with a simple Excel spreadsheet. I was manually inputting company data following earnings releases, spending countless hours developing formulas to extract meaningful insights from all those numbers.

Several years later, I integrated VBA programming, transforming that basic spreadsheet into a sophisticated analytical system. That evolution became the blueprint for what you see today - not merely another financial tool, but a comprehensive ecosystem built on proven methodology.

I continue expanding its capabilities because I remain actively invested in the markets myself - hunting for undervalued opportunities, executing options strategies, constantly refining the analysis framework. This isn't theoretical work; it's battle-tested in real market conditions.

My sincere hope is that this decade of development and refinement will serve as a valuable asset in your investment decisions. If it helps you identify even one exceptional opportunity, the years of work will have been worthwhile."""

# Signature block
SIGNATURE_TEXT = """Sincerely

Dennis J

CEO"""

def create_parchment_background(w, h, base_color):
    """Create realistic parchment texture with subtle variations"""
    print("Creating parchment background...")
    img = Image.new("RGB", (w, h), base_color)

    # Add paper grain texture
    px = img.load()
    for y in range(0, h, 1):
        for x in range(0, w, 1):
            # Random grain variation
            jitter = random.randint(-12, 12)
            r = max(0, min(255, base_color[0] + jitter))
            g = max(0, min(255, base_color[1] + jitter))
            b = max(0, min(255, base_color[2] + jitter))
            px[x, y] = (r, g, b)

    # Subtle blur for paper texture
    img = img.filter(ImageFilter.GaussianBlur(radius=0.6))
    return img

def add_age_spots(img, count=85):
    """Add vintage aging spots for authentic manuscript feel"""
    print("Adding vintage aging effects...")
    draw = ImageDraw.Draw(img)
    w, h = img.size

    for _ in range(count):
        # Random positioning with slight bias toward edges
        x = int(random.random() * w)
        y = int(random.random() * h)
        radius = random.randint(4, 24)

        # Subtle brown spots
        alpha = random.randint(15, 35)
        color = (180, 140, 100, alpha)

        # Create spot on alpha layer
        spot = Image.new("RGBA", img.size, (0,0,0,0))
        sd = ImageDraw.Draw(spot)
        sd.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color)
        img = Image.alpha_composite(img.convert("RGBA"), spot)

    return img.convert("RGB")

def add_vignette(img, intensity=0.7):
    """Add subtle vignette effect for premium look"""
    print("Adding vignette effect...")
    w, h = img.size
    vign = Image.new("L", (w, h), 0)

    # Create radial gradient from center
    for y in range(h):
        for x in range(w):
            dx = (x - w/2) / (w/2)
            dy = (y - h/2) / (h/2)
            d = math.sqrt(dx*dx + dy*dy)
            val = int(255 * max(0.0, 1.0 - (d**1.8)*intensity))
            vign.putpixel((x,y), val)

    # Apply vignette
    colored = Image.new("RGBA", (w,h))
    colored.paste(img)
    colored.putalpha(vign)
    background = Image.new("RGB", (w,h), (30, 25, 20))
    background.paste(colored, mask=colored.split()[-1])
    return background

def add_decorative_border(img):
    """Add elegant decorative border"""
    print("Adding decorative border...")
    draw = ImageDraw.Draw(img)
    w, h = img.size

    # Main border
    border_color = (139, 69, 19, 180)
    border_img = Image.new("RGBA", img.size, (0,0,0,0))
    bd = ImageDraw.Draw(border_img)

    # Outer border
    bd.rectangle([20, 20, w-20, h-20], outline=border_color, width=3)
    # Inner decorative line
    bd.rectangle([35, 35, w-35, h-35], outline=(160, 82, 45, 120), width=1)

    # Corner decorations (simple ornamental lines)
    corner_size = 40
    corner_color = (139, 69, 19, 150)

    # Top-left corner
    bd.line([35, 35, 35+corner_size, 35], fill=corner_color, width=2)
    bd.line([35, 35, 35, 35+corner_size], fill=corner_color, width=2)

    # Top-right corner  
    bd.line([w-35, 35, w-35-corner_size, 35], fill=corner_color, width=2)
    bd.line([w-35, 35, w-35, 35+corner_size], fill=corner_color, width=2)

    # Bottom-left corner
    bd.line([35, h-35, 35+corner_size, h-35], fill=corner_color, width=2)
    bd.line([35, h-35, 35, h-35-corner_size], fill=corner_color, width=2)

    # Bottom-right corner
    bd.line([w-35, h-35, w-35-corner_size, h-35], fill=corner_color, width=2)
    bd.line([w-35, h-35, w-35, h-35-corner_size], fill=corner_color, width=2)

    img = Image.alpha_composite(img.convert("RGBA"), border_img).convert("RGB")
    return img

def render_profitpal_letter():
    """Main rendering function for ProfitPal letter"""
    print("🔥 Starting ProfitPal Calligraphy Generation 🔥")

    # Create base parchment
    img = create_parchment_background(CANVAS_WIDTH, CANVAS_HEIGHT, PARCHMENT_BASE)

    # Add aging effects
    if ADD_AGE_SPOTS:
        img = add_age_spots(img, count=90)

    # Load fonts
    try:
        main_font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
        title_font = ImageFont.truetype(FONT_PATH, TITLE_FONT_SIZE)
        signature_font = ImageFont.truetype(FONT_PATH, SIGNATURE_FONT_SIZE)
        print(f"✅ Loaded font: {FONT_PATH}")
    except Exception as e:
        print(f"❌ Error loading font: {e}")
        print("💡 Try downloading UnifrakturCook-Bold.ttf from Google Fonts")
        return None

    draw = ImageDraw.Draw(img)

    # Add title
    print("Adding title...")
    title = "A Personal Letter"
    subtitle = "From the Creator's Desk"

    # Center title
    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    title_width = title_bbox[2] - title_bbox[0]
    title_x = (CANVAS_WIDTH - title_width) // 2
    title_y = MARGIN_TOP

    draw.text((title_x, title_y), title, font=title_font, fill=TITLE_COLOR)

    # Center subtitle
    subtitle_font = ImageFont.truetype(FONT_PATH, FONT_SIZE - 10)
    subtitle_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
    subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
    subtitle_x = (CANVAS_WIDTH - subtitle_width) // 2
    subtitle_y = title_y + TITLE_FONT_SIZE + 20

    draw.text((subtitle_x, subtitle_y), subtitle, font=subtitle_font, fill=SIGNATURE_COLOR)

    # Add decorative line under title
    line_y = subtitle_y + FONT_SIZE + 30
    line_start = CANVAS_WIDTH // 4
    line_end = 3 * CANVAS_WIDTH // 4
    draw.line([line_start, line_y, line_end, line_y], fill=TITLE_COLOR, width=2)

    # Render main text
    print("Rendering main letter text...")
    text_y = line_y + 60
    text_x = MARGIN_LEFT
    available_width = CANVAS_WIDTH - MARGIN_LEFT - MARGIN_RIGHT

    # Process paragraphs
    paragraphs = LETTER_TEXT.strip().split("\n\n")

    for para in paragraphs:
        # Word wrap for readability
        lines = textwrap.wrap(para, width=WRAP_WIDTH)

        # Render each line
        for line in lines:
            draw.text((text_x, text_y), line, font=main_font, fill=TEXT_COLOR)
            text_y += int(FONT_SIZE * LINE_SPACING)

        # Paragraph spacing
        text_y += PARAGRAPH_SPACING

    # Add signature section
    print("Adding signature...")
    text_y += SIGNATURE_SPACING

    # Position signature on the right
    signature_x = CANVAS_WIDTH - MARGIN_RIGHT - 350
    signature_y = text_y

    # Create signature on separate layer for rotation
    sign_layer = Image.new("RGBA", img.size, (0,0,0,0))
    sd = ImageDraw.Draw(sign_layer)

    signature_lines = SIGNATURE_TEXT.strip().split("\n")
    current_y = signature_y

    for line in signature_lines:
        if not line.strip():
            current_y += int(SIGNATURE_FONT_SIZE * 0.4)
            continue
        sd.text((signature_x, current_y), line, font=signature_font, fill=SIGNATURE_COLOR)
        current_y += int(SIGNATURE_FONT_SIZE * 0.9)

    # Rotate signature slightly for handwritten feel
    sign_layer = sign_layer.rotate(SIGNATURE_ROTATION, 
                                   resample=Image.BICUBIC, 
                                   center=(signature_x, signature_y))

    img = Image.alpha_composite(img.convert("RGBA"), sign_layer).convert("RGB")

    # Add final effects
    if ADD_DECORATIVE_BORDER:
        img = add_decorative_border(img)

    if ADD_VIGNETTE:
        img = add_vignette(img, intensity=0.6)

    # Add discrete watermark
    timestamp = datetime.now().strftime("%Y")
    footer_font = ImageFont.truetype(FONT_PATH, 16)
    draw = ImageDraw.Draw(img)
    watermark = f"© {timestamp} ProfitPal - Dennis J."
    draw.text((MARGIN_LEFT, CANVAS_HEIGHT - 40), watermark, 
              font=footer_font, fill=(100, 90, 80))

    return img

def save_files(img):
    """Save image in multiple formats"""
    if img is None:
        print("❌ Cannot save - image generation failed")
        return

    print(f"💾 Saving PNG: {OUTPUT_PNG}")
    img.save(OUTPUT_PNG, "PNG", dpi=(300, 300), optimize=True)

    print(f"💾 Saving PDF: {OUTPUT_PDF}")
    img.convert("RGB").save(OUTPUT_PDF, "PDF", resolution=300.0, optimize=True)

    print("✅ Files saved successfully!")
    print(f"📁 PNG file: {OUTPUT_PNG} (for web)")
    print(f"📁 PDF file: {OUTPUT_PDF} (for print)")

def main():
    """Main execution function"""
    print("💎 ProfitPal Calligraphy Generator v1.0 💎")
    print("=" * 50)

    # Generate the calligraphy
    img = render_profitpal_letter()

    if img:
        # Save files
        save_files(img)

        print("\n🔥 Generation Complete! 🔥")
        print("📋 Usage tips:")
        print("  • PNG: Perfect for website backgrounds")  
        print("  • PDF: High-quality printing")
        print("  • 300 DPI: Professional print quality")
        print("\n💡 Next steps:")
        print("  • Use as introduction.html background")
        print("  • Print for premium marketing materials")
        print("  • Integrate into presentation slides")
    else:
        print("❌ Generation failed. Check font path and try again.")

if __name__ == "__main__":
    main()