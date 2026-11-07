"""Render the architecture diagram used in the README."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

S = 2
NAVY = (0x12, 0x35, 0x5B)
TEAL = (0x0E, 0x7C, 0x86)
INK = (0x1C, 0x28, 0x33)
MUTED = (0x5C, 0x6B, 0x7A)
PAPER = (0xF6, 0xF7, 0xF9)
WHITE = (255, 255, 255)
LINE = (0xD5, 0xDC, 0xE3)
SOFT = (0xE7, 0xF4, 0xF5)

W = 1400
H = 2100
MX = 48
CONTENT = W - MX * 2


def px(n: float) -> int:
    return int(round(n * S))


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf"
    return ImageFont.truetype(path, px(size))


F_TITLE = load_font(22, True)
F_NODE = load_font(18, True)
F_BODY = load_font(16)
F_SMALL = load_font(15)
F_LABEL = load_font(13, True)


def main() -> Path:
    image = Image.new("RGB", (px(W), px(H)), PAPER)
    draw = ImageDraw.Draw(image)
    y = 36.0

    def text(value: str, font: ImageFont.FreeTypeFont, x: float, top: float, color: tuple[int, int, int]) -> None:
        box = font.getbbox(value)
        draw.text((px(x) - box[0], px(top) - box[1]), value, font=font, fill=color)

    def center(value: str, font: ImageFont.FreeTypeFont, x: float, top: float, w: float, h: float, color: tuple[int, int, int]) -> None:
        box = font.getbbox(value)
        tw, th = box[2] - box[0], box[3] - box[1]
        tx = px(x) + (px(w) - tw) / 2 - box[0]
        ty = px(top) + (px(h) - th) / 2 - box[1]
        draw.text((tx, ty), value, font=font, fill=color)

    def round_box(x: float, top: float, w: float, h: float, fill: tuple[int, int, int], outline: tuple[int, int, int] | None = LINE, radius: float = 14) -> None:
        draw.rounded_rectangle(
            [px(x), px(top), px(x + w), px(top + h)],
            radius=px(radius),
            fill=fill,
            outline=outline,
            width=px(2) if outline else 1,
        )

    def bar(x: float, top: float, h: float) -> None:
        draw.rectangle([px(x), px(top + 12), px(x + 6), px(top + h - 12)], fill=TEAL)

    def arrow_down(x: float, top: float, bottom: float) -> None:
        draw.line([(px(x), px(top)), (px(x), px(bottom - 8))], fill=TEAL, width=px(3))
        draw.polygon(
            [(px(x - 7), px(bottom - 9)), (px(x + 7), px(bottom - 9)), (px(x), px(bottom))],
            fill=TEAL,
        )

    def arrow_right(x1: float, x2: float, mid: float) -> None:
        draw.line([(px(x1), px(mid)), (px(x2 - 8), px(mid))], fill=TEAL, width=px(3))
        draw.polygon(
            [(px(x2 - 9), px(mid - 6)), (px(x2 - 9), px(mid + 6)), (px(x2), px(mid))],
            fill=TEAL,
        )

    def section(label: str, top: float) -> float:
        text(label.upper(), F_LABEL, MX, top, TEAL)
        return top + 24

    def card(x: float, top: float, w: float, h: float, title: str, lines: list[str], fill: tuple[int, int, int] = WHITE) -> None:
        round_box(x, top, w, h, fill)
        bar(x, top, h)
        text(title, F_NODE, x + 22, top + 16, NAVY)
        line_y = top + 46
        for line in lines:
            text(line, F_SMALL, x + 22, line_y, MUTED)
            line_y += 22

    def chip_row(labels: list[str], top: float, h: float = 64, fill: tuple[int, int, int] = WHITE, fg: tuple[int, int, int] = NAVY) -> float:
        gap = 28
        width = 300
        total = len(labels) * width + (len(labels) - 1) * gap
        left = (W - total) / 2
        for index, label in enumerate(labels):
            x = left + index * (width + gap)
            round_box(x, top, width, h, fill, radius=12)
            center(label, F_NODE, x, top, width, h, fg)
            if index < len(labels) - 1:
                arrow_right(x + width + 4, x + width + gap - 2, top + h / 2)
        return top + h

    # Employee
    pill_w, pill_h = 280, 58
    pill_x = (W - pill_w) / 2
    round_box(pill_x, y, pill_w, pill_h, NAVY, outline=None, radius=29)
    center("Employee", F_TITLE, pill_x, y, pill_w, pill_h, WHITE)
    arrow_down(W / 2, y + pill_h + 4, y + pill_h + 34)
    y += pill_h + 46

    y = section("Frontend", y)
    card(MX, y, CONTENT, 96, "Streamlit", ["Chat, citations, and the live activity panel.", "The browser talks only to FastAPI."])
    arrow_down(W / 2, y + 100, y + 130)
    y += 142

    y = section("Backend", y)
    gap = 18
    col_w = (CONTENT - 2 * gap) / 3
    backend = [
        ("FastAPI", ["Async chat over server-sent events.", "Forwards each agent step live."]),
        ("Access control", ["Login, role check, and a token bucket.", "A denied call never starts the graph."]),
        ("SQLite", ["Session transcript and a short summary.", "Owned by the signed-in user."]),
    ]
    for index, (title, lines) in enumerate(backend):
        card(MX + index * (col_w + gap), y, col_w, 112, title, lines)
    arrow_down(W / 2, y + 116, y + 146)
    y += 158

    y = section("Agent", y)
    panel_top = y
    panel_h = 640
    round_box(MX, panel_top, CONTENT, panel_h, WHITE)
    text("LangGraph", F_TITLE, MX + 24, panel_top + 18, NAVY)
    text("input_guard runs first. memory_load reads SQLite. The supervisor then picks one route.", F_BODY, MX + 24, panel_top + 52, MUTED)

    chip_row(["input_guard", "memory_load", "supervisor"], panel_top + 96)
    text("ONE ROUTE", F_LABEL, MX + 24, panel_top + 184, TEAL)

    route_y = panel_top + 214
    route_gap = 14
    route_w = (CONTENT - 48 - 4 * route_gap) / 5
    routes = [
        ("retrieval_agent", ["Ranked chunks.", "analysis_agent", "can count them."]),
        ("research_agent", ["Catalog, plan,", "and batches in", "the sandbox."]),
        ("mcp_agent", ["Directory, catalog,", "and operational", "tickets."]),
        ("approval_request", ["Pauses before", "approval_wait.", "Then reindex."]),
        ("response_agent", ["Also the direct", "route for a", "simple reply."]),
    ]
    for index, (title, lines) in enumerate(routes):
        x = MX + 24 + index * (route_w + route_gap)
        round_box(x, route_y, route_w, 148, SOFT, outline=LINE, radius=12)
        text(title, F_LABEL, x + 12, route_y + 12, TEAL)
        line_y = route_y + 40
        for line in lines:
            text(line, F_SMALL, x + 12, line_y, INK)
            line_y += 24

    text("EVERY ROUTE JOINS HERE", F_LABEL, MX + 24, panel_top + 384, TEAL)
    chip_row(["response_agent", "output_guard", "memory_save"], panel_top + 416)
    text("memory_save writes the transcript back to SQLite. The graph pauses before approval_wait.", F_SMALL, MX + 24, panel_top + 500, MUTED)
    text("Approving resumes the same checkpoint. A rejected reindex still returns an answer.", F_SMALL, MX + 24, panel_top + 526, MUTED)

    y = panel_top + panel_h + 16
    arrow_down(W / 2, y, y + 28)
    y += 40

    y = section("Tools and knowledge", y)
    tools = [
        ("Hybrid index", ["BM25 plus local vectors.", "Access is filtered before scoring."]),
        ("Python sandbox", ["Planner code only. No user code.", "AST limits, one-second timeout."]),
        ("MCP server", ["JSON-RPC on port 8100.", "Same data in-process if it is down."]),
    ]
    for index, (title, lines) in enumerate(tools):
        card(MX + index * (col_w + gap), y, col_w, 112, title, lines)
    y += 136

    y = section("Optional, only with a key", y)
    dash_top = y
    dash_h = 168
    # Dashed outline, drawn as short segments on a rectangle.
    x1, y1, x2, y2 = px(MX), px(dash_top), px(MX + CONTENT), px(dash_top + dash_h)
    dash, gap_px = px(12), px(8)
    def segments(start: int, end: int, fixed: int, horizontal: bool) -> None:
        cursor = start
        while cursor < end:
            stop = min(cursor + dash, end)
            if horizontal:
                draw.line([(cursor, fixed), (stop, fixed)], fill=TEAL, width=px(2))
            else:
                draw.line([(fixed, cursor), (fixed, stop)], fill=TEAL, width=px(2))
            cursor += dash + gap_px

    segments(x1, x2, y1, True)
    segments(x1, x2, y2, True)
    segments(y1, y2, x1, False)
    segments(y1, y2, x2, False)

    optional = [
        ("Pinecone", ["Dense scores merge into", "local hits. Quoted text", "stays in the local index."]),
        ("gpt-4o-mini", ["Rewrites a grounded draft.", "It does not choose tools", "or grant a role."]),
        ("LangSmith", ["Traces the run, each node,", "and the model call when", "tracing and a key are set."]),
    ]
    opt_w = (CONTENT - 48 - 2 * gap) / 3
    for index, (title, lines) in enumerate(optional):
        x = MX + 24 + index * (opt_w + gap)
        round_box(x, dash_top + 20, opt_w, 128, WHITE)
        text(title, F_NODE, x + 16, dash_top + 34, NAVY)
        line_y = dash_top + 66
        for line in lines:
            text(line, F_SMALL, x + 16, line_y, MUTED)
            line_y += 22

    bottom = int(dash_top + dash_h + 36)
    image = image.crop((0, 0, px(W), px(bottom)))
    destination = Path(__file__).resolve().parents[1] / "docs" / "architecture.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, "PNG", optimize=True)
    return destination


if __name__ == "__main__":
    print(main())
