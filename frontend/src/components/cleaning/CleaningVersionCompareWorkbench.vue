<template>
  <section class="industrial-card version-compare-workbench" aria-labelledby="version-compare-title">
    <header class="workbench-header">
      <div>
        <span class="workbench-eyebrow font-mono">VERSION COMPARE</span>
        <h3 id="version-compare-title">清洗版本对比</h3>
        <p>比较两个 Cleaning 阶段版本的数据变化与血缘关系。</p>
      </div>
      <el-tag v-if="result?.artifacts_identical" type="success" effect="light">数据内容一致</el-tag>
    </header>

    <div class="selector-grid">
      <div class="selector-field">
        <label>Baseline Version</label>
        <VersionLineagePicker
          data-test="compare-baseline-picker"
          :dataset-name="dataset?.name ?? ''"
          :versions="versions"
          :selected-version-id="baselineVersionId"
          :loading="false"
          context-label="仅原始或清洗规整版本可用于对比"
          eligible-label="可用于版本对比"
          empty-state-text="暂无可用于对比的数据版本。"
          empty-state-hint="请先上传、生成或清洗数据。"
          placeholder="选择比较基线"
          selected-badge-label="比较基线"
          :is-eligible="isCompareEligible"
          :disabled-reason="compareDisabledReason"
          @select="selectBaseline"
        />
      </div>

      <div class="selector-field">
        <label>Compare Version</label>
        <VersionLineagePicker
          data-test="compare-target-picker"
          :dataset-name="dataset?.name ?? ''"
          :versions="versions"
          :selected-version-id="compareVersionId"
          :loading="false"
          context-label="仅原始或清洗规整版本可用于对比"
          eligible-label="可用于版本对比"
          empty-state-text="暂无可用于对比的数据版本。"
          empty-state-hint="请先上传、生成或清洗数据。"
          placeholder="选择对照版本"
          selected-badge-label="对照版本"
          :is-eligible="isCompareEligible"
          :disabled-reason="compareDisabledReason"
          @select="selectCompare"
        />
      </div>
    </div>

    <div class="execution-row">
      <div class="channel-field">
        <label for="version-compare-channel">观察通道</label>
        <el-select
          id="version-compare-channel"
          v-model="selectedChannel"
          data-test="version-compare-channel"
          placeholder="选择共同数值通道"
          :loading="channelLoading"
          :disabled="channelLoading || !channelOptions.length"
        >
          <el-option
            v-for="option in channelOptions"
            :key="option.name"
            :label="channelLabel(option)"
            :value="option.name"
          />
        </el-select>
        <small v-if="channelLoading" class="loading-copy">正在读取共同数值通道…</small>
      </div>

      <el-button
        data-test="version-compare-submit"
        type="primary"
        :loading="compareLoading"
        :disabled="!canCompare"
        @click="executeCompare"
      >开始比较</el-button>
    </div>

    <el-alert
      v-if="channelError"
      class="inline-alert"
      type="error"
      :title="channelError"
      :closable="false"
      show-icon
    >
      <el-button size="small" plain @click="loadChannels">重新读取通道</el-button>
    </el-alert>
    <el-alert
      v-else-if="pairReady && !channelLoading && channelOptions.length === 0"
      class="inline-alert"
      type="info"
      title="两个版本没有可共同比较的数值通道。"
      :closable="false"
      show-icon
    />
    <el-alert
      v-if="channelWarnings.length"
      class="inline-alert"
      type="warning"
      :title="channelWarnings.join('；')"
      :closable="false"
      show-icon
    />

    <el-alert
      v-if="compareError"
      class="result-alert"
      type="error"
      :title="compareError"
      :closable="false"
      show-icon
    />
    <div v-if="compareLoading" class="compare-loading" data-test="compare-loading">
      正在比较完整版本数据…
    </div>

    <div v-else-if="result" class="compare-result" data-test="version-compare-result">
      <div class="summary-header">
        <div>
          <span class="summary-scope">SELECTED CHANNEL</span>
          <h4>数据差异 · 当前通道 {{ result.channel.name }}</h4>
          <p>{{ directionCopy }}</p>
        </div>
        <div class="summary-badges">
          <el-tag effect="plain">{{ relationCopy }}</el-tag>
          <el-tag v-if="result.artifacts_identical" type="success" effect="light">数据内容一致</el-tag>
        </div>
      </div>

      <el-alert
        v-if="result.relation === 'SAME_VERSION' && hasZeroDifference"
        class="result-alert"
        type="info"
        title="同一版本，无数据差异。"
        :closable="false"
        show-icon
      />

      <div class="metric-grid">
        <div class="metric-card changed"><span>值变化</span><strong>{{ result.generic_diff_summary.changed_values }}</strong></div>
        <div class="metric-card added"><span>新增点</span><strong>{{ result.generic_diff_summary.added_points }}</strong></div>
        <div class="metric-card removed"><span>移除点</span><strong>{{ result.generic_diff_summary.removed_points }}</strong></div>
        <div class="metric-card ambiguous"><span>对齐歧义组</span><strong>{{ result.generic_diff_summary.ambiguous_timestamp_groups }}</strong></div>
      </div>

      <div class="summary-secondary">
        <span>Baseline {{ result.generic_diff_summary.baseline_point_count }} points</span>
        <span>Compare {{ result.generic_diff_summary.compare_point_count }} points</span>
        <span v-if="result.generic_diff_summary.baseline_duplicate_occurrences > 0">
          Baseline 重复 occurrence {{ result.generic_diff_summary.baseline_duplicate_occurrences }}
        </span>
        <span v-if="result.generic_diff_summary.compare_duplicate_occurrences > 0">
          Compare 重复 occurrence {{ result.generic_diff_summary.compare_duplicate_occurrences }}
        </span>
      </div>

      <el-alert
        v-if="result.projection.applied"
        class="result-alert"
        type="info"
        title="图形已抽样显示，差异统计基于完整数据。"
        :closable="false"
        show-icon
      />
      <el-alert
        v-if="result.difference_points_truncated"
        class="result-alert"
        type="info"
        title="差异统计完整，图中仅显示部分差异点。"
        :closable="false"
        show-icon
      />
      <el-alert
        v-if="result.warnings.length"
        class="result-alert"
        type="warning"
        :title="result.warnings.join('；')"
        :closable="false"
        show-icon
      />

      <div class="chart-header">
        <div><strong>Overlay</strong><span>Baseline 与 Compare 共享真实时间轴</span></div>
        <el-button data-test="version-compare-reset-zoom" size="small" plain @click="resetZoom">重置视图</el-button>
      </div>
      <ChartContainer ref="chartRef" :options="overlayChartOptions" height="420px" />
      <p v-if="result.generic_diff_summary.ambiguous_timestamp_groups > 0" class="ambiguity-note">
        重复时间戳歧义仅按 timestamp group 汇总，图中未建立 occurrence 间的推测配对。
      </p>
    </div>

    <div v-else-if="!compareError" class="workbench-empty">
      <strong>选择两个版本与观察通道后开始比较</strong>
      <span>切换选择不会自动下载完整版本差异。</span>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, shallowRef, watch } from "vue";
