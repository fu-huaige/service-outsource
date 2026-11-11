# IndusOpt 五个新增模型研发规划与开发原则

**项目：** A14 / IndusOpt / ProcessPilot\
**文档用途：** 后续模型开发的长期规划、架构约束和 Codex 工作依据\
**规划状态：**
五个模型已确认纳入开发计划；每个模型的具体实现方案仍须先审计、再确认、后实施。\
**当前基线：** PLS 已完成核心训练、Artifact、DatasetVersion
绑定、ProcessingRun、统一 Manifest、固定模型评价及五类业务
API，并已由用户 Commit + Push。

------------------------------------------------------------------------

## 1. 项目定位与本轮目标

IndusOpt 定位为：

> 面向流程工业的多模型动态辨识与智能优化平台，以动态系统辨识为核心，同时兼顾非线性预测、工业软测量与统计过程监测。

模型协作方式采用已经确定的方案 C：

-   **手动横向比较：**
    用户能够根据任务、数据和工程知识选择模型，并在统一实验条件下比较结果。
-   **Agent 自动推荐：** Agent
    根据任务类型、数据特征、模型能力和历史评价结果提出建议，但不覆盖人工选择，不擅自改变实验定义。

本轮只开发以下五个新增模型：

1.  XGBoost
2.  TCN
3.  SINDy
4.  Neural State-Space
5.  Transformer / TimeXer

GNN 暂不纳入必做范围。暂缓新增 Random
Forest、SVR、LSTM、GRU、NARX、NARMAX、ARMAX、BJ、GPR、DPCA、DPLS
等模型，以控制开发规模、减少能力重复。暂缓不代表这些方法没有学术或工业价值。

## 2. 五个模型的时间、定位与应用边界

年份采用具有代表性的原始论文或代表性架构论文年份。对于持续演进的模型家族，不把代表性论文年份误称为整个思想唯一的诞生年份。

  ---------------------------------------------------------------------------------------------------------------------------------
  模型                                   代表性年份 主要任务                                 在 IndusOpt 中的角色
  ---------------- -------------------------------- ---------------------------------------- --------------------------------------
  XGBoost                                      2016 结构化数据回归、软测量、非线性预测       静态/特征化工业数据的强基线

  TCN                                          2018 多变量时序预测、动态软测量               基于因果、扩张卷积的时序模型

  SINDy                                        2016 非线性动力学方程发现、动态系统辨识       从数据中识别稀疏、可解释的动力学方程

  Neural                        2021 在线发表、2022 非线性状态空间建模、状态估计、过程监测   学习非线性状态转移和观测关系
  State-Space        正式刊载的工业过程监测代表研究                                          

  TimeXer                                      2024 带外生变量的多变量时间序列预测           现代 Transformer 时序预测模型
  ---------------------------------------------------------------------------------------------------------------------------------

### 2.1 XGBoost

**代表性论文：** Chen 与 Guestrin, *XGBoost: A Scalable Tree Boosting
System*, KDD 2016。\
**DOI：** https://doi.org/10.1145/2939672.2939785

**主要用途：** - 工业结构化数据非线性回归。 - 产品质量预测和软测量。 -
工艺参数与质量指标之间的非线性关系建模。 - 特征重要性等辅助解释信息。

**首版建议范围：** - 首先实现单目标回归。 -
严格保留输入特征顺序和目标列定义。 -
首版不自动生成滞后特征；若使用历史特征，必须由实验契约明确声明。 -
训练、验证、测试分区沿用统一实验契约。 - 预处理只能在 Train 分区拟合。 -
预测和评价必须加载同一个已保存 model_id，不允许隐式重训。

**边界：** XGBoost
本身不是动态系统辨识算法。即使使用滞后特征，它仍是基于构造特征的监督预测，不应描述成原生状态空间或传递函数辨识。

### 2.2 TCN

**代表性论文：** Bai、Kolter、Koltun, *An Empirical Evaluation of
Generic Convolutional and Recurrent Networks for Sequence Modeling*,
2018。\
**论文：** https://arxiv.org/abs/1803.01271

TCN
是一类时序卷积架构。代表性设计使用因果卷积、扩张卷积和残差结构，以捕获较长历史范围并避免未来信息泄漏。

