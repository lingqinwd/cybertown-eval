"""PPT 数据图 v2：统一配色与字体，去掉多余装饰，改用更干净的哑铃图/堆叠条。

设计约束（针对上一版"丑"的具体问题）：
1. 上一版 fig4 的文字标注超出画布 → 改用哑铃图，数值放在轴内侧
2. 上一版 fig3 纵向堆叠在 16:9 页面里偏窄 → 改横向堆叠，占比一目了然
3. 上一版 fig2 两根柱子都在 100%，信息量低 → 改哑铃图，端点直接标 0% / 100%
4. 统一用阿里巴巴普惠体 3.0 65 Medium（与 PPT 正文一致），英文数字走同一字体保证基线一致
5. 只保留水平浅虚线网格，无 3D、无阴影、无渐变

输出：docs/images/fig{1..4}_*.png（dpi=200，16:9 友好尺寸）
"""

import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

REPO = pathlib.Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "images"
OUT.mkdir(parents=True, exist_ok=True)

# ---------------- 字体：图内统一用阿里巴巴普惠体 3.0 65 Medium
# 说明：图表是位图，混排会破坏基线；英文 Times New Roman 的规则只作用于 PPT 正文
# matplotlib >= 3.6 支持字体回退链：拉丁字符取第一个字体，CJK 回退到下一个
ALIBABA = [
    pathlib.Path.home() / "AppData/Local/Microsoft/Windows/Fonts/AlibabaPuHuiTi-3-65-Medium.ttf",
    pathlib.Path(r"C:\Windows\Fonts\AlibabaPuHuiTi-3-65-Medium.ttf"),
]
_loaded = []
for cand in ALIBABA:
    if cand.exists():
        font_manager.fontManager.addfont(str(cand))
        _loaded.append(cand.name)
        break
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Alibaba PuHuiTi 3.0", "SimHei"]
print(f"[font] Times New Roman + Alibaba PuHuiTi 3.0 (font file: {_loaded or '未找到，回退 SimHei'})")
plt.rcParams["axes.unicode_minus"] = False

# ---------------- 统一色板
INK = "#1F3352"        # 主色（深蓝）
ACCENT = "#2F6FD0"     # 强调蓝
MUTED = "#9AA9BA"      # 关/基线
BAD = "#D64545"        # 被拦下 / 代价
GOOD = "#2E9E5B"       # 通过 / 收益
WARN = "#E8952E"
GRID = "#DDE3EA"

plt.rcParams.update({
    "font.size": 13,
    "axes.edgecolor": GRID,
    "axes.labelcolor": INK,
    "text.color": INK,
    "xtick.color": INK,
    "ytick.color": INK,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
})


def style(ax, grid_axis="y"):
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.grid(axis=grid_axis, color=GRID, linestyle="--", linewidth=0.9, alpha=0.9)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)


def save(fig, name):
    path = OUT / name
    fig.savefig(path, dpi=200, bbox_inches="tight", pad_inches=0.28, facecolor="white")
    plt.close(fig)
    print(f"[OK] {name}  {path.stat().st_size // 1024} KB")


# ============================================================ 图 1
def fig1():
    fig, ax = plt.subplots(figsize=(10.0, 5.5))
    groups = ["云端 DeepSeek", "端侧 Qwen2.5-1.5B"]
    off = [1542, 861]
    on = [4810, 1078]
    x = [0, 1]
    w = 0.30

    ax.bar([i - w / 2 - 0.01 for i in x], off, w, color=MUTED, label="记忆关", zorder=2)
    ax.bar([i + w / 2 + 0.01 for i in x], on, w, color=ACCENT, label="记忆开", zorder=2)

    for i, (a, b) in enumerate(zip(off, on)):
        ax.text(i - w / 2 - 0.01, a + 90, f"{a}", ha="center", va="bottom",
                fontsize=13, color=INK)
        ax.text(i + w / 2 + 0.01, b + 90, f"{b}", ha="center", va="bottom",
                fontsize=13, color=ACCENT, fontweight="bold")

    # 倍数：画在两根柱子上方，用短横线 + 文本，避免箭头乱指
    for i, (a, b, mult, color) in enumerate(
            [(0, 0, "3.12×", BAD), (1, 1, "1.25×", GOOD)]):
        ax.plot([i - w / 2 - 0.01, i + w / 2 + 0.01], [5300, 5300],
                color=color, linewidth=1.4, zorder=3)
        ax.text(i, 5420, mult, ha="center", va="bottom", fontsize=19,
                color=color, fontweight="bold")

    ax.set_xticks(x, groups, fontsize=14)
    ax.set_ylabel("平均延迟（ms）", fontsize=13)
    ax.set_ylim(0, 6300)
    ax.set_title("同一个记忆功能，代价差两个数量级", fontsize=19, pad=34, color=INK,
                 fontweight="bold")
    ax.legend(frameon=False, loc="upper right", fontsize=12,
              bbox_to_anchor=(1.0, 1.02))
    style(ax)
    save(fig, "fig1_aup_latency.png")