import ChartContainer, { type ChartOption } from "../ChartContainer.vue";
import VersionLineagePicker from "../versioning/VersionLineagePicker.vue";
import { getCleaningVersionCompare, getCleaningVersionCompareChannels } from "../../api/datasets";
import { ApiError } from "../../api/client";
import type {
  CleaningVersionDirection,
  CleaningVersionCompareChannelOption,
  CleaningVersionCompareData,
  CleaningVersionRelation,
  DatasetItem,
  DatasetVersionNode,
  VersionComparePoint,
  VersionDifferencePoint,
} from "../../types/api";

defineOptions({ name: "CleaningVersionCompareWorkbench" });

const props = defineProps<{
  dataset: DatasetItem | null;
  versions: DatasetVersionNode[];
  currentVersionId: string | null;
}>();

type ChartAction = { type: string; start?: number; end?: number };
type ChartExpose = { dispatchAction: (action: ChartAction) => void };
type MarkerDatum = {
  value: [string, number];
  differenceKind: "VALUE_CHANGED" | "POINT_ADDED" | "POINT_REMOVED";
};

const ELIGIBLE_OPERATIONS = new Set(["simulation_generate", "raw_upload", "preprocessing.clean"]);
const BASELINE_COLOR = "#A8665E";
const COMPARE_COLOR = "#557562";
const CHANGED_COLOR = "#B5965D";