**流程工业应用示例：** - *A temporal convolution network-based
just-in-time learning method for industrial quality variable
prediction*, Chemical Engineering Research and Design, 2024。\
https://doi.org/10.1016/j.cherd.2024.11.003 - *Integration of Encoding
and Temporal Forecasting: Toward End-to-End NOx Prediction for
Industrial Chemical Process*, IEEE TNNLS, 2024。\
https://doi.org/10.1109/TNNLS.2023.3276593

**主要用途：** - 工业多变量时间序列预测。 - 动态软测量。 -
质量变量随时间变化的预测。 - 捕获非线性时间依赖。

**首版设计要求：** - 明确采用 sequence-to-one 还是
sequence-to-horizon，不得混用。 - 明确 lookback、预测 horizon、窗口
stride、目标时间戳对齐方式。 - 使用严格的时间顺序切分。 -
窗口不能跨越不连续运行区段。 - Train/Validation/Test
边界设置历史窗口与预测目标 guard，避免窗口重叠造成泄漏。 -
标准化器等可学习预处理只能在 Train 上拟合。 -
首版实现离线训练和固定模型预测，不承诺在线增量学习。

### 2.3 SINDy

**代表性论文：** Brunton、Proctor、Kutz, *Discovering governing
equations from data by sparse identification of nonlinear dynamical
systems*, PNAS, 2016。\
**DOI：** https://doi.org/10.1073/pnas.1517384113

SINDy（Sparse Identification of Nonlinear
Dynamics）构造候选函数库，并通过稀疏回归筛选少量重要项，从观测数据中识别动力学方程。

**流程工业应用示例：** - *Real-time adaptive sparse-identification-based
predictive control of nonlinear processes*, Chemical Engineering
Research and Design, 2023。\
https://doi.org/10.1016/j.cherd.2023.07.011

**主要用途：** - 非线性动力学方程发现。 - 可解释动态模型构建。 -
为模型预测控制等后续任务提供显式动力学表达。

**首版设计必须先决策：** - 连续时间模型还是离散时间模型。 -
连续时间情况下如何估计导数；普通差分对噪声敏感，应评估平滑微分或积分/弱形式方法。 -
候选函数库包含哪些项：多项式、交叉项、用户指定函数等。 -
稀疏优化器和正则化参数如何配置。 - 输入变量与状态变量如何区分。 -
如何评价方程复杂度、残差、稳定性和预测能力。

**边界：** SINDy 不是普通的 `fit(X, y)`
静态回归器。输出应包含方程结构、系数、变量顺序、候选函数库配置和拟合来源。不得为了复用
PLS 接口而抹去其动力学辨识语义。

### 2.4 Neural State-Space

**代表性工业研究：** *Deep Neural Network-Embedded Stochastic Nonlinear
State-Space Models and Their Applications to Process Monitoring*, IEEE
Transactions on Neural Networks and Learning Systems，2021
年在线发表、2022 年正式刊载。\
**DOI：** https://doi.org/10.1109/TNNLS.2021.3086323

该研究使用深度神经网络表示非线性状态转移和观测生成关系，并面向过程监测构建状态估计机制。它是本规划采用的代表性研究，不意味着
Neural State-Space 是在 2021 年才首次出现的单一算法。

**主要用途：** - 非线性动态系统建模。 - 潜在状态估计。 -
动态过程监测。 - 处理非线性、动态性和不确定性。

**首版设计必须先决策：** - 状态维数及其确定方式。 -
状态转移函数与观测函数的参数化方式。 - 初始状态如何确定。 - 使用
filtering、smoothing 还是两者。 -
训练损失采用一步预测还是多步滚动预测。 -
如何处理不规则采样、缺失值和运行区段边界。 -
如何评价状态估计、预测误差和异常监测性能。

**边界：** Neural State-Space
是一类模型架构，不是一个唯一固定的算法名称。Codex
必须先给出可执行的首版定义，说明取舍和局限，再等待确认；不得自行把任意
RNN 包装成 Neural State-Space。

### 2.5 Transformer / TimeXer

**代表性论文：** Wang 等, *TimeXer: Empowering Transformers for Time
Series Forecasting with Exogenous Variables*, NeurIPS 2024。\
**论文：**
https://proceedings.neurips.cc/paper_files/paper/2024/hash/0113ef4642264adc2e6924a3cbbdf532-Abstract-Conference.html

