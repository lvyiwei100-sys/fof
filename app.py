import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="FOF基金配置助手", page_icon="📊", layout="wide")

CATEGORY_RULES = {
    "固收基金": [
        "中长期纯债型基金",
        "混合债券型一级基金",
        "国际(QDII)债券型基金",
    ],
    "固收+基金": [
        "混合债券型二级基金",
        "偏债混合型基金",
        "灵活配置型基金",
    ],
    "权益基金": [
        "普通股票型基金",
        "偏股混合型基金",
        "增强指数型基金",
        "被动指数型基金",
        "国际(QDII)股票型基金",
    ],
}

DISPLAY_COLUMNS = {
    "基金简称": "基金名称",
    "基金代码": "基金代码",
    "投资类型": "投资类型",
    "近1年年化收益率": "近1年年化收益率",
    "近1年最大回撤": "近1年最大回撤",
    "配置比例": "配置比例",
    "组合贡献收益": "组合贡献收益",
    "组合贡献回撤": "组合贡献回撤",
}


@st.cache_data(show_spinner=False)
def load_data(file: str) -> pd.DataFrame:
    df = pd.read_excel(file)

    needed_cols = [
        "基金代码",
        "基金简称",
        "投资类型",
        "近1年年化收益率",
        "近1年最大回撤",
    ]
    missing = [c for c in needed_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Excel 缺少必要字段: {', '.join(missing)}")

    clean = df[needed_cols].copy()
    clean["近1年年化收益率"] = pd.to_numeric(clean["近1年年化收益率"], errors="coerce")
    clean["近1年最大回撤"] = pd.to_numeric(clean["近1年最大回撤"], errors="coerce")

    clean = clean.dropna(subset=["近1年年化收益率", "近1年最大回撤", "基金简称", "基金代码"])
    clean = clean.drop_duplicates(subset=["基金代码"], keep="first")
    clean["近1年最大回撤"] = clean["近1年最大回撤"].clip(upper=0)
    return clean


def attach_category(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result["资产类别"] = "其他"
    for cat, patterns in CATEGORY_RULES.items():
        result.loc[result["投资类型"].isin(patterns), "资产类别"] = cat
    return result


def pick_candidate_pool(df: pd.DataFrame, target_return: float, max_drawdown: float, top_n: int = 8) -> pd.DataFrame:
    all_parts = []
    for cat in ["固收基金", "固收+基金", "权益基金"]:
        part = df[df["资产类别"] == cat].copy()
        if part.empty:
            continue

        feasible = part[part["近1年最大回撤"] >= max_drawdown]
        chosen = feasible if len(feasible) >= max(3, top_n // 2) else part

        chosen["评分"] = (
            -(chosen["近1年年化收益率"] - target_return).abs() * 0.6
            + chosen["近1年年化收益率"] * 0.6
            + chosen["近1年最大回撤"] * 0.2
        )
        all_parts.append(chosen.sort_values("评分", ascending=False).head(top_n))

    if not all_parts:
        return pd.DataFrame()

    pool = pd.concat(all_parts, ignore_index=True)
    return pool.drop(columns=["评分"], errors="ignore")


def simulate_frontier(pool: pd.DataFrame, target_return: float, max_drawdown: float, n: int = 5000):
    r = pool["近1年年化收益率"].to_numpy()
    d = pool["近1年最大回撤"].to_numpy()
    cats = pool["资产类别"].to_numpy()

    idx = {
        "固收基金": np.where(cats == "固收基金")[0],
        "固收+基金": np.where(cats == "固收+基金")[0],
        "权益基金": np.where(cats == "权益基金")[0],
    }

    if any(len(v) == 0 for v in idx.values()):
        return None

    min_bucket = {"固收基金": 0.2, "固收+基金": 0.2, "权益基金": 0.2}

    random_points = []
    best_score = -1e18
    best_w = None

    for _ in range(n):
        bucket_w = np.random.dirichlet([2.2, 1.8, 2.0])

        w = np.zeros(len(pool))
        ok = True
        for i, cat in enumerate(["固收基金", "固收+基金", "权益基金"]):
            if bucket_w[i] < min_bucket[cat]:
                ok = False
                break
            inside = np.random.dirichlet(np.ones(len(idx[cat])))
            w[idx[cat]] = inside * bucket_w[i]
        if not ok:
            continue

        port_r = float(np.dot(w, r))
        port_dd = float(np.dot(w, d))

        penalty = 0.0
        if port_dd < max_drawdown:
            penalty -= abs(port_dd - max_drawdown) * 8.0

        score = (
            -abs(port_r - target_return) * 4.0
            + port_r * 1.4
            + port_dd * 0.8
            + penalty
        )

        random_points.append((port_dd, port_r, score))
        if score > best_score:
            best_score = score
            best_w = w

    if best_w is None:
        return None

    frontier_df = pd.DataFrame(random_points, columns=["预期最大回撤", "预期收益率", "评分"])
    return best_w, frontier_df


def build_portfolio_table(pool: pd.DataFrame, weights: np.ndarray) -> pd.DataFrame:
    res = pool.copy()
    res["配置比例"] = weights
    res = res[res["配置比例"] > 0.0001].copy()

    # 只保留 5 只基金：先保证三大类各至少 1 只，再按权重补足到 5 只
    picked_idx = []
    for cat in ["固收基金", "固收+基金", "权益基金"]:
        cat_part = res[res["资产类别"] == cat].sort_values("配置比例", ascending=False)
        if not cat_part.empty:
            picked_idx.append(cat_part.index[0])

    remaining = res.drop(index=picked_idx, errors="ignore").sort_values("配置比例", ascending=False)
    need_more = max(0, 5 - len(picked_idx))
    picked_idx.extend(remaining.head(need_more).index.tolist())

    # 如果极端情况下不足 5 只，则用当前可用基金；如果超过 5 只，则按权重截断到 5 只
    res = res.loc[picked_idx].sort_values("配置比例", ascending=False).head(5).copy()
    res["配置比例"] = res["配置比例"] / res["配置比例"].sum()

    res["组合贡献收益"] = res["配置比例"] * res["近1年年化收益率"]
    res["组合贡献回撤"] = res["配置比例"] * res["近1年最大回撤"]
    res = res.sort_values(["资产类别", "配置比例"], ascending=[True, False])

    show = res[[*DISPLAY_COLUMNS.keys(), "资产类别"]].rename(columns=DISPLAY_COLUMNS)
    return show


def as_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def render():
    st.markdown(
        """
        <style>
        .main-title {font-size: 34px; font-weight: 700; margin-bottom: 4px;}
        .sub-title {color: #4b5563; margin-bottom: 14px;}
        .metric-card {padding: 12px 14px; border-radius: 14px; background: #f7f9fc; border: 1px solid #e5e7eb;}
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="main-title">📊 FOF 基金配置助手</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-title">基于有效前沿模拟，按“固收 / 固收+ / 权益”三类基金自动生成组合建议。</div>',
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.2, 2.0], gap="large")

    with left:
        st.markdown("### 客户信息")
        name = st.text_input("姓名", placeholder="请输入客户姓名")
        age = st.number_input("年龄", min_value=18, max_value=100, value=35)
        target_return = st.slider("预期收益率", min_value=0.01, max_value=0.20, value=0.08, step=0.005)
        max_drawdown = st.slider("最大可承受回撤", min_value=-0.40, max_value=-0.01, value=-0.08, step=0.005)

        st.caption("说明：预期收益率与回撤均使用 Excel 中“近1年”指标进行估算。")
        run = st.button("生成配置方案", type="primary", use_container_width=True)

    with right:
        st.markdown("### 组合结果")

        if not run:
            st.info("请在左侧输入客户信息后点击“生成配置方案”。")
            return

        try:
            raw = load_data("基金业绩统计表.xlsx")
        except Exception as e:
            st.error(f"数据读取失败：{e}")
            return

        data = attach_category(raw)
        pool = pick_candidate_pool(data, target_return, max_drawdown)

        if pool.empty:
            st.error("基金池为空，请检查数据文件或分类映射。")
            return

        sim = simulate_frontier(pool, target_return, max_drawdown)
        if sim is None:
            st.error("无法生成满足约束的组合，请放宽回撤限制或调整预期收益率。")
            return

        weights, frontier = sim
        table = build_portfolio_table(pool, weights)

        port_r = float((table["配置比例"] * table["近1年年化收益率"]).sum())
        port_dd = float((table["配置比例"] * table["近1年最大回撤"]).sum())

        c1, c2, c3 = st.columns(3)
        c1.metric("客户", name or "未命名客户")
        c2.metric("组合预期收益率", as_pct(port_r))
        c3.metric("组合预期最大回撤", as_pct(port_dd))

        st.markdown("#### 推荐基金组合")
        st.caption("当前策略每次固定输出 5 只基金（覆盖固收、固收+、权益三类）。")
        st.dataframe(
            table,
            use_container_width=True,
            hide_index=True,
            column_config={
                "近1年年化收益率": st.column_config.NumberColumn(format="%.2f%%", help="展示为百分比"),
                "近1年最大回撤": st.column_config.NumberColumn(format="%.2f%%"),
                "配置比例": st.column_config.NumberColumn(format="%.2f%%"),
                "组合贡献收益": st.column_config.NumberColumn(format="%.2f%%"),
                "组合贡献回撤": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )

        st.markdown("#### 有效前沿（模拟）")
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=frontier["预期最大回撤"],
                y=frontier["预期收益率"],
                mode="markers",
                marker=dict(size=4, color=frontier["评分"], colorscale="Viridis", opacity=0.45),
                name="可行组合",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=[port_dd],
                y=[port_r],
                mode="markers+text",
                marker=dict(size=12, color="#ef4444"),
                text=["当前方案"],
                textposition="top center",
                name="推荐组合",
            )
        )

        fig.update_layout(
            xaxis_title="预期最大回撤（越高越好）",
            yaxis_title="预期收益率",
            height=410,
            margin=dict(l=20, r=20, t=30, b=20),
            template="plotly_white",
        )
        st.plotly_chart(fig, use_container_width=True)

        st.success(f"已为 {name or '客户'}（{age}岁）生成配置建议。")


if __name__ == "__main__":
    render()
