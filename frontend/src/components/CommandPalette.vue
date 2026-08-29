<template>
  <teleport to="body">
    <div
      v-if="isOpen"
      class="cmd-palette-backdrop"
      @click.self="close"
      @keydown.esc="close"
    >
      <div class="cmd-palette-modal" role="dialog" aria-modal="true" aria-label="快捷指令面板">
        <!-- Search Input Bar -->
        <div class="cmd-search-wrapper">
          <el-icon class="cmd-search-icon"><Search /></el-icon>
          <input
            ref="inputRef"
            v-model="query"
            type="text"
            placeholder="搜索功能模块、算法步骤或执行指令... (例如: ARX, 寻优, 时滞)"
            class="cmd-input"
            @keydown.down.prevent="moveSelection(1)"
            @keydown.up.prevent="moveSelection(-1)"
            @keydown.enter.prevent="executeSelected"
          />
          <span class="cmd-esc-badge" @click="close">ESC</span>
        </div>

        <!-- Suggestions List -->
        <div class="cmd-list" ref="listRef">
          <template v-if="groupedItems.length > 0">
            <div v-for="group in groupedItems" :key="group.category" class="cmd-group">
              <div class="cmd-group-title">{{ group.category }}</div>
              <div
                v-for="item in group.items"
                :key="item.id"
                class="cmd-item"
                :class="{ active: selectedId === item.id }"
                @click="executeItem(item)"
                @mouseenter="selectedId = item.id"
              >
                <div class="cmd-item-left">
                  <component :is="item.icon" class="cmd-item-icon" />
                  <div class="cmd-item-text">
                    <span class="cmd-item-title">{{ item.title }}</span>
                    <span v-if="item.sub" class="cmd-item-sub">{{ item.sub }}</span>
                  </div>
                </div>
                <div class="cmd-item-right">
                  <span v-if="item.shortcut" class="cmd-item-shortcut">{{ item.shortcut }}</span>
                  <el-icon class="cmd-enter-icon"><Right /></el-icon>
                </div>
              </div>
            </div>
          </template>

          <div v-else class="cmd-empty">
            <el-icon><Warning /></el-icon>
            <span>未找到匹配的指令或页面</span>
          </div>
        </div>

        <!-- Footer Help -->
        <div class="cmd-footer">
          <div class="footer-keys">
            <span><kbd>↑</kbd><kbd>↓</kbd> 移动选择</span>
            <span><kbd>Enter</kbd> 确认跳转</span>
            <span><kbd>Esc</kbd> 关闭面板</span>
          </div>
          <div class="footer-brand font-mono">IndusOpt Command Hub</div>
        </div>
      </div>
    </div>
  </teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import {
  Search,
  Right,
  Warning,
  Odometer,
  Cpu,
  FolderOpened,
  Operation,
  TrendCharts,
  ChatDotSquare,
  Document,
  Setting,
  Lightning,
  Histogram,
  Compass,
} from "@element-plus/icons-vue";

interface CommandItem {
  id: string;
  category: "常用导航" | "预处理与优选" | "建模与寻优" | "分析与交付";
  title: string;
  sub?: string;
  shortcut?: string;
  path?: string;
  action?: () => void;
  icon: any;
}

const router = useRouter();
const isOpen = ref(false);
const query = ref("");
const selectedId = ref("");
const inputRef = ref<HTMLInputElement | null>(null);
const listRef = ref<HTMLElement | null>(null);

