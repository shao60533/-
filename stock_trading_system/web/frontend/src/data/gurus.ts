export interface Guru {
  id: string
  name: string
  philosophy: string
  initials: string
  color: string
  principles: string[]
  tier: "core" | "advanced" | "custom"
}

export const GURUS: Guru[] = [
  { id: "buffett",       name: "Warren Buffett",        philosophy: "价值投资 / 护城河",        initials: "WB", color: "linear-gradient(135deg,#c0a882,#8b7355)", principles: ["经济护城河","ROE>15%","低负债","长期 FCF"],    tier: "core" },
  { id: "graham",        name: "Benjamin Graham",       philosophy: "深度价值 / 安全边际",      initials: "BG", color: "linear-gradient(135deg,#5f7a99,#3e5478)", principles: ["P/B<1.5","P/E<15","流动比率>2","净资产折价"], tier: "core" },
  { id: "munger",        name: "Charlie Munger",        philosophy: "质量优先 / 多元模型",      initials: "CM", color: "linear-gradient(135deg,#a67c52,#735537)", principles: ["优秀生意>便宜价","Lollapalooza","ROIC 趋势"], tier: "core" },
  { id: "lynch",         name: "Peter Lynch",           philosophy: "成长价值 / PEG",           initials: "PL", color: "linear-gradient(135deg,#4a8c3f,#2e6325)", principles: ["PEG<1","故事一致","行业领先"],             tier: "core" },
  { id: "fisher",        name: "Philip Fisher",         philosophy: "科学成长 / 定性分析",       initials: "PF", color: "linear-gradient(135deg,#6b8e9e,#4a6473)", principles: ["15 Points","管理层质量","研发持续"],        tier: "advanced" },
  { id: "burry",         name: "Michael Burry",         philosophy: "反共识 / 深度价值",         initials: "MB", color: "linear-gradient(135deg,#8b4a4a,#5a2e2e)", principles: ["NCAV 折价","反向持仓","尾部风险"],         tier: "advanced" },
  { id: "ackman",        name: "Bill Ackman",           philosophy: "激进 / Catalyst 驱动",      initials: "BA", color: "linear-gradient(135deg,#8e5f8e,#5c3b5c)", principles: ["催化剂","集中持仓","公开行动"],             tier: "advanced" },
  { id: "wood",          name: "Cathie Wood",           philosophy: "颠覆性创新 / 长期主题",     initials: "CW", color: "linear-gradient(135deg,#c25b7e,#8a3456)", principles: ["AI / 基因 / 自动化","指数增长","5 年视角"], tier: "advanced" },
  { id: "druckenmiller", name: "Stanley Druckenmiller", philosophy: "宏观驱动 / 集中持仓",       initials: "SD", color: "linear-gradient(135deg,#6c5a99,#453872)", principles: ["宏观象限","流动性","高信念集中"],           tier: "advanced" },
  { id: "damodaran",     name: "Aswath Damodaran",      philosophy: "估值学术 / DCF 驱动",       initials: "AD", color: "linear-gradient(135deg,#5a7a8e,#3b5466)", principles: ["DCF","内在价值","故事+数字"],               tier: "advanced" },
  { id: "pabrai",        name: "Mohnish Pabrai",        philosophy: "Dhandho / Kelly",           initials: "MP", color: "linear-gradient(135deg,#a68250,#735933)", principles: ["低风险高不确定","Kelly 仓位","少数下重注"], tier: "advanced" },
  { id: "taleb",         name: "Nassim Taleb",          philosophy: "反脆弱 / 杠铃策略",         initials: "NT", color: "linear-gradient(135deg,#556b7d,#38495a)", principles: ["尾部风险","反脆弱","凸性"],                 tier: "advanced" },
  { id: "marks",         name: "Howard Marks",          philosophy: "循环 / 第二层思考",         initials: "HM", color: "linear-gradient(135deg,#7a6b8e,#52456b)", principles: ["市场循环","共识反向","不对称回报"],         tier: "custom" },
  { id: "dalio",         name: "Ray Dalio",             philosophy: "全天候 / 桥水原则",         initials: "RD", color: "linear-gradient(135deg,#4a8585,#2e5454)", principles: ["经济四象限","债务周期","真实生产率"],       tier: "custom" },
]