TimeXer 专门研究带外生变量的时间序列预测。论文使用 patch-wise
self-attention 与 variate-wise cross-attention
协调目标变量和外生变量信息，并在 12
个真实世界预测基准上报告了有竞争力的结果。

**主要用途：** - 利用温度、压力、流量等外生变量预测目标质量变量。 -
多变量时间序列预测。 - 学习变量之间及时间片段之间的关联。

**首版设计要求：** - 优先参考原论文公开实现，核对许可、依赖和版本。 -
明确 endogenous target 与 exogenous covariates 的组织方式。 -
明确历史窗口、预测 horizon、变量维度和时间戳对齐。 - 预处理仅在 Train
数据拟合。 - 保存足以复现预测的模型参数、配置、实现版本和依赖版本。 -
不把通用基准上的表现直接宣传为已证明的工业优势。

**边界：** TimeXer
原始论文的通用预测基准不等于流程工业现场部署案例。产品描述必须区分通用基准证据与工业应用证据。

------------------------------------------------------------------------

## 3. 模型能力边界与数据契约

五个模型不是同一类算法，不应强行使用完全相同的输入和训练语义。

  -----------------------------------------------------------------------------------------------
  能力类别              模型              输入语义                      输出语义
  --------------------- ----------------- ----------------------------- -------------------------
  静态/特征化监督回归   XGBoost           样本 × 特征矩阵               回归预测

  时序预测              TCN               批次 × 历史窗口 × 特征        目标预测序列/预测时域

  动态方程辨识          SINDy             状态、输入及时间序列          显式稀疏动力学方程

  非线性状态空间        Neural            输入/观测序列及初始状态约束   状态估计、观测重构/预测
                        State-Space                                     

  外生变量时序预测      TimeXer           目标历史序列 +                目标未来序列
                                          外生变量历史/可用未来信息     
  -----------------------------------------------------------------------------------------------

**共同基础应统一，模型特有语义必须保留。**

应尽可能复用： - Dataset / DatasetVersion / SHA256 绑定。 - Experiment
身份、来源追踪和数据分区。 - ProcessingRun 及运行状态管理。 - Artifact
身份、摘要、路径安全和统一加载入口。 - 统一模型注册与能力描述。 -
统一评价结果记录、历史查询和 API 错误封装。 - 固定模型评价原则。 -
手动模型选择与 Agent 推荐共存机制。

但不得强迫所有模型使用 PLS 的静态 `X, y`
契约。应按任务类型扩展数据契约，例如静态回归、序列预测、动力学方程辨识和状态空间建模。

## 4. 总体开发原则

### 4.1 先审计，再实施

每个模型开发前先审计： 1. Registry 能否表达其类型、能力和成熟度。 2.
Experiment Spec 能否表达输入、目标、时间、分区及预测语义。 3.
数据读取器是否能提供正确的数据结构。 4. Train-only
预处理如何实现和证明。 5. 训练结果如何保存和恢复。 6. Artifact /
Manifest 如何扩展。 7. 固定模型如何预测和评价。 8. API 如何接入。 9.
需要哪些依赖及版本。 10. 是否会影响 ARX/FIR/OE/PLS。

审计报告完成后，先由用户确认技术方案和授权文件范围，再实施。

### 4.2 一个模型一个纵向闭环

每个模型原则上按以下顺序完成： 1. 参数 Schema 与模型能力注册。 2.
实验契约与数据绑定。 3. 训练核心实现。 4. Train-only 预处理。 5. 模型
Artifact 保存和安全加载。 6. ProcessingRun 来源关联。 7. 统一 Manifest。
8. 固定模型预测。 9. 固定模型评价和历史记录。 10. API 接入。 11.
定向测试及必要兼容回归。

可以把共用基础设施抽取为独立阶段，但不能为每个模型重复建设。

### 4.3 禁止隐式拟合

-   `predict` 不得 fit。
-   `evaluate` 不得重新训练。
-   模型加载不得拟合。
-   Manifest 构建和重试不得拟合。
-   评价必须使用原 `model_id`。
-   不得为了提高测试指标而在 Test 上拟合预处理或选择模型。
-   模型选择和超参数搜索只能使用明确授权的训练/验证数据。

### 4.4 数据泄漏控制