const allCommands: CommandItem[] = [
  {
    id: "dashboard",
    category: "常用导航",
    title: "工作台概览 (Dashboard)",
    sub: "查看当前任务与模型排行榜",
    shortcut: "G D",
    path: "/dashboard",
    icon: Odometer,
  },
  {
    id: "copilot",
    category: "常用导航",
    title: "Agent 协作工作台 (Copilot)",
    sub: "自然语言驱动白名单工作流编排",
    shortcut: "G C",
    path: "/copilot",
    icon: ChatDotSquare,
  },
  {
    id: "datasets",
    category: "常用导航",
    title: "数据资产中心 (Datasets)",
    sub: "管理已上传 CSV 与不可变数据版本",
    shortcut: "G A",
    path: "/datasets",
    icon: FolderOpened,
  },
  {
    id: "simulation",
    category: "常用导航",
    title: "仿真数据生成器 (Simulation)",
    sub: "生成 S1/S3/S6 带真值标准工况数据",
    shortcut: "G S",
    path: "/simulation",
    icon: Cpu,
  },
  {
    id: "cleaning",
    category: "预处理与优选",
    title: "时间规整与清洗 (Cleaning)",
    sub: "重采样、缺失填补与 3σ 异常过滤",
    path: "/preprocessing/cleaning",
    icon: Operation,
  },
  {
    id: "segmentation",
    category: "预处理与优选",
    title: "质量约束 D-最优优选 (Segmentation)",
    sub: "动态信噪比门控与信息矩阵行列式极大化",
    path: "/preprocessing/segmentation",
    icon: Histogram,
  },
  {
    id: "delay",
    category: "预处理与优选",
    title: "多变量时滞分析 (Delay Compensation)",
    sub: "预白化互相关估计与通道移位对齐",
    path: "/preprocessing/delay",
    icon: Compass,
  },
  {
    id: "collinearity",
    category: "预处理与优选",
    title: "共线性与变量筛选 (Collinearity)",
    sub: "VIF 方差膨胀因子检测与特征剔除",
    path: "/preprocessing/collinearity",
    icon: Operation,
  },
  {
    id: "arx",
    category: "建模与寻优",
    title: "ARX 系统辨识 (ARX Modeling)",
    sub: "QR 最小二乘辨识与滚动自由仿真 FIT 评测",
    path: "/modeling/arx",
    icon: TrendCharts,
  },
  {
    id: "optimization",
    category: "建模与寻优",
    title: "Optuna 闭环寻优 (Hyperparameter Search)",
    sub: "贝叶斯 TPE 分级搜索与历史策略热启动",
    path: "/modeling/optimization",
    icon: Lightning,
  },
  {
    id: "benchmark",
    category: "分析与交付",
    title: "一键自评测基准 (Benchmark)",
    sub: "执行 10 组随机种子消融实验与敏感性扫描",
    path: "/benchmark",
    icon: Odometer,
  },
  {
    id: "deliverables",
    category: "分析与交付",
    title: "报告与数据交付 (Deliverables)",
    sub: "导出全数值可溯源图文报告与优选 CSV",
    path: "/deliverables",
    icon: Document,
  },
  {
    id: "settings",
    category: "分析与交付",
    title: "系统设置 (Settings)",
    sub: "大模型 Provider 运行时配置与网络测试",
    path: "/settings",
    icon: Setting,
  },
];

const filteredCommands = computed(() => {
  const q = query.value.trim().toLowerCase();
  if (!q) return allCommands;
  return allCommands.filter(
    (c) =>
      c.title.toLowerCase().includes(q) ||
      (c.sub && c.sub.toLowerCase().includes(q)) ||
      c.category.toLowerCase().includes(q) ||
      c.id.toLowerCase().includes(q)
  );
});

const groupedItems = computed(() => {
  const categories: CommandItem["category"][] = [
    "常用导航",
    "预处理与优选",
    "建模与寻优",
    "分析与交付",
  ];
  return categories
    .map((cat) => ({
      category: cat,
      items: filteredCommands.value.filter((item) => item.category === cat),
    }))
    .filter((g) => g.items.length > 0);
});

const flatFilteredItems = computed(() => {
  return groupedItems.value.flatMap((g) => g.items);
});

watch(flatFilteredItems, (newItems) => {
  if (newItems.length > 0 && !newItems.some((i) => i.id === selectedId.value)) {
    selectedId.value = newItems[0].id;
  }
});

function open() {
  isOpen.value = true;
  query.value = "";
  if (flatFilteredItems.value.length > 0) {
    selectedId.value = flatFilteredItems.value[0].id;
  }
  nextTick(() => {
    inputRef.value?.focus();
  });
}

function close() {
  isOpen.value = false;
}

