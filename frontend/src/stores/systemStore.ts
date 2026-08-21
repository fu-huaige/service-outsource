import { defineStore } from "pinia";
import { ref } from "vue";
import { getHealthLive, getHealthReady } from "../api/health";
import type { LivenessData, ReadinessData, SystemInfoData } from "../types/api";

export type SystemStatus = "connecting" | "ready" | "offline";

const HEALTH_POLL_INTERVAL_MS = 5_000;

export const useSystemStore = defineStore("system", () => {
  const liveness = ref<LivenessData | null>(null);
  const readiness = ref<ReadinessData | null>(null);
  const systemInfo = ref<SystemInfoData | null>(null);
  const status = ref<SystemStatus>("connecting");
  const isChecking = ref(false);
  let pollingTimer: ReturnType<typeof setInterval> | null = null;

  function isReady(live: LivenessData, ready: ReadinessData): boolean {
    return (
      live.status === "ok" &&
      ready.status === "ready" &&
      ready.database === "connected" &&
      ready.queue === "connected"
    );
  }

  async function checkHealth(): Promise<SystemStatus> {
    if (isChecking.value) {
      return status.value;
    }

    isChecking.value = true;
    try {
      const live = await getHealthLive();
      const ready = await getHealthReady();
      liveness.value = live;
      readiness.value = ready;
      status.value = isReady(live, ready) ? "ready" : "offline";
    } catch {
      liveness.value = null;
      readiness.value = null;
      status.value = "offline";
    } finally {
      isChecking.value = false;
    }

    return status.value;
  }

  function startHealthPolling() {
    if (pollingTimer !== null) {
      return;
    }

    void checkHealth();
    pollingTimer = setInterval(() => {
      void checkHealth();
    }, HEALTH_POLL_INTERVAL_MS);
  }

  function stopHealthPolling() {
    if (pollingTimer !== null) {
      clearInterval(pollingTimer);
      pollingTimer = null;
    }
  }

  function setSystemInfo(info: SystemInfoData) {
    systemInfo.value = info;
  }

  return {
    liveness,
    readiness,
    systemInfo,
    status,
    isChecking,
    checkHealth,
    startHealthPolling,
    stopHealthPolling,
    setSystemInfo,
  };
});