# ============================================================ 图 2（哑铃图）
def fig2():
    fig, ax = plt.subplots(figsize=(10.0, 4.6))
    rows = ["云端 DeepSeek", "端侧 Qwen2.5-1.5B"]
    y = [1, 0]

    for yy, label in zip(y, rows):
        ax.plot([0, 100], [yy, yy], color=GRID, linewidth=6, solid_capstyle="round",
                zorder=1)
        ax.plot([0, 100], [yy, yy], color=ACCENT, linewidth=6, solid_capstyle="round",
                zorder=2)
        ax.scatter([0], [yy], s=150, color=MUTED, zorder=3, edgecolor="white",
                   linewidth=2)
        ax.scatter([100], [yy], s=170, color=ACCENT, zorder=4, edgecolor="white",
                   linewidth=2)
        ax.text(-6, yy, "0%", ha="right", va="center", fontsize=14, color=MUTED)
        ax.text(106, yy, "100%", ha="left", va="center", fontsize=15,
                color=ACCENT, fontweight="bold")

    ax.set_yticks(y, rows, fontsize=14)
    ax.set_xlim(-22, 128)
    ax.set_ylim(-0.6, 1.6)
    ax.set_xticks([])
    ax.set_title("记忆从无到有：跨轮真实召回 0% → 100%", fontsize=19, pad=18,
                 color=INK, fontweight="bold")
    style(ax)
    ax.grid(False)
    ax.spines["bottom"].set_visible(False)
    save(fig, "fig2_recall.png")


# ============================================================ 图 3（横向堆叠）
def fig3():
    fig, ax = plt.subplots(figsize=(10.4, 3.6))
    parts = [
        ("ok 本来就该允许", 3, GOOD),
        ("forbidden 数量超上限", 1, BAD),
        ("unknown_action 发明动作", 1, WARN),
        ("precondition_failed 幻觉/条件不满足", 10, "#6B7C90"),
    ]
    left = 0
    for label, value, color in parts:
        ax.barh([0], [value], left=left, color=color, height=0.42, label=label, zorder=2)
        if value >= 3:
            ax.text(left + value / 2, 0, str(value), ha="center", va="center",
                    color="white", fontsize=13, fontweight="bold")
        left += value

    ax.set_xlim(0, 17.4)
    ax.set_ylim(-0.75, 0.95)
    ax.set_yticks([0], ["动作提议打开"], fontsize=14)
    ax.set_xlabel("提议次数（四个场景合计）", fontsize=13)
    ax.text(0, 0.66, "关闭动作提议时：0 次", fontsize=13, color=MUTED)
    ax.text(15.05, 0.66, "越权采纳 0 次", fontsize=13, color=GOOD, fontweight="bold")
    ax.set_title("打开后 15 次提议，规则层全部拦下", fontsize=19, pad=16,
                 color=INK, fontweight="bold")
    ax.legend(frameon=False, ncol=2, fontsize=11, loc="upper center",
              bbox_to_anchor=(0.5, -0.30))
    style(ax, grid_axis="x")
    ax.spines["left"].set_visible(False)
    save(fig, "fig3_ab_proposals.png")


# ============================================================ 图 4（哑铃图）
def fig4():
    fig, ax = plt.subplots(figsize=(10.0, 4.2))
    rows = ["伪造记忆 可信度 0.20", "伪造记忆 可信度 0.90"]
    vals = [76, 197]
    y = [1, 0]
    colors = [MUTED, ACCENT]

    for yy, v, c in zip(y, vals, colors):
        ax.plot([0, v], [yy, yy], color=GRID, linewidth=6, solid_capstyle="round",
                zorder=1)
        ax.scatter([v], [yy], s=170, color=c, zorder=3, edgecolor="white", linewidth=2)
        ax.text(v + 7, yy, f"{v} 字符", va="center", ha="left", fontsize=14,
                color=c, fontweight="bold")

    ax.set_yticks(y, rows, fontsize=14)
    ax.set_xlim(0, 300)
    ax.set_ylim(-0.6, 1.6)
    ax.set_xlabel("进入提示词的记忆片段长度", fontsize=13)
    ax.text(88, 0.72, "未达阈值 → 伪造内容进不了 prompt", fontsize=12, color=MUTED)
    ax.text(205, -0.28, "抬高后 → 内容进入", fontsize=12, color=ACCENT)
    ax.set_title("可信度不是标签：它决定什么能进 prompt", fontsize=19, pad=18,
                 color=INK, fontweight="bold")
    style(ax, grid_axis="x")
    save(fig, "fig4_memory_filter.png")


if __name__ == "__main__":
    fig1()
    fig2()
    fig3()
    fig4()
