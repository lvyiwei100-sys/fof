# fof allocation app

基于你上传的 `基金业绩统计表.xlsx` 做基金组合建议的 Streamlit 应用。

## 功能

- 输入客户信息：姓名、年龄、预期收益率、最大可承受回撤。
- 使用“有效前沿模拟（Monte Carlo）”在基金池内生成组合。
- 组合强制包含三类资产：**固收基金、固收+基金、权益基金**。
- 输出基金组合表：基金名称、代码、近1年年化收益率、配置比例、预期最大回撤、组合贡献等。
- 可视化展示有效前沿与推荐组合位置。

## 本地运行

```bash
pip install -r requirements.txt
streamlit run app.py
```

## 部署到 share.streamlit.io

1. 将本仓库推送到 GitHub。
2. 进入 https://share.streamlit.io ，选择该仓库。
3. Main file path 填 `app.py`。
4. 部署后保持仓库根目录下有：
   - `app.py`
   - `requirements.txt`
   - `基金业绩统计表.xlsx`

## 数据字段要求

Excel 至少包含以下列：

- `基金代码`
- `基金简称`
- `投资类型`
- `近1年年化收益率`
- `近1年最大回撤`

应用会基于 `投资类型` 自动映射资产类别。
