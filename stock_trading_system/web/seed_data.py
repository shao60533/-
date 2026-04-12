"""Seed mock MSFT analysis data for web UI testing."""

import json
from datetime import datetime
from pathlib import Path

from stock_trading_system.config import load_config, get_config
from stock_trading_system.portfolio.database import PortfolioDatabase


def seed_msft_analysis():
    """Insert a realistic MSFT analysis record based on actual output."""
    load_config()
    config = get_config()
    db_path = config.get("portfolio", {}).get("db_path", "data/portfolio.db")
    db = PortfolioDatabase(db_path)

    msft_data = {
        "ticker": "MSFT",
        "date": "2026-04-06",
        "signal": "OVERWEIGHT",
        "market_report": """微软(MSFT)技术面分析报告 - 2026年4月6日

一、价格走势与趋势分析

当前价格: $388.45
52周最高: $468.35 (2025年7月)
52周最低: $344.79 (2025年10月)
距52周高点: -17.1%

移动平均线系统:
- MA5: $385.20 (价格在上方, 短期看多)
- MA20: $379.88 (价格在上方, 中期看多)
- MA60: $392.15 (价格在下方, 中长期承压)
- MA120: $401.33 (价格在下方, 长期趋势偏弱)

趋势判断: 短中期反弹趋势形成，但长期均线仍有压力。价格从10月低点反弹约12.7%，目前处于60日均线附近的关键阻力区域。

二、关键技术指标

MACD: DIF=3.21, DEA=1.85, MACD柱=2.72 (金叉状态, 多头动能增强)
RSI(14): 58.3 (中性偏多, 未到超买区域)
KDJ: K=65.2, D=58.7, J=78.2 (多头排列, 短期仍有上行空间)
布林带: 上轨=$398.50, 中轨=$379.88, 下轨=$361.26 (价格位于中上轨之间)
成交量: 近5日平均2,850万股, 较20日均量增加15%, 量价配合良好

三、支撑与阻力

强阻力位: $398-402 (60日均线+布林上轨)
第一阻力: $392-395
当前价格: $388.45
第一支撑: $379-382 (20日均线+布林中轨)
强支撑位: $365-370 (前期整理平台)

四、技术面总结

技术评分: 7/10
综合来看，MSFT处于中期反弹通道中，短期技术指标多头排列，MACD金叉且RSI未进入超买。主要风险在于60日和120日均线的压力，需要放量突破$398才能打开进一步上行空间。建议关注$379支撑是否有效。""",

        "fundamentals_report": """微软(MSFT)基本面分析报告 - 2026年4月6日

一、核心财务数据 (FY2026 Q2, 截至2025年12月)

营收: $696亿 (同比+14.2%)
- 智能云: $264亿 (+21%)
  - Azure: 同比增长31% (AI服务贡献约12个百分点)
- 生产力与商业流程: $213亿 (+12%)
  - Microsoft 365商业版: +15%
  - LinkedIn: +9%
- 个人计算: $219亿 (+8%)
  - Windows OEM: +5%
  - Xbox: +12%

毛利率: 71.2% (同比提升1.3个百分点)
运营利润率: 46.8% (同比提升0.9个百分点)
净利润: $242亿 (同比+18%)
EPS: $3.25 (超市场预期$3.18)

二、关键估值指标

市盈率(TTM): 32.5x (行业中值: 28x)
前瞻市盈率: 28.8x
PEG: 1.8 (合理偏高)
市净率: 12.3x
EV/EBITDA: 24.1x
自由现金流收益率: 2.8%

三、增长驱动力

1. Azure与AI云服务: Azure保持30%+增速, Copilot企业订阅量已超过500万席位
2. Microsoft 365 Copilot: 企业付费用户快速增长, ARPU提升显著
3. AI基础设施投资: FY2026资本开支预计$780亿, 主要投向AI数据中心
4. GitHub Copilot: 开发者付费用户突破800万

四、风险因素

- 高资本开支短期压制自由现金流
- AI变现节奏不及预期的风险
- 反垄断监管 (欧盟、FTC)
- 估值溢价相对较高

五、基本面总结

基本面评分: 8/10
微软是AI浪潮中最大的受益者之一。Azure增速强劲, AI产品矩阵完善, 利润率持续扩张。估值虽高于行业均值但增速支撑充分。主要担忧是巨额资本开支的回报周期。""",

        "sentiment_report": """微软(MSFT)市场情绪分析 - 2026年4月6日

一、社交媒体情绪

Reddit (r/stocks, r/investing):
- 情绪指数: 72/100 (积极偏多)
- 热门话题: Copilot企业版扩展、Azure AI增速、Q2财报超预期
- 看多观点: AI领域龙头地位稳固, 企业AI采用加速
- 看空观点: 资本开支过高, 估值偏贵

Twitter/X:
- 提及量: 过去7天12,500+条
- 正面比例: 65%, 中性: 22%, 负面: 13%
- 主要正面: "AI三巨头中最稳的选择", "Copilot订阅增长超预期"
- 主要负面: "市盈率太高了", "数据中心投资回报不确定"

二、机构评级

最新30天评级变动:
- 摩根士丹利: 维持增持, 目标价$450 → $460
- 高盛: 维持买入, 目标价$440
- Wedbush: 上调至强力买入, 目标价$475 ("AI领域被低估")
- 伯恩斯坦: 维持市场表现, 目标价$400 ("估值已充分反映")

共识评级: 买入 (45个分析师中39个买入/增持, 5个持有, 1个卖出)
平均目标价: $442 (当前价上方约14%)

三、期权市场信号

看涨/看跌比率: 1.35 (偏多)
最大未平仓看涨期权: 4月$400 Call (大量机构持仓)
隐含波动率: 24.5% (低于30日历史波动率26.8%, 市场预期平稳)

四、情绪总结

情绪评分: 7/10
市场整体对MSFT保持积极态度, 机构评级共识偏多, 社交媒体情绪良好。期权市场显示温和看涨预期。""",

        "news_report": """微软(MSFT)新闻分析 - 2026年4月6日

一、近期重要新闻

1. [2026-04-03] Microsoft Copilot企业版用户突破500万
   - 微软宣布Microsoft 365 Copilot企业付费用户超500万, 较上季度增长40%
   - 企业ARPU提升约15%, 显示强劲的变现能力
   - 影响: 正面, 验证了AI产品的商业化路径

2. [2026-04-01] Azure AI服务扩展至新区域
   - Azure OpenAI服务新增东南亚和中东5个数据中心区域
   - 与当地电信运营商达成合作, 降低延迟
   - 影响: 正面, 扩大全球AI服务覆盖

3. [2026-03-28] FY2026资本支出指引上调至$800亿
   - 微软CFO确认全年资本支出可能达到$800亿(此前指引$750亿)
   - 主要用于AI数据中心基础设施建设
   - 影响: 双刃剑, 显示AI投资信心但短期压制FCF

4. [2026-03-25] Windows 12发布日期确认: 2026年秋季
   - 集成Copilot深度功能, 支持本地AI推理
   - OEM合作伙伴已开始预装测试
   - 影响: 正面, 有望带动PC换机周期

5. [2026-03-20] 欧盟反垄断调查Teams捆绑销售
   - 欧盟委员会对Teams与Office 365捆绑销售展开正式调查
   - 微软回应称已提供独立购买选项
   - 影响: 轻微负面, 但预计影响有限

二、新闻影响评估

整体新闻面偏正面。Copilot商业化进展超预期是最大利好, 资本开支上调显示管理层对AI前景的信心, 但也增加了短期财务压力。欧盟反垄断调查是常规事件, 不构成重大风险。

新闻情绪评分: 7.5/10""",

        "investment_debate": """{'bull_case': '看多方观点: 1) AI领域最完整的产品矩阵(Azure AI + Copilot + GitHub Copilot + Windows AI), 变现能力最强; 2) Azure增速31%远超AWS和GCP, 市场份额持续提升; 3) Copilot企业版500万用户验证PMF, 后续增长空间巨大; 4) 利润率持续扩张, 规模效应显著; 5) 机构共识目标价$442, 上行空间约14%', 'bear_case': '看空方观点: 1) TTM PE 32.5x高于行业中值, 估值偏贵; 2) FY2026资本开支$800亿创历史新高, 自由现金流承压; 3) AI投资回报周期不确定, 存在"军备竞赛"风险; 4) 欧盟反垄断调查可能影响捆绑销售策略; 5) 技术面上60日均线构成短期阻力', 'conclusion': '多空辩论结论: 多方论据更具说服力。微软在AI领域的领先地位和商业化能力是核心优势, 短期估值虽高但增速支撑充分。空方的资本开支担忧合理但可控。综合评估偏向增持。'}""",

        "risk_assessment": """{'overall_risk': 'medium', 'risk_factors': [{'factor': '估值风险', 'level': 'medium', 'detail': 'TTM PE 32.5x高于行业中值28x, 但PEG 1.8尚在合理区间'}, {'factor': '资本开支风险', 'level': 'medium-high', 'detail': 'FY2026资本开支预计$800亿, 短期压制自由现金流, 需关注ROI'}, {'factor': '竞争风险', 'level': 'low-medium', 'detail': 'AWS和GCP在AI领域加大投入, 但微软产品矩阵优势明显'}, {'factor': '监管风险', 'level': 'low', 'detail': '欧盟反垄断调查为常规事件, 影响有限'}, {'factor': '技术面风险', 'level': 'medium', 'detail': '60日和120日均线构成阻力, 需放量突破'}], 'risk_score': '5.5/10', 'recommendation': '风险可控, 适合中长期配置'}""",

        "trade_decision": """{'decision': 'OVERWEIGHT', 'reasoning': '综合多Agent分析结论: MSFT在AI领域具有最完整的产品矩阵和最强的变现能力, Azure增速领先行业, Copilot商业化进展超预期。虽然估值偏高且资本开支巨大, 但增速和利润率扩张提供了支撑。技术面短中期反弹趋势完好, 但需关注60日均线阻力突破情况。建议增持但控制仓位, 在$379-382区间有良好的买入机会。', 'position_suggestion': '建议仓位5-10%, 逢回调$379-382区间加仓', 'stop_loss': '$365 (前期支撑平台下方)', 'take_profit': '$440-450 (机构共识目标价区间)', 'time_horizon': '3-6个月'}""",

        "advice_json": json.dumps({
            "action": "watch",
            "confidence": "medium",
            "suggested_position_pct": 10.0,
            "entry_price_low": 379.0,
            "entry_price_high": 392.0,
            "stop_loss": 365.0,
            "take_profit": 445.0,
            "reasoning": "AI信号OVERWEIGHT, 建议增持但等待更好的入场时机。当前价格$388接近60日均线阻力, 可在$379-382回调支撑位建仓。",
            "risk_warning": "AI分析仅供参考, 不构成投资建议"
        }, ensure_ascii=False),

        "created_at": "2026-04-06 20:25:00",
    }

    db.save_analysis(msft_data)
    print(f"MSFT analysis record seeded successfully!")


if __name__ == "__main__":
    seed_msft_analysis()