const baselineVersionId = ref<string | null>(null);
const compareVersionId = ref<string | null>(null);
const channelOptions = ref<CleaningVersionCompareChannelOption[]>([]);
const selectedChannel = ref<string | null>(null);
const channelWarnings = ref<string[]>([]);
const channelLoading = ref(false);
const channelError = ref("");
const compareLoading = ref(false);
const compareError = ref("");
const result = shallowRef<CleaningVersionCompareData | null>(null);
const chartRef = ref<ChartExpose | null>(null);
let channelRequestId = 0;
let compareRequestId = 0;

const isCompareEligible = (version: DatasetVersionNode) => ELIGIBLE_OPERATIONS.has(version.tool);
const compareDisabledReason = () => "已进入后续处理阶段，不属于 Cleaning 版本对比范围";
const pairReady = computed(() => !!props.dataset && !!baselineVersionId.value && !!compareVersionId.value);
const canCompare = computed(() => pairReady.value && !!selectedChannel.value && !channelLoading.value && !compareLoading.value);

const nearestEligibleAncestor = (current: DatasetVersionNode, byId: Map<string, DatasetVersionNode>) => {
  const visited = new Set<string>();
  let parentId = current.parent_version_id;
  while (parentId && !visited.has(parentId)) {
    visited.add(parentId);
    const parent = byId.get(parentId);
    if (!parent) return null;
    if (isCompareEligible(parent)) return parent;
    parentId = parent.parent_version_id;
  }
  return null;
};

const descendantDistance = (ancestorId: string, candidate: DatasetVersionNode, byId: Map<string, DatasetVersionNode>) => {
  const visited = new Set<string>();
  let current: DatasetVersionNode | undefined = candidate;
  let distance = 0;
  while (current.parent_version_id && !visited.has(current.id)) {
    visited.add(current.id);
    distance += 1;
    if (current.parent_version_id === ancestorId) return distance;
    current = byId.get(current.parent_version_id);
    if (!current) return null;
  }
  return null;
};

const applyDefaultPair = () => {
  const eligible = props.versions.filter(isCompareEligible);
  const current = eligible.find((version) => version.id === props.currentVersionId);
  if (!current) {
    baselineVersionId.value = null;
    compareVersionId.value = null;
    return;
  }
  if (eligible.length === 1) {
    baselineVersionId.value = current.id;
    compareVersionId.value = current.id;
    return;
  }
  const byId = new Map(props.versions.map((version) => [version.id, version]));
  const ancestor = nearestEligibleAncestor(current, byId);
  if (ancestor) {
    baselineVersionId.value = ancestor.id;
    compareVersionId.value = current.id;
    return;
  }
  baselineVersionId.value = current.id;
  const descendants = eligible
    .filter((version) => version.id !== current.id)
    .map((version) => ({ version, distance: descendantDistance(current.id, version, byId) }))
    .filter((entry): entry is { version: DatasetVersionNode; distance: number } => entry.distance !== null);
  const nearestDistance = Math.min(...descendants.map((entry) => entry.distance));
  const nearest = descendants.filter((entry) => entry.distance === nearestDistance);
  compareVersionId.value = nearest.length === 1 ? nearest[0].version.id : null;
};

const invalidateResult = () => {
  ++compareRequestId;
  compareLoading.value = false;
  compareError.value = "";
  result.value = null;
};

const currentPairMatches = (datasetId: string, baselineId: string, compareId: string) =>
  props.dataset?.id === datasetId && baselineVersionId.value === baselineId && compareVersionId.value === compareId;

const errorCopy = (prefix: string, error: unknown) => {
  if (error instanceof ApiError) return `${prefix} [${error.code}]：${error.message}`;
  return `${prefix}：${error instanceof Error ? error.message : "未知错误"}`;
};