-   先切分，再拟合预处理。
-   缩放、插补、特征选择等可学习变换只在 Train 上拟合。
-   时间序列必须按时间顺序切分。
-   历史窗口不能跨越不连续运行区段。
-   预测目标不能越过允许的时间边界。
-   Validation/Test 不得与训练样本或其目标窗口重叠。
-   无法证明预处理拟合来源时，泄漏状态保持
    `unknown`，不得仅凭请求声明升级为 verified。

### 4.5 统一 Artifact 与来源追踪

-   不把完整 sklearn/PyTorch 模型对象不加限制地 pickle 保存。
-   优先采用明确、可校验、可版本化的数值 Payload。
-   NPZ 等格式使用安全加载方式，例如 `allow_pickle=False`。
-   保存模型类型、model_id、training_run_id、实现版本、依赖版本、变量顺序、训练数据版本、Spec
    摘要、实际训练行和 Payload 摘要。
-   训练运行、Artifact 和 Manifest 必须交叉校验。
-   历史来源缺失时如实标记，不伪造来源证明。
-   加载失败不得静默回退到不安全的旧路径。

### 4.6 评价必须使用固定模型

-   训练只发生在训练入口。
-   Validation/Test 评价使用已保存的同一个 model_id。
-   每次评价创建独立 evaluation_run_id。
-   不覆盖训练记录或历史评价记录。
-   统一记录实际评价 RowSet、样本数、指标和数据版本。
-   不只报告 R²；根据任务增加
    RMSE、MAE、NRMSE、残差诊断、稳定性或方程复杂度等适用指标。
-   不同模型只有在任务、数据版本、目标定义、预测时域和评价行一致时，才允许直接横向比较。

### 4.7 人工决策与 Agent 推荐

-   用户可以手动选择模型。
-   Agent 可以根据任务和数据特征推荐模型。
-   Agent 推荐必须给出理由、适用条件和限制。
-   Agent 不得覆盖用户选择。
-   Agent 不得擅自改变 Experiment Spec、训练/测试划分或模型参数。
-   Agent 推荐和人工选择都应留下来源记录。

### 4.8 控制开发范围

-   本轮只开发已确定的五个模型。
-   GNN 暂缓。
-   不顺手加入 RF、SVR、LSTM、GRU、NARX、NARMAX、ARMAX、BJ、DPCA、DPLS
    等模型。
-   不为追求模型数量而开发功能重复的变体。
-   不在单个模型阶段顺便重构 Agent、Optuna 或前端无关模块。

## 5. 建议实施顺序

以下为初步建议，最终顺序应结合架构审计、依赖和数据契约复用情况确定。

  ----------------------------------------------------------------------------------------------------------
  顺序                    模型                    原因
  ----------------------- ----------------------- ----------------------------------------------------------
  1                       XGBoost                 与现有 PLS 静态监督回归链路最接近，可先验证扩展复用方式

  2                       TCN                     建立统一时序窗口、序列切分和动态预测基础

  3                       TimeXer                 可复用部分序列数据契约，但需要外生变量专属组织方式

  4                       SINDy                   专用动力学方程辨识契约，需解决导数估计、函数库和稀疏优化

  5                       Neural State-Space      状态维数、状态估计和训练目标较复杂，安排在后续
  ----------------------------------------------------------------------------------------------------------

这不是不可更改的强制顺序。若审计发现 SINDy 首版实现更轻量，或 Neural
State-Space 与现有动态辨识基础更容易整合，可以提出调整，但必须说明理由。

## 6. 统一验收标准

每个模型至少证明：

**功能正确性** - 参数校验有效。 - 输入输出形状和变量顺序正确。 -
训练结果符合模型定义。 - 预测结果有限且可复现。 -
模型专属能力真实实现，而不是只注册名称。

**数据正确性** - DatasetVersion 和 SHA256 正确绑定。 -
训练行集合准确。 - 时间序列窗口和目标对齐准确。 - 不跨越连续运行区段。 -
Train-only 预处理得到验证。

**生命周期** - 训练生成唯一 model_id 和 training_run_id。 - Artifact
能安全保存和加载。 - Manifest 能发布和验证。 -
固定模型预测不触发拟合。 - 固定模型评价使用相同 model_id。 -
每次评价有独立 evaluation_run_id。 - 历史记录能正确查询。

