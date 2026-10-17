"""Erzeugt das Programmsymbol (PNG + ICO): aufgeschlagenes Buch mit Übersetzungspfeil, Tintenblau auf Papierton."""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "src" / "quellenuebersetzer" / "resources"
INK, PAPER, ACCENT = (31, 58, 95, 255), (244, 239, 230, 255), (179, 92, 0, 255)


def draw(size: int = 1024) -> Image.Image:
    s = size / 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([40 * s, 40 * s, 984 * s, 984 * s], radius=200 * s, fill=INK)
    # aufgeschlagenes Buch
    d.polygon([(512 * s, 330 * s), (200 * s, 270 * s), (200 * s, 720 * s), (512 * s, 780 * s)], fill=PAPER)
    d.polygon([(512 * s, 330 * s), (824 * s, 270 * s), (824 * s, 720 * s), (512 * s, 780 * s)], fill=(230, 222, 207, 255))
    for i in range(5):  # Zeilen links (Quelle) und rechts (Übersetzung)
        y = 370 + i * 70
        d.line([(250 * s, (y - 8) * s), (460 * s, (y + 32) * s)], fill=(110, 102, 90, 255), width=int(18 * s))
        d.line([(564 * s, (y + 32) * s), (774 * s, (y - 8) * s)], fill=INK, width=int(18 * s))
    # Übersetzungspfeil
    d.ellipse([408 * s, 700 * s, 616 * s, 908 * s], fill=ACCENT)
    d.line([(455 * s, 804 * s), (560 * s, 804 * s)], fill=PAPER, width=int(30 * s))
    d.polygon([(555 * s, 760 * s), (595 * s, 804 * s), (555 * s, 848 * s)], fill=PAPER)
    return img


if __name__ == "__main__":
    big = draw(1024)
    big.resize((256, 256), Image.LANCZOS).save(OUT / "icon.png")
    big.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("geschrieben:", OUT / "icon.ico")