const loadChannels = async () => {
  const requestId = ++channelRequestId;
  const preferredChannel = selectedChannel.value;
  channelOptions.value = [];
  selectedChannel.value = null;
  channelWarnings.value = [];
  channelError.value = "";
  invalidateResult();
  const datasetId = props.dataset?.id;
  const baselineId = baselineVersionId.value;
  const compareId = compareVersionId.value;
  if (!datasetId || !baselineId || !compareId) {
    channelLoading.value = false;
    return;
  }
  channelLoading.value = true;
  try {
    const response = await getCleaningVersionCompareChannels(datasetId, {
      baseline_version_id: baselineId,
      compare_version_id: compareId,
    });
    if (requestId !== channelRequestId || !currentPairMatches(datasetId, baselineId, compareId)) return;
    channelOptions.value = response.channels;
    channelWarnings.value = response.warnings;
    selectedChannel.value = response.channels.some((option) => option.name === preferredChannel)
      ? preferredChannel
      : response.channels[0]?.name ?? null;
  } catch (error) {
    if (requestId !== channelRequestId || !currentPairMatches(datasetId, baselineId, compareId)) return;
    channelError.value = errorCopy("共同通道加载失败", error);
  } finally {
    if (requestId === channelRequestId) channelLoading.value = false;
  }
};

const selectBaseline = (versionId: string) => { baselineVersionId.value = versionId; };
const selectCompare = (versionId: string) => { compareVersionId.value = versionId; };

const executeCompare = async () => {
  if (!canCompare.value) return;
  const datasetId = props.dataset!.id;
  const baselineId = baselineVersionId.value!;
  const compareId = compareVersionId.value!;
  const channel = selectedChannel.value!;
  const requestId = ++compareRequestId;
  result.value = null;
  compareError.value = "";
  compareLoading.value = true;
  try {
    const response = await getCleaningVersionCompare(datasetId, {
      baseline_version_id: baselineId,
      compare_version_id: compareId,
      channel,
      max_points: 10_000,
    });
    if (requestId !== compareRequestId || !currentPairMatches(datasetId, baselineId, compareId) || selectedChannel.value !== channel) return;
    result.value = response;
  } catch (error) {
    if (requestId !== compareRequestId || !currentPairMatches(datasetId, baselineId, compareId) || selectedChannel.value !== channel) return;
    compareError.value = errorCopy("版本比较失败", error);
  } finally {
    if (requestId === compareRequestId) compareLoading.value = false;
  }
};

const channelLabel = (option: CleaningVersionCompareChannelOption) => option.unit ? `${option.name} (${option.unit})` : option.name;
const RELATION_COPY: Record<CleaningVersionRelation, string> = {
  DIRECT_PARENT: "直接派生",
  ANCESTOR_DESCENDANT: "跨级祖先比较",
  SIBLING: "同源分支",
  SAME_VERSION: "同一版本",
  UNRELATED_WITHIN_DATASET: "同数据集独立分支",
};
const DIRECTION_COPY: Record<CleaningVersionDirection, string> = {
  BASELINE_TO_COMPARE: "Baseline → Compare",
  COMPARE_TO_BASELINE: "Compare → Baseline",
  NONE: "无派生方向",
};
const relationCopy = computed(() => result.value ? RELATION_COPY[result.value.relation] : "");
const directionCopy = computed(() => result.value ? DIRECTION_COPY[result.value.direction] : "");
const hasZeroDifference = computed(() => {
  const summary = result.value?.generic_diff_summary;
  return !!summary && summary.changed_values === 0 && summary.added_points === 0
    && summary.removed_points === 0 && summary.ambiguous_timestamp_groups === 0;
});

const lineData = (points: VersionComparePoint[]) => points.map((point) => [point.timestamp, point.value] as [string, number | null]);
const occurrenceMarkers = (
  difference: VersionDifferencePoint,
  side: "baseline" | "compare",
  kind: MarkerDatum["differenceKind"]
) => {
  const directValue = side === "baseline" ? difference.baseline_value : difference.compare_value;
  if (directValue !== null) return [{ value: [difference.timestamp, directValue], differenceKind: kind } satisfies MarkerDatum];
  const occurrences = side === "baseline" ? difference.baseline_occurrences : difference.compare_occurrences;
  return occurrences
    .filter((point) => point.value !== null)
    .map((point) => ({ value: [point.timestamp, point.value as number], differenceKind: kind } satisfies MarkerDatum));
};