**兼容性** - ARX/FIR/OE 原有行为不被破坏。 - PLS
已有核心训练、Artifact、Manifest、评价和 API 不被破坏。 -
不新增数据库表或迁移，除非单独论证并取得批准。 - 不改变既有历史 Artifact
格式。

**测试** - 新增模型专属正向、反向和边界测试。 - 关键路径禁止隐式 fit。 -
对数据泄漏、分区边界、Artifact 损坏和来源不匹配进行反例测试。 -
只运行相关定向测试和必要回归，不无条件运行全项目测试。

## 7. 当前项目基线与协作约定

### 已有模型能力

-   ARX：已有。
-   FIR：已有。
-   OE：已有，仍需保留实验性成熟度标记。
-   PLS：已完成核心训练、JSON/NPZ Artifact、DatasetVersion
    绑定、ProcessingRun、统一 Manifest、固定模型评价、评价历史和五类业务
    API。

PLS 是后续模型扩展的重要参考实现，但不是所有模型的数据契约模板。

### 项目环境

-   项目路径：`E:\服外\A14`
-   后端路径：`E:\服外\A14\backend`
-   分支：`feat/agent-execution-workflow`
-   Python：项目 `.venv-win`，Python 3.11.3
-   解释器：`E:\服外\A14\backend\.venv-win\Scripts\python.exe`
-   已确认的 PLS 环境：NumPy 2.4.6、SciPy 1.17.1、scikit-learn
    1.7.2、joblib 1.5.3。
-   PyTorch、XGBoost、PySINDy 等依赖是否已经安装，必须由 Codex
    只读检查，不得猜测。

### Git 与文件保护

-   Git add、commit、push 全部由用户本人执行。
-   Commit Summary 和 Description 必须使用中文。
-   不得执行 git reset、checkout、clean 等破坏性操作。
-   不得覆盖或清理用户未提交修改。
-   受保护文件
    `docs/submission-materials/浙江工业大学-A14-完整资料包.zip`
    不提交、不修改、不删除。
-   不允许扫描整个磁盘寻找项目文件；使用已知项目路径和定向源码定位。
-   若路径不明，先向用户确认。
-   一次推进一个明确阶段，减少无关验证。

## 8. 本轮明确不做的事情

当前规划阶段不进行： - 五个模型同时编码。 -
真实工业数据完整闭环验证（用户决定待模型开发完成后统一进行）。 -
前端工作台开发。 - Agent 自动推荐实现。 - Optuna 大规模优化流程改造。 -
数据库表和迁移变更。 - ARX/FIR/OE/PLS 算法重写。 - GNN 开发。 -
无关依赖升级或全项目重构。

## 9. 参考文献与官方资料

1.  XGBoost, Chen & Guestrin, KDD 2016:
    https://doi.org/10.1145/2939672.2939785
2.  TCN, Bai et al., 2018: https://arxiv.org/abs/1803.01271
3.  工业 TCN 软测量, Chemical Engineering Research and Design, 2024:
    https://doi.org/10.1016/j.cherd.2024.11.003
4.  FCC 工业 NOx 预测 TCN, IEEE TNNLS, 2024:
    https://doi.org/10.1109/TNNLS.2023.3276593
5.  SINDy, Brunton et al., PNAS 2016:
    https://doi.org/10.1073/pnas.1517384113
6.  SINDy 非线性过程预测控制, Chemical Engineering Research and Design,
    2023: https://doi.org/10.1016/j.cherd.2023.07.011
7.  Neural State-Space 工业过程监测, IEEE TNNLS, 2021 online / 2022
    issue: https://doi.org/10.1109/TNNLS.2021.3086323
8.  TimeXer, NeurIPS 2024:
    https://proceedings.neurips.cc/paper_files/paper/2024/hash/0113ef4642264adc2e6924a3cbbdf532-Abstract-Conference.html

## 10. 最终原则

> 先把模型定义清楚，再把数据语义定义清楚；先证明训练正确，再接入持久化、加载、预测和评价；先完成一个模型的纵向闭环，再扩展下一个模型。

最终目标不是让 Registry
中出现五个新名字，而是让五个模型都具备真实、可验证、可追踪、可比较的业务能力，同时保留它们各自正确的数学语义。

本文件是五模型研发的长期约束文件。后续 Codex
指令应引用本文件，并遵守其中的范围、数据安全、来源追踪、固定模型评价和
Git 约定。
