import { defineStore } from "pinia";
import { reactive, ref } from "vue";

import { api } from "../api/http";

export interface SiteSettings {
  site_name: string;
  logo_url: string | null;
  login_welcome: string;
  login_description: string;
  home_title: string;
  home_description: string;
}

const defaults: SiteSettings = {
  site_name: "Bixi Seed",
  logo_url: null,
  login_welcome: "开始构建你的应用",
  login_description: "登录轻量应用基座，管理组织权限并使用 AI 创建业务功能。",
  home_title: "工作台",
  home_description: "这里是当前组织的运行概览。",
};

export const useSiteStore = defineStore("site", () => {
  const settings = reactive<SiteSettings>({ ...defaults });
  const loaded = ref(false);
  const loading = ref(false);

  async function load() {
    if (loaded.value || loading.value) return;
    loading.value = true;
    try {
      Object.assign(settings, await api<SiteSettings>("/site-settings/"));
    } catch (error) {
      console.error("无法加载站点设置", error);
    } finally {
      loaded.value = true;
      loading.value = false;
    }
  }

  async function refresh() {
    loaded.value = false;
    await load();
  }

  async function update(formData: FormData) {
    Object.assign(settings, await api<SiteSettings>("/site-settings/", { method: "PATCH", body: formData }));
    loaded.value = true;
  }

  return { settings, loaded, loading, load, refresh, update };
});