const formatAxisTimestamp = (value: string | number) => {
  let timestamp = String(value);
  if (typeof value === "number") {
    const parsed = new Date(value);
    if (Number.isFinite(parsed.getTime())) timestamp = parsed.toISOString();
  }
  const match = timestamp.match(/[T ](\d{2}:\d{2}:\d{2})/);
  return match?.[1] ?? timestamp;
};
const formatTooltipTimestamp = (timestamp: string) => {
  const match = timestamp.replace("T", " ").match(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})/);
  return match?.[1] ?? timestamp.replace("T", " ");
};
const formatValue = (value: unknown) => {
  if (value === null || typeof value !== "number" || !Number.isFinite(value)) return "缺失";
  return value.toLocaleString("en-US", { useGrouping: false, maximumFractionDigits: 4 });
};

const overlayChartOptions = computed<ChartOption>(() => {
  const response = result.value;
  if (!response) return {};
  const changed: MarkerDatum[] = [];
  const added: MarkerDatum[] = [];
  const removed: MarkerDatum[] = [];
  for (const difference of response.difference_points) {
    if (difference.difference_kind === "VALUE_CHANGED" && difference.compare_value !== null) {
      changed.push({ value: [difference.timestamp, difference.compare_value], differenceKind: "VALUE_CHANGED" });
    } else if (difference.difference_kind === "POINT_ADDED") {
      added.push(...occurrenceMarkers(difference, "compare", "POINT_ADDED"));
    } else if (difference.difference_kind === "POINT_REMOVED") {
      removed.push(...occurrenceMarkers(difference, "baseline", "POINT_REMOVED"));
    }
  }
  return {
    animation: false,
    tooltip: {
      trigger: "axis",
      backgroundColor: "rgba(248, 248, 244, 0.97)",
      borderColor: "#C5CEC6",
      textStyle: { color: "#34443A", fontSize: 12 },
      formatter: (params: unknown) => {
        const entries = Array.isArray(params) ? params : [params];
        const validEntries = entries.filter((entry): entry is { seriesName?: string; value?: unknown } => !!entry && typeof entry === "object");
        const firstValue = validEntries[0]?.value;
        const timestamp = Array.isArray(firstValue) && typeof firstValue[0] === "string" ? firstValue[0] : "";
        return [
          timestamp ? `时间：${formatTooltipTimestamp(timestamp)}` : "",
          ...validEntries.map((entry) => {
            const value = Array.isArray(entry.value) ? entry.value[1] : null;
            return `${entry.seriesName ?? "数据"}：${formatValue(value)}`;
          }),
        ].filter(Boolean).join("<br/>");
      },
    },
    legend: { data: ["Baseline", "Compare"], top: 2, left: "center", itemGap: 22, textStyle: { color: "#536158", fontSize: 11 } },
    grid: { left: "3%", right: "4%", bottom: 72, top: "16%", containLabel: true },
    dataZoom: [
      { id: "version-compare-inside-zoom", type: "inside", xAxisIndex: 0, filterMode: "none", zoomOnMouseWheel: "ctrl", moveOnMouseWheel: false, moveOnMouseMove: true },
      { id: "version-compare-slider-zoom", type: "slider", xAxisIndex: 0, filterMode: "none", height: 18, bottom: 8, showDetail: false, brushSelect: false, backgroundColor: "#F2F5F1", borderColor: "#CDD5CE", fillerColor: "rgba(85, 117, 98, 0.18)" },
    ],
    xAxis: { type: "time", axisLabel: { formatter: formatAxisTimestamp, hideOverlap: true } },
    yAxis: { type: "value", scale: true },
    series: [
      { id: "version-compare-baseline", name: "Baseline", type: "line", showSymbol: false, connectNulls: false, lineStyle: { type: "dashed", width: 1.8, opacity: 0.72, color: BASELINE_COLOR }, itemStyle: { color: BASELINE_COLOR }, data: lineData(response.baseline_series.points), z: 2 },
      { id: "version-compare-target", name: "Compare", type: "line", showSymbol: false, connectNulls: false, lineStyle: { type: "solid", width: 2.6, color: COMPARE_COLOR }, itemStyle: { color: COMPARE_COLOR }, data: lineData(response.compare_series.points), z: 3 },
      { id: "version-difference-changed", name: "值变化", type: "scatter", silent: true, symbol: "emptyCircle", symbolSize: 9, itemStyle: { color: CHANGED_COLOR, borderColor: CHANGED_COLOR, borderWidth: 2 }, data: changed, z: 7 },
      { id: "version-difference-added", name: "新增点", type: "scatter", silent: true, symbol: "triangle", symbolSize: 10, itemStyle: { color: COMPARE_COLOR }, data: added, z: 7 },
      { id: "version-difference-removed", name: "移除点", type: "scatter", silent: true, symbol: "triangle", symbolRotate: 180, symbolSize: 10, itemStyle: { color: BASELINE_COLOR }, data: removed, z: 7 },
    ],
  };
});

