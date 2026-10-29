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
    red = "#D71920"
    # White document with a large COD label, kept deliberately simple so the
    # file type remains recognisable in 16 px explorer views.
    draw.rounded_rectangle((29, 12, 227, 244), radius=18, fill="white", outline=red, width=10)
    draw.polygon(((173, 12), (227, 66), (173, 66)), fill="#FFE5E6", outline=red)
    draw.line((173, 12, 173, 66, 227, 66), fill=red, width=8)
    title_font = font(62)
    label = "COD"
    box = draw.textbbox((0, 0), label, font=title_font)
    x = 128 - (box[2] - box[0]) / 2
    y = 112 - (box[3] - box[1]) / 2
    draw.text((x, y), label, font=title_font, fill=red)
    draw.line((62, 166, 194, 166), fill=red, width=7)
    draw.line((62, 190, 174, 190), fill="#E78B8F", width=6)
    draw.line((62, 214, 151, 214), fill="#E78B8F", width=6)
    png = ASSETS / "lou-codi-document.png"
    ico = ASSETS / "lou-codi-document.ico"
    icns = ASSETS / "lou-codi-document.icns"
    image.save(png, "PNG", optimize=True)
    image.save(ico, "ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    image.resize((1024, 1024), Image.Resampling.LANCZOS).save(
        icns,
        "ICNS",
        sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)],
    )
    for size in (16, 24, 32, 48, 64, 128, 256):
        image.resize((size, size), Image.Resampling.LANCZOS).save(
            ASSETS / f"lou-codi-document-{size}.png", "PNG", optimize=True
        )


if __name__ == "__main__":
    build()
