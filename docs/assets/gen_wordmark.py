#!/usr/bin/env python3
"""生成「南评」字标 SVG。

把思源宋体的字形转成矢量路径，这样 README 在任何机器上渲染都一致
（GitHub 用访客本地字体，多数人没装思源宋体；而 Markdown 里的
style 属性会被 GitHub 过滤，纯文字也没法控制字号）。

依赖（不进 requirements.txt，属一次性构建工具）：
    python3 -m pip install --target /tmp/ft-lib fonttools brotli

字体需本机已安装 SourceHanSerifSC-VF.otf（思源宋体 SC 变量版）。

用法：
    PYTHONPATH=/tmp/ft-lib python3 docs/assets/gen_wordmark.py
"""

import subprocess
import tempfile
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

# --- 设计参数（对应原 README 内联 CSS）---
TEXT = "南评"
FONT_PX = 72  # font-size: 72px
TRACKING = 8  # letter-spacing: 8px
WEIGHT = 700  # font-weight: 700
PAD = 8  # 四周留白(px)
COLOR = "#7B2D8E"  # 品牌紫

FONT_SRC = Path.home() / "Library/Fonts/SourceHanSerifSC-VF.otf"
OUT = Path(__file__).parent / "wordmark.svg"


def subset_font(src: Path, text: str, dest: Path) -> None:
    """先子集化再实例化——整个 CJK 变量字体有 4 万多字形，直接实例化会跑几分钟。"""
    subprocess.run(
        [
            "python3", "-m", "fontTools.subset", str(src),
            f"--text={text}",
            f"--output-file={dest}",
            "--drop-tables+=GSUB,GPOS,BASE,JSTF,DSIG",
            "--no-hinting",
        ],
        check=True,
    )


def main() -> None:
    """提取字形路径、计算画布尺寸与变换矩阵，写出 SVG。"""
    if not FONT_SRC.exists():
        raise SystemExit(f"找不到字体：{FONT_SRC}")

    with tempfile.TemporaryDirectory() as tmp:
        sub = Path(tmp) / "subset.otf"
        subset_font(FONT_SRC, TEXT, sub)

        font = TTFont(sub)
        instantiateVariableFont(font, {"wght": WEIGHT}, inplace=True)

        cmap = font.getBestCmap()
        glyph_set = font.getGlyphSet()
        hmtx = font["hmtx"]
        scale = FONT_PX / font["head"].unitsPerEm
        tracking_units = TRACKING / scale

        glyphs, cursor = [], 0.0
        for char in TEXT:
            name = cmap[ord(char)]
            path_pen = SVGPathPen(glyph_set)
            glyph_set[name].draw(path_pen)
            bounds_pen = BoundsPen(glyph_set)
            glyph_set[name].draw(bounds_pen)
            glyphs.append(
                {
                    "x": cursor,
                    "d": path_pen.getCommands(),
                    "bounds": bounds_pen.bounds,
                }
            )
            cursor += hmtx[name][0] + tracking_units

    # 墨迹包围盒 → 画布尺寸；SVG 的 Y 轴朝下，故 scale 的 y 取负翻转
    xs = [g["x"] + g["bounds"][0] for g in glyphs] + [g["x"] + g["bounds"][2] for g in glyphs]
    ys = [g["bounds"][1] for g in glyphs] + [g["bounds"][3] for g in glyphs]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)

    width = round((x1 - x0) * scale + 2 * PAD)
    height = round((y1 - y0) * scale + 2 * PAD)
    tx = PAD - x0 * scale
    ty = PAD + y1 * scale

    paths = "\n".join(
        f'    <path transform="translate({g["x"]:.0f} 0)" d="{g["d"]}"/>'
        if g["x"]
        else f'    <path d="{g["d"]}"/>'
        for g in glyphs
    )

    OUT.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"'
        f' viewBox="0 0 {width} {height}" role="img" aria-label="{TEXT}">\n'
        f"  <title>{TEXT}</title>\n"
        f"  <!-- 由 docs/assets/gen_wordmark.py 生成，请勿手改。\n"
        f"       Source Han Serif SC (思源宋体) wght={WEIGHT}，{FONT_PX}px，字距 {TRACKING}px。\n"
        f"       字形已转为矢量路径，不依赖访客本地字体。 -->\n"
        f'  <g fill="{COLOR}" transform="translate({tx:.3f} {ty:.3f})'
        f' scale({scale} -{scale})">\n'
        f"{paths}\n"
        f"  </g>\n"
        f"</svg>\n"
    )
    print(f"已写出 {OUT}  ({width}x{height})")


if __name__ == "__main__":
    main()
