<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";

import { api } from "../api/http";
import { useSessionStore } from "../stores/session";
import { useSiteStore } from "../stores/site";

interface Feature {
  id: string;
  name: string;
  description: string;
  status: string;
}

const session = useSessionStore();
const site = useSiteStore();
const router = useRouter();
const features = ref<Feature[]>([]);

onMounted(async () => {
  await site.load();
  try {
    features.value = await api<Feature[]>("/features/");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "无法加载功能");
  }
});
</script>

<template>
  <div class="page-header">
    <div>
      <div class="eyebrow">OVERVIEW</div>
      <h1>{{ site.settings.home_title }}</h1>
      <p>{{ site.settings.home_description }} {{ session.activeOrganization?.name ?? "当前组织" }}</p>
    </div>
  </div>

  <div class="stat-grid">
    <section class="stat-block">
      <span class="stat-label">当前组织</span>
      <strong>{{ session.activeOrganization?.name ?? "未选择" }}</strong>
      <span class="stat-note">{{ session.activeOrganization?.role ?? "-" }}</span>
    </section>
    <section class="stat-block">
      <span class="stat-label">组织数量</span>
      <strong>{{ session.organizations.length }}</strong>
      <span class="stat-note">当前账号可访问的组织</span>
    </section>
    <section class="stat-block">
      <span class="stat-label">已发布功能</span>
      <strong>{{ features.length }}</strong>
      <span class="stat-note">由功能引擎提供</span>
    </section>
  </div>

  <section class="surface-section">
    <div class="section-heading">
      <div>
        <h2>业务功能</h2>
        <p>AI 创建并发布的业务功能会出现在这里。</p>
      </div>
    </div>
    <div v-if="features.length" class="feature-list">
      <button v-for="feature in features" :key="feature.id" type="button" class="feature-row feature-row-button" @click="router.push({ name: 'feature', params: { featureId: feature.id } })">
        <div>
          <strong>{{ feature.name }}</strong>
          <p>{{ feature.description || "暂无说明" }}</p>
        </div>
        <el-tag type="success">已发布</el-tag>
      </button>
    </div>
    <el-empty v-else description="还没有已发布的业务功能" />
  </section>
</template>