function moveSelection(direction: 1 | -1) {
  const items = flatFilteredItems.value;
  if (items.length === 0) return;
  const currentIndex = items.findIndex((i) => i.id === selectedId.value);
  let nextIndex = currentIndex + direction;
  if (nextIndex < 0) nextIndex = items.length - 1;
  if (nextIndex >= items.length) nextIndex = 0;
  selectedId.value = items[nextIndex].id;
}

function executeSelected() {
  const current = flatFilteredItems.value.find((i) => i.id === selectedId.value);
  if (current) {
    executeItem(current);
  }
}

function executeItem(item: CommandItem) {
  close();
  if (item.action) {
    item.action();
  } else if (item.path) {
    router.push(item.path);
  }
}

function handleGlobalKeydown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    if (isOpen.value) {
      close();
    } else {
      open();
    }
  }
}

onMounted(() => {
  window.addEventListener("keydown", handleGlobalKeydown);
});

onBeforeUnmount(() => {
  window.removeEventListener("keydown", handleGlobalKeydown);
});

defineExpose({
  open,
  close,
});
</script>

<style scoped>
.cmd-palette-backdrop {
  position: fixed;
  inset: 0;
  z-index: 9999;
  background: rgba(0, 0, 0, 0.65);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: clamp(60px, 12vh, 120px);
  animation: fadeIn 0.15s ease-out;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.cmd-palette-modal {
  width: min(640px, 92vw);
  background: #111822;
  border: 1px solid #2d3b4e;
  border-radius: 8px;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.55);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  animation: slideDown 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes slideDown {
  from { transform: translateY(-12px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}

.cmd-search-wrapper {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  border-bottom: 1px solid #222f3e;
  background: #16202c;
}

.cmd-search-icon {
  font-size: 18px;
  color: #7a8c9e;
}

.cmd-input {
  flex: 1;
  background: transparent;
  border: none;
  color: #f1f5f9;
  font-size: 15px;
  outline: none;
  line-height: 1.4;
}

.cmd-input::placeholder {
  color: #64748b;
  font-size: 14px;
}

.cmd-esc-badge {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 2px 6px;
  background: #253342;
  color: #94a3b8;
  border-radius: 4px;
  border: 1px solid #334454;
  cursor: pointer;
}

.cmd-list {
  max-height: 380px;
  overflow-y: auto;
  padding: 10px;
}

.cmd-group-title {
  padding: 8px 10px 4px;
  font-size: 11px;
  font-weight: 700;
  color: #5c6e82;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.cmd-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background-color 0.12s ease;
  color: #cbd5e1;
}

.cmd-item:hover, .cmd-item.active {
  background: #1e2c3c;
  color: #ffffff;
}

.cmd-item-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.cmd-item-icon {
  font-size: 16px;
  color: #63add3;
  flex-shrink: 0;
}

.cmd-item-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.cmd-item-title {
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cmd-item-sub {
  font-size: 11px;
  color: #64748b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cmd-item.active .cmd-item-sub {
  color: #94a3b8;
}

.cmd-item-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.cmd-item-shortcut {
  font-family: var(--font-mono);
  font-size: 10px;
  color: #64748b;
  background: #182330;
  padding: 1px 5px;
  border-radius: 3px;
  border: 1px solid #2d3b4e;
}

.cmd-enter-icon {
  font-size: 12px;
  color: #64748b;
  opacity: 0;
}

.cmd-item.active .cmd-enter-icon {
  opacity: 1;
  color: #63add3;
}

.cmd-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 36px 16px;
  color: #64748b;
  font-size: 13px;
}

.cmd-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  background: #0d141d;
  border-top: 1px solid #1c2633;
  font-size: 11px;
  color: #5c6e82;
}

.footer-keys {
  display: flex;
  align-items: center;
  gap: 12px;
}

.footer-keys kbd {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 1px 4px;
  background: #192430;
  border: 1px solid #2d3b4e;
  border-radius: 3px;
  color: #94a3b8;
  margin-right: 3px;
}

.footer-brand {
  font-size: 10px;
  letter-spacing: 0.04em;
}
</style>
