"""生成架构流程图 docs/figures/architecture.png。

这个脚本不参与实验运行，只负责出图；放在 docs/figures/ 下是为了让图可追溯、可重画。
依赖 Pillow（项目 venv 里没有，用 DSH 自带运行时）：

    & "C:\\Users\\lenovo\\.dsh\\dsh-runtimes\\dsh-primary-runtime\\dependencies\\python\\python.exe" docs/figures/architecture.py

修改布局时先改下面的坐标常量，再重新渲染。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1600, 1200
S = 2  # 超采样倍数
FONT = "C:/Windows/Fonts/msyh.ttc"
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"

C_BG = "#FFFFFF"
C_CONTAINER = "#F7F9FC"
C_CONTAINER_BORDER = "#C9D3E3"
C_DATA = "#FFF7E6"
C_DATA_BORDER = "#D9A441"
C_AGENT = "#EAF2FF"
C_AGENT_BORDER = "#4A7FE8"
C_MEM = "#FDF0E4"
C_MEM_BORDER = "#D9822B"
C_TOOL = "#E9F7EE"
C_TOOL_BORDER = "#3FA45B"
C_DECISION = "#FFF0EE"
C_DECISION_BORDER = "#D9534F"
C_LOG = "#F1EFFA"
C_LOG_BORDER = "#6B5BD2"
C_FUTURE = "#9AA5B1"
C_TEXT = "#1F2933"
C_MUTED = "#5C6B7A"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT, size * S)


def p(v: float) -> int:
    return int(round(v * S))


def text_size(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont) -> tuple[int, int]:
    box = draw.multiline_textbbox((0, 0), text, font=f, spacing=p(6), align="center")
    return box[2] - box[0], box[3] - box[1]


def center_text(draw, cx, cy, text, f, fill=C_TEXT):
    tw, th = text_size(draw, text, f)
    draw.multiline_text((cx - tw / 2, cy - th / 2), text, font=f, fill=fill, spacing=p(6), align="center")


def box(draw, x, y, w, h, text, *, fill, outline, f, radius=10, width=2, text_fill=C_TEXT):
    draw.rounded_rectangle([p(x), p(y), p(x + w), p(y + h)], radius=p(radius), fill=fill, outline=outline, width=p(width))
    center_text(draw, p(x + w / 2), p(y + h / 2), text, f, text_fill)


def dashed_box(draw, x, y, w, h, text, *, f, radius=10):
    # Pillow 没有虚线圆角矩形，用细线 + 虚线边框近似
    draw.rounded_rectangle([p(x), p(y), p(x + w), p(y + h)], radius=p(radius), fill="#FAFAFA", outline=C_FUTURE, width=p(2))
    center_text(draw, p(x + w / 2), p(y + h / 2), text, f, C_MUTED)


def arrow(draw, pts, *, color=C_MUTED, width=2.5, head=9, dashed=False):
    pts = [(p(x), p(y)) for x, y in pts]
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        if dashed:
            _dashed_line(draw, x1, y1, x2, y2, color, width)
        else:
            draw.line([x1, y1, x2, y2], fill=color, width=p(width))
    x1, y1 = pts[-2]
    x2, y2 = pts[-1]
    _head(draw, x1, y1, x2, y2, color, head)


def _dashed_line(draw, x1, y1, x2, y2, color, width, dash=10, gap=7):
    import math

    length = math.hypot(x2 - x1, y2 - y1)
    if length == 0:
        return
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    pos = 0
    while pos < length:
        end = min(pos + dash * S, length)
        draw.line([x1 + ux * pos, y1 + uy * pos, x1 + ux * end, y1 + uy * end], fill=color, width=p(width))
        pos = end + gap * S


def _head(draw, x1, y1, x2, y2, color, size):
    import math

    ang = math.atan2(y2 - y1, x2 - x1)
    s = size * S
    left = (x2 - s * math.cos(ang - math.pi / 7), y2 - s * math.sin(ang - math.pi / 7))
    right = (x2 - s * math.cos(ang + math.pi / 7), y2 - s * math.sin(ang + math.pi / 7))
    draw.polygon([(x2, y2), left, right], fill=color)


def diamond(draw, cx, cy, w, h, text, f):
    pts = [(p(cx), p(cy - h / 2)), (p(cx + w / 2), p(cy)), (p(cx), p(cy + h / 2)), (p(cx - w / 2), p(cy))]
    draw.polygon(pts, fill=C_DECISION, outline=C_DECISION_BORDER, width=p(2))
    center_text(draw, p(cx), p(cy), text, f)


def main() -> None:
    img = Image.new("RGB", (W * S, H * S), C_BG)
    draw = ImageDraw.Draw(img)

    f_title = font(26, True)
    f_section = font(19, True)
    f_box = font(18)
    f_small = font(14)
    f_tiny = font(13)

    # 标题
    draw.text((p(40), p(28)), "多轮交互 LLM Agent 隐私泄露评估平台：执行流程", font=f_title, fill=C_TEXT)
    draw.text((p(40), p(66)), "实线 = 已实现（P1–P2）    虚线 = 尚未实现（P3/P5）", font=f_small, fill=C_MUTED)

    # ---------- 左：输入 ----------
    draw.text((p(40), p(112)), "输入数据", font=f_section, fill=C_MUTED)
    in_w, in_h = 300, 92
    inputs = [
        (150, "场景 YAML", "威胁模型 · 用户脚本 · mock"),
        (270, "人物 JSON", "敏感字段 · 类别 · 敏感级"),
        (390, "记忆 JSONL", "敏感值 · 标签 · 归属"),
    ]
    for y, title, sub in inputs:
        draw.rounded_rectangle([p(40), p(y), p(40 + in_w), p(y + in_h)], radius=p(10), fill=C_DATA, outline=C_DATA_BORDER, width=p(2))
        draw.text((p(40 + in_w / 2), p(y + 26)), title, font=font(18, True), fill=C_TEXT, anchor="mm")
        draw.text((p(40 + in_w / 2), p(y + 60)), sub, font=f_small, fill=C_MUTED, anchor="mm")

    # 汇入竖线
    bus_x = 372
    for y, _, _ in inputs:
        draw.line([p(40 + in_w), p(y + in_h / 2), p(bus_x), p(y + in_h / 2)], fill=C_MUTED, width=p(2))
    draw.line([p(bus_x), p(150 + in_h / 2), p(bus_x), p(390 + in_h / 2)], fill=C_MUTED, width=p(2))
    arrow(draw, [(bus_x, 276), (bus_x + 28, 276)])

    # ---------- 中：单轮循环 ----------
    cx0, cy0, cw, ch = 400, 150, 760, 860
    draw.rounded_rectangle([p(cx0), p(cy0), p(cx0 + cw), p(cy0 + ch)], radius=p(18), fill=C_CONTAINER, outline=C_CONTAINER_BORDER, width=p(2))
    draw.text((p(cx0 + 24), p(cy0 + 16)), "单轮 Agent 循环  T = 1 … N", font=f_section, fill=C_MUTED)

    mid = cx0 + cw / 2  # 780

    y1 = 226
    box(draw, mid - 210, y1, 420, 64, "用户消息（脚本，非 LLM 扮演）", fill=C_AGENT, outline=C_AGENT_BORDER, f=f_box)
    y2 = 326
    box(draw, mid - 230, y2, 460, 64, "记忆检索 BM25 · top-k", fill=C_MEM, outline=C_MEM_BORDER, f=f_box)
    y3 = 426
    box(draw, mid - 290, y3, 580, 76, "组装上下文\nsystem + 记忆块 + 历史 + 当前输入", fill=C_AGENT, outline=C_AGENT_BORDER, f=f_box)
    y4 = 546
    box(draw, mid - 235, y4, 470, 64, "调用 LLM（deepseek-flash）", fill=C_AGENT, outline=C_AGENT_BORDER, f=f_box)

    # 判断菱形
    dy = 680
    diamond(draw, mid, dy, 230, 104, "tool_calls?", f_box)

    # 工具分支
    tool_x, tool_y, tool_w, tool_h = 890, dy - 32, 200, 64
    box(draw, tool_x, tool_y, tool_w, tool_h, "执行工具", fill=C_TOOL, outline=C_TOOL_BORDER, f=f_box)

    y6 = 800
    box(draw, mid - 210, y6, 420, 64, "最终回答（assistant）", fill=C_AGENT, outline=C_AGENT_BORDER, f=f_box)
    y7 = 900
    box(draw, mid - 180, y7, 360, 64, "追加到对话历史", fill=C_AGENT, outline=C_AGENT_BORDER, f=f_box)

    # 主链箭头
    arrow(draw, [(mid, y1 + 64), (mid, y2)])
    arrow(draw, [(mid, y2 + 64), (mid, y3)])
    arrow(draw, [(mid, y3 + 76), (mid, y4)])
    arrow(draw, [(mid, y4 + 64), (mid, dy - 52)])
    arrow(draw, [(mid, dy + 52), (mid, y6)])
    arrow(draw, [(mid, y6 + 64), (mid, y7)])

    # 工具环路：菱形右顶点 → 工具 → 回 LLM
    arrow(draw, [(mid + 115, dy), (tool_x, dy)])
    draw.line([p(tool_x + tool_w), p(dy), p(tool_x + tool_w + 22), p(dy)], fill=C_MUTED, width=p(2.5))
    arrow(draw, [(tool_x + tool_w + 22, dy), (tool_x + tool_w + 22, y4 + 32), (mid + 235, y4 + 32)])
    draw.text((p(tool_x + tool_w + 30), p(dy - 20)), "是", font=f_small, fill=C_MUTED)

    # 否 标签
    draw.text((p(mid + 12), p(dy + 56)), "否", font=f_small, fill=C_MUTED)

    # 外循环：追加历史 → 用户消息
    loop_x = cx0 + 46
    arrow(draw, [(mid - 180, y7 + 32), (loop_x, y7 + 32), (loop_x, y1 + 32), (mid - 210, y1 + 32)])
    draw.text((p(loop_x + 10), p((y1 + y7) / 2)), "T < N", font=f_small, fill=C_MUTED)

    # ---------- 右：日志 ----------
    draw.text((p(1230), p(150)), "运行产物", font=f_section, fill=C_MUTED)
    log_x, log_w = 1230, 330
    draw.rounded_rectangle([p(log_x), p(186), p(log_x + log_w), p(320)], radius=p(10), fill=C_LOG, outline=C_LOG_BORDER, width=p(2))
    draw.text((p(log_x + log_w / 2), p(216)), "trace.jsonl", font=font(18, True), fill=C_TEXT, anchor="mm")
    draw.text((p(log_x + log_w / 2), p(250)), "每行一个事件", font=f_small, fill=C_MUTED, anchor="mm")
    draw.text((p(log_x + log_w / 2), p(282)), "visibility · provenance · usage", font=f_small, fill=C_MUTED, anchor="mm")

    draw.rounded_rectangle([p(log_x), p(350), p(log_x + log_w), p(470)], radius=p(10), fill=C_LOG, outline=C_LOG_BORDER, width=p(2))
    draw.text((p(log_x + log_w / 2), p(380)), "meta.json", font=font(18, True), fill=C_TEXT, anchor="mm")
    draw.text((p(log_x + log_w / 2), p(412)), "模型 · 参数 · git commit", font=f_small, fill=C_MUTED, anchor="mm")
    draw.text((p(log_x + log_w / 2), p(444)), "prompt / 记忆模板版本", font=f_small, fill=C_MUTED, anchor="mm")

    arrow(draw, [(cx0 + cw, 300), (log_x, 300)])
    draw.text((p(cx0 + cw + 14), p(272)), "写入", font=f_tiny, fill=C_MUTED)

    # 攻击者（虚线）
    dashed_box(draw, log_x, 540, log_w, 120, "攻击者（第三阶段）\n只读 visibility 含\nattacker 的事件", f=f_small)
    arrow(draw, [(mid + 210, y6 + 32), (1205, y6 + 32), (1205, 620), (log_x, 620)], dashed=True, color=C_FUTURE)

    # ---------- 底部：未实现 ----------
    dashed_box(draw, cx0, 1050, cw, 110, "第三阶段：攻击者 · 直接泄露判定 · 恢复/推断 · 累积指标\n第五阶段：风险状态 · 分级防御 · 披露账本", f=f_small)

    img = img.resize((W, H), Image.LANCZOS)
    out = Path(__file__).with_name("architecture.png")
    img.save(out, "PNG")
    print(f"saved: {out}  {img.size[0]}x{img.size[1]}")


if __name__ == "__main__":
    main()
