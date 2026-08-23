<template>
  <aside class="app-sidebar" :class="{ collapsed: isCollapsed }">
    <div class="toggle-btn" @click="isCollapsed = !isCollapsed">
      <el-icon><Fold v-if="!isCollapsed" /><Expand v-else /></el-icon>
    </div>

    <el-menu
      :default-active="activePath"
      class="sidebar-menu"
      :collapse="isCollapsed"
      router
    >
      <el-menu-item index="/dashboard">
        <el-icon><Odometer /></el-icon>
        <template #title>工作台</template>
      </el-menu-item>

      <el-menu-item-group title="准备数据">
        <el-menu-item index="/simulation">
          <el-icon><Cpu /></el-icon>
          <template #title>生成仿真数据</template>
        </el-menu-item>
        <el-menu-item index="/datasets">
          <el-icon><FolderOpened /></el-icon>
          <template #title>数据资产</template>
        </el-menu-item>
      </el-menu-item-group>

      <el-menu-item-group title="分析与建模">
        <el-sub-menu index="/preprocessing">
          <template #title>
            <el-icon><Operation /></el-icon>
            <span>预处理与优选</span>
          </template>
          <el-menu-item index="/preprocessing/cleaning">时间规整与清洗</el-menu-item>
          <el-menu-item index="/preprocessing/segmentation">动态区间优选</el-menu-item>
          <el-menu-item index="/preprocessing/delay">多变量时滞分析</el-menu-item>
          <el-menu-item index="/preprocessing/collinearity">共线性与变量筛选</el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="/modeling">
          <template #title>
            <el-icon><TrendCharts /></el-icon>
            <span>辨识与寻优</span>
          </template>
          <el-menu-item index="/modeling/arx">ARX 系统辨识</el-menu-item>
          <el-menu-item index="/modeling/optimization">Optuna 闭环寻优</el-menu-item>
        </el-sub-menu>
      </el-menu-item-group>

      <el-menu-item-group title="协作与交付">
        <el-menu-item index="/copilot">
          <el-icon><ChatDotSquare /></el-icon>
          <template #title>Agent 工作台</template>
        </el-menu-item>
        <el-menu-item index="/benchmark">
          <el-icon><Odometer /></el-icon>
          <template #title>系统自评测</template>
        </el-menu-item>
        <el-menu-item index="/deliverables">
          <el-icon><Document /></el-icon>
          <template #title>报告与数据交付</template>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>
          <template #title>系统设置</template>
        </el-menu-item>
      </el-menu-item-group>
    </el-menu>
  </aside>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import { useRoute } from "vue-router";
import {
  Odometer,
  Cpu,
  FolderOpened,
  Operation,
  TrendCharts,
  ChatDotSquare,
  Document,
  Setting,
  Fold,
  Expand,
} from "@element-plus/icons-vue";

const route = useRoute();
const isCollapsed = ref(false);

const activePath = computed(() => route.path);
</script>

<style scoped>
.app-sidebar {
  width: 220px;
  background: var(--bg-sidebar);
  transition: width 0.2s ease;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.app-sidebar.collapsed {
  width: 64px;
}

.toggle-btn {
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 0 16px;
  color: #8d96a0;
  cursor: pointer;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.app-sidebar.collapsed .toggle-btn {
  justify-content: center;
  padding: 0;
}

.sidebar-menu {
  border-right: none;
  background: transparent;
  flex: 1;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-color: rgba(160, 174, 192, 0.45) transparent;
  scrollbar-width: thin;
}

.sidebar-menu::-webkit-scrollbar {
  width: 6px;
}

.sidebar-menu::-webkit-scrollbar-thumb {
  background: rgba(160, 174, 192, 0.45);
  border-radius: 999px;
}

.sidebar-menu::-webkit-scrollbar-track {
  background: transparent;
}

:deep(.el-menu) {
  background: transparent;
}

:deep(.el-menu-item), :deep(.el-sub-menu__title) {
  color: #a0aec0;
}

:deep(.el-menu-item:hover), :deep(.el-sub-menu__title:hover) {
  background: rgba(255, 255, 255, 0.06) !important;
  color: #ffffff;
}

:deep(.el-menu-item.is-active) {
  color: #ffffff !important;
  background: var(--color-primary) !important;
  font-weight: 600;
}

:deep(.el-menu-item-group__title) {
  padding: 16px 20px 6px !important;
  color: #6f7b8a;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.collapsed :deep(.el-menu-item-group__title) {
  display: none;
}
</style>
