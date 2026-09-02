<template>
  <div class="page-container assets-view">
    <PageHeader
      eyebrow="DATA & MODEL / ASSETS"
      title="资产中心"
      description="统一管理工业时序数据集、处理版本、ARX 辨识模型、Optuna 参数寻优及分析交付报告"
    />

    <!-- Quick navigation cards -->
    <div class="assets-grid">
      <router-link to="/datasets" class="asset-card">
        <div class="asset-card__icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <ellipse cx="12" cy="5" rx="9" ry="3"/>
            <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
            <path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/>
          </svg>
        </div>
        <div class="asset-card__body">
          <div class="asset-card__title">数据集与版本</div>
          <div class="asset-card__desc">工业时序数据导入、列角色配置与数据版本谱系追踪</div>
        </div>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" class="card-arrow"><path d="m9 18 6-6-6-6"/></svg>
      </router-link>

      <router-link to="/modeling/arx" class="asset-card">
        <div class="asset-card__icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
          </svg>
        </div>
        <div class="asset-card__body">
          <div class="asset-card__title">ARX 辨识模型</div>
          <div class="asset-card__desc">离散系统辨识结构求解、拟合度 FIT 与残差独立性验证</div>
        </div>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" class="card-arrow"><path d="m9 18 6-6-6-6"/></svg>
      </router-link>

      <router-link to="/modeling/optimization" class="asset-card">
        <div class="asset-card__icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="m13 2-2 2.5h3L12 7"/><path d="M10 14v-3"/><path d="M14 14v-3"/><path d="M16 14v-3"/><path d="M8 14v-3"/><path d="M4 14h16a2 2 0 0 1 0 4H4a2 2 0 0 1 0-4z"/>
          </svg>
        </div>
        <div class="asset-card__body">
          <div class="asset-card__title">闭环参数寻优</div>
          <div class="asset-card__desc">Optuna 贝叶斯搜索、试验收敛曲线与特征重要度分析</div>
        </div>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" class="card-arrow"><path d="m9 18 6-6-6-6"/></svg>
      </router-link>

      <router-link to="/deliverables" class="asset-card">
        <div class="asset-card__icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" x2="8" y1="13" y2="13"/><line x1="16" x2="8" y1="17" y2="17"/><polyline points="10 9 9 9 8 9"/>
          </svg>
        </div>
        <div class="asset-card__body">
          <div class="asset-card__title">报告与交付中心</div>
          <div class="asset-card__desc">基于执行记录生成 Markdown / PDF 报告与数据工件导出</div>
        </div>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" class="card-arrow"><path d="m9 18 6-6-6-6"/></svg>
      </router-link>

      <router-link to="/benchmark" class="asset-card">
        <div class="asset-card__icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" x2="18" y1="20" y2="10"/><line x1="12" x2="12" y1="20" y2="4"/><line x1="6" x2="6" y1="20" y2="14"/>
          </svg>
        </div>
        <div class="asset-card__body">
          <div class="asset-card__title">消融评测基准</div>
          <div class="asset-card__desc">4 策略对照真值自评测，实时验证算法主张</div>
        </div>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" class="card-arrow"><path d="m9 18 6-6-6-6"/></svg>
      </router-link>

      <router-link to="/simulation" class="asset-card">
        <div class="asset-card__icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
          </svg>
        </div>
        <div class="asset-card__body">
          <div class="asset-card__title">仿真工况数据集</div>
          <div class="asset-card__desc">构造包含精确物理真值的 S1~S6 标准工业测试场景</div>
        </div>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" class="card-arrow"><path d="m9 18 6-6-6-6"/></svg>
      </router-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import PageHeader from '../components/common/PageHeader.vue';
</script>

<style scoped>
.assets-view {
  min-height: 100%;
}

.assets-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
}

.asset-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 18px 20px;
  background: #FFFFFF;
  border: 1px solid #E8EAE5;
  border-radius: 10px;
  color: inherit;
  text-decoration: none;
  transition: all 0.15s ease;
}

.asset-card:hover {
  background: #F7F9F5;
  border-color: #D6DDD2;
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.asset-card__icon {
  width: 42px;
  height: 42px;
  border-radius: 8px;
  background: #F0F4EE;
  border: 1px solid #DFE6DC;
  color: #5E8358;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all 0.15s ease;
}

.asset-card:hover .asset-card__icon {
  background: #E8F0E5;
  color: #426340;
}

.asset-card__icon svg {
  width: 20px;
  height: 20px;
}

.asset-card__body {
  flex: 1;
  min-width: 0;
}

.asset-card__title {
  font-size: 15px;
  font-weight: 600;
  color: #2C332B;
  margin-bottom: 4px;
}

.asset-card:hover .asset-card__title {
  color: #426340;
}

.asset-card__desc {
  font-size: 13px;
  color: #747A72;
  line-height: 1.4;
}

.card-arrow {
  color: #A0A69D;
  transition: transform 0.15s ease, color 0.15s ease;
  flex-shrink: 0;
}

.asset-card:hover .card-arrow {
  color: #426340;
  transform: translateX(2px);
}
</style>
