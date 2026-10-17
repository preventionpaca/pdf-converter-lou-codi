from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "lou_codi_pdf_converter" / "assets"


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def build() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    navy, pale, red, yellow = "#193B66", "#F7FAFD", "#C8202F", "#FFD21A"
    draw.rounded_rectangle((35, 14, 221, 242), radius=18, fill=pale, outline=navy, width=10)
    draw.polygon(((171, 14), (221, 64), (171, 64)), fill="#DCEBFA", outline=navy)
    draw.line((171, 14, 171, 64, 221, 64), fill=navy, width=8)
    title_font = font(54)
    positions = (("C", red, 34), ("O", yellow, 101), ("D", red, 168))
    for letter, color, y in positions:
        box = draw.textbbox((0, 0), letter, font=title_font)
        x = 128 - (box[2] - box[0]) / 2
        draw.text((x, y), letter, font=title_font, fill=color, stroke_width=2, stroke_fill=navy)
    draw.line((121, 99, 133, 90), fill=yellow, width=6)
    png = ASSETS / "lou-codi-document.png"
    ico = ASSETS / "lou-codi-document.ico"
    image.save(png, "PNG", optimize=True)
    image.save(ico, "ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    build()
