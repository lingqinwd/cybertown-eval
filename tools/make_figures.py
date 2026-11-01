"""生成 PPT 用的四张图（数据全部来自仓库实测，不引入任何虚构数字）。

输出到 docs/images/：
    fig1_aup_latency.png    AUP 2×2 记忆开关的延迟对比（3.12× / 1.25×）
    fig2_recall.png         跨轮记忆召回率 0% → 100%
    fig3_ab_proposals.png   A/B：关掉动作提议 0 次、打开后 15 次及裁决分布
    fig4_memory_filter.png  可信度阈值把伪造记忆挡在 prompt 外（76 → 197 字符）
"""

import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

REPO = pathlib.Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "images"
OUT.mkdir(parents=True, exist_ok=True)

# 中文字体
for name in ("Microsoft YaHei", "SimHei"):
    if any(f.name == name for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.sans-serif"] = [name]
        break
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["font.size"] = 13

C_OFF = "#8fa3b8"
C_ON = "#2f6fd0"
C_BAD = "#e05252"
C_WARN = "#e8952e"
C_OK = "#3fa45b"


def save(fig, name):
    path = OUT / name
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[OK] {path.relative_to(REPO)}  ({path.stat().st_size // 1024} KB)")


# ---------------------------------------------------------------- 图 1
def fig_latency():
    labels = ["云端 DeepSeek\n(AUP, GPU)", "端侧 Qwen2.5-1.5B\n(R9700 + ROCm)"]
    off = [1542, 861]
    on = [4810, 1078]
    x = [0, 1]
    w = 0.34

    fig, ax = plt.subplots(figsize=(8.4, 5.0))
    b1 = ax.bar([i - w / 2 for i in x], off, w, label="记忆关", color=C_OFF)
    b2 = ax.bar([i + w / 2 for i in x], on, w, label="记忆开", color=C_ON)
    for bars in (b1, b2):
        for r in bars:
            ax.annotate(f"{r.get_height():.0f}",
                        (r.get_x() + r.get_width() / 2, r.get_height()),
                        ha="center", va="bottom", fontsize=12)

    # 倍数标注
    ax.annotate("3.12×", xy=(0 + w / 2, 4810), xytext=(0.02, 5400),
                ha="center", fontsize=17, color=C_BAD, fontweight="bold",
                arrowprops=dict(arrowstyle="->", color=C_BAD, lw=1.8))
    ax.annotate("1.25×", xy=(1 + w / 2, 1078), xytext=(1.02, 2200),
                ha="center", fontsize=17, color=C_OK, fontweight="bold",
                arrowprops=dict(arrowstyle="->", color=C_OK, lw=1.8))

    ax.set_xticks(x, labels)
    ax.set_ylabel("平均延迟 (ms)")
    ax.set_title("加记忆的代价：同一个功能，两个数量级不同", fontsize=15, pad=14)
    ax.set_ylim(0, 6200)
    ax.legend(frameon=False, loc="upper right")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25, linestyle="--")
    ax.set_axisbelow(True)
    save(fig, "fig1_aup_latency.png")


# ---------------------------------------------------------------- 图 2
def fig_recall():
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    groups = ["云端 DeepSeek", "端侧 Qwen2.5-1.5B"]
    off = [0, 0]
    on = [100, 100]
    x = [0, 1]
    w = 0.34
    ax.bar([i - w / 2 for i in x], off, w, label="记忆关", color=C_OFF)
    ax.bar([i + w / 2 for i in x], on, w, label="记忆开", color=C_ON)
    for i in x:
        ax.annotate("0%", (i - w / 2, 2), ha="center", va="bottom", fontsize=12)
        ax.annotate("100%", (i + w / 2, 100), ha="center", va="bottom",
                    fontsize=13, color=C_OK, fontweight="bold")
    ax.set_xticks(x, groups)
    ax.set_ylim(0, 118)
    ax.set_ylabel("跨轮真实召回率 (%)")
    ax.set_title("记忆从无到有：0% → 100%，两组都拿到", fontsize=15, pad=12)
    ax.legend(frameon=False, loc="upper left")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25, linestyle="--")
    ax.set_axisbelow(True)
    save(fig, "fig2_recall.png")


# ---------------------------------------------------------------- 图 3
def fig_ab():
    fig, ax = plt.subplots(figsize=(8.4, 5.0))
    cats = ["动作提议关闭", "动作提议打开"]
    ok = [0, 3]
    unknown = [0, 1]
    forbidden = [0, 1]
    precondition = [0, 10]

    ax.bar(cats, ok, label="ok（本来就该允许）", color=C_OK)
    ax.bar(cats, unknown, bottom=ok, label="unknown_action（发明动作）", color=C_WARN)
    b3 = ax.bar(cats, forbidden, bottom=[a + b for a, b in zip(ok, unknown)],
                label="forbidden（数量超上限）", color=C_BAD)
    ax.bar(cats, precondition,
           bottom=[a + b + c for a, b, c in zip(ok, unknown, forbidden)],
           label="precondition_failed（幻觉/条件不满足）", color="#5b6b7c")

    for i, total in enumerate([0, 15]):
        ax.annotate(f"{total} 次", (i, total), ha="center", va="bottom",
                    fontsize=15, fontweight="bold")
    ax.annotate("越权采纳：0 次\n四个场景判据全过", xy=(1, 7.5), xytext=(0.42, 12.4),
                fontsize=12, color="#333",
                bbox=dict(boxstyle="round,pad=0.5", fc="#f4f6f8", ec="#c8d0d8"))

    ax.set_ylabel("提议次数")
    ax.set_ylim(0, 17)
    ax.set_title("打开动作提议后，模型会越权 —— 规则层全部拦下", fontsize=15, pad=14)
    ax.legend(frameon=False, loc="upper left", fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25, linestyle="--")
    ax.set_axisbelow(True)
    save(fig, "fig3_ab_proposals.png")


# ---------------------------------------------------------------- 图 4
def fig_filter():
    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    bars = ax.barh(["伪造记忆 可信度 0.20\n（默认阈值 0.5）",
                    "伪造记忆 可信度 0.90"],
                   [76, 197], color=[C_OFF, C_ON], height=0.5)
    for r, extra in zip(bars, ["只含可信记忆", "伪造内容已进入"]):
        ax.annotate(f"{int(r.get_width())} 字符 · {extra}",
                    (r.get_width(), r.get_y() + r.get_height() / 2),
                    va="center", ha="left", fontsize=12, xytext=(8, 0),
                    textcoords="offset points")
    ax.set_xlim(0, 320)
    ax.set_xlabel("进入提示词的记忆片段长度")
    ax.set_title("可信度阈值不是标签：它决定什么能进 prompt", fontsize=15, pad=12)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", alpha=0.25, linestyle="--")
    ax.set_axisbelow(True)
    save(fig, "fig4_memory_filter.png")


if __name__ == "__main__":
    fig_latency()
    fig_recall()
    fig_ab()
    fig_filter()