const resetZoom = () => { chartRef.value?.dispatchAction({ type: "dataZoom", start: 0, end: 100 }); };

watch([() => props.dataset?.id, () => props.currentVersionId, () => props.versions], applyDefaultPair, { immediate: true });
watch([() => props.dataset?.id, baselineVersionId, compareVersionId], () => { void loadChannels(); }, { immediate: true });
watch(selectedChannel, (channel, previous) => { if (channel !== previous) invalidateResult(); });
</script>

<style scoped>
.version-compare-workbench { padding: 20px; background: #fff; }
.workbench-header, .summary-header, .chart-header, .execution-row { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.workbench-header h3, .workbench-header p, .summary-header h4, .summary-header p { margin: 0; }
.workbench-header h3 { margin-top: 4px; font-size: 17px; }
.workbench-header p, .summary-header p, .chart-header span, .loading-copy, .workbench-empty span, .ambiguity-note { color: var(--text-muted); font-size: 11px; }
.workbench-header p { margin-top: 4px; font-size: 12px; }
.workbench-eyebrow, .summary-scope { color: var(--color-primary); font-size: 9px; font-weight: 700; letter-spacing: .1em; }
.selector-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-top: 18px; }
.selector-field, .channel-field { display: flex; flex-direction: column; gap: 7px; min-width: 0; }
.selector-field > label, .channel-field > label { color: var(--text-secondary); font-size: 11px; font-weight: 600; }
.execution-row { align-items: flex-end; margin-top: 16px; }
.channel-field { width: min(360px, 100%); }
.channel-field :deep(.el-select) { width: 100%; }
.inline-alert, .result-alert, .compare-loading { margin-top: 14px; }
.compare-loading { padding: 24px; border: 1px dashed var(--border-default); border-radius: 8px; color: var(--text-muted); font-size: 12px; text-align: center; }
.compare-result { margin-top: 20px; padding-top: 18px; border-top: 1px solid var(--border-light); }
.summary-header { align-items: flex-start; }
.summary-header h4 { margin-top: 3px; font-size: 15px; }
.summary-header p { margin-top: 4px; }
.summary-badges { display: flex; gap: 8px; }
.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
.metric-card { display: flex; flex-direction: column; gap: 5px; padding: 12px 14px; border: 1px solid var(--border-light); border-radius: 8px; background: #fafbf8; }
.metric-card span { color: var(--text-muted); font-size: 10px; }
.metric-card strong { color: var(--text-primary); font-family: var(--font-mono); font-size: 21px; }
.metric-card.changed { border-top: 2px solid #B5965D; }
.metric-card.added { border-top: 2px solid #557562; }
.metric-card.removed { border-top: 2px solid #A8665E; }
.metric-card.ambiguous { border-top: 2px solid #8E7B55; }
.summary-secondary { display: flex; flex-wrap: wrap; gap: 8px 18px; margin-top: 10px; color: var(--text-muted); font-size: 10px; }
.chart-header { margin: 18px 0 8px; }
.chart-header > div { display: flex; flex-direction: column; gap: 2px; }
.chart-header strong { font-size: 13px; }
.ambiguity-note { margin: 6px 0 0; }
.workbench-empty { display: flex; flex-direction: column; align-items: center; gap: 5px; margin-top: 20px; padding: 34px 20px; border: 1px dashed var(--border-default); border-radius: 8px; background: var(--bg-subtle); }
.workbench-empty strong { font-size: 13px; }
@media (max-width: 900px) {
  .selector-grid, .metric-grid { grid-template-columns: 1fr; }
  .execution-row, .workbench-header, .summary-header { align-items: stretch; flex-direction: column; }
  .summary-badges { align-self: flex-start; }
}
</style>
