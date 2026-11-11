<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ChatDotRound, Folder, Grid, OfficeBuilding, Setting, SwitchButton } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";

import { useSessionStore } from "./stores/session";
import { useSiteStore } from "./stores/site";

const route = useRoute();
const router = useRouter();
const session = useSessionStore();
const site = useSiteStore();
const collapsed = ref(false);

onMounted(() => {
  session.load();
  site.load();
});

async function handleOrganizationChange(id: string) {
  try {
    await session.switchOrganization(id);
    ElMessage.success("已切换组织");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "切换组织失败");
  }
}

async function handleLogout() {
  await session.logout();
  await router.push({ name: "login" });
}

</script>

<template>
  <router-view v-if="route.name === 'login'" />
  <div v-else-if="session.isAuthenticated" class="app-shell">
    <aside class="sidebar" :class="{ collapsed }">
      <div class="brand-mark">
        <span v-if="site.settings.logo_url" class="brand-logo">
          <img :src="site.settings.logo_url" :alt="site.settings.site_name" />
        </span>
        <span v-else class="brand-symbol">B</span>
        <span v-if="!collapsed">{{ site.settings.site_name }}</span>
      </div>
      <el-menu :default-active="route.path" :collapse="collapsed" router class="main-menu">
        <el-menu-item index="/">
          <el-icon class="app-icon app-icon--nav"><Grid /></el-icon>
          <template #title>工作台</template>
        </el-menu-item>
        <el-menu-item v-if="session.hasAnyPermission(['member.read', 'member.manage', 'role.manage', 'audit.read', 'organization.manage'])" index="/organizations">
          <el-icon class="app-icon app-icon--nav"><OfficeBuilding /></el-icon>
          <template #title>组织权限</template>
        </el-menu-item>
        <el-menu-item v-if="session.hasAnyPermission(['ai.use', 'ai.configure'])" index="/ai">
          <el-icon class="app-icon app-icon--nav"><ChatDotRound /></el-icon>
          <template #title>AI 助手</template>
        </el-menu-item>
        <el-menu-item v-if="session.hasPermission('feature.manage')" index="/extensions">
          <el-icon class="app-icon app-icon--nav"><Folder /></el-icon>
          <template #title>扩展草稿</template>
        </el-menu-item>
        <el-menu-item v-if="session.hasPermission('organization.manage')" index="/settings">
          <el-icon class="app-icon app-icon--nav"><Setting /></el-icon>
          <template #title>站点设置</template>
        </el-menu-item>
      </el-menu>
      <button class="collapse-button" type="button" @click="collapsed = !collapsed">
        {{ collapsed ? ">" : "收起菜单" }}
      </button>
    </aside>

    <section class="main-area">
      <header class="topbar">
        <div class="topbar-title">{{ site.settings.site_name }}</div>
        <div class="topbar-actions">
          <el-select
            v-if="session.organizations.length"
            :model-value="session.activeOrganizationId ?? undefined"
            placeholder="选择组织"
            class="organization-select"
            @change="handleOrganizationChange"
          >
            <el-option v-for="item in session.organizations" :key="item.id" :label="item.path || item.name" :value="item.id" />
          </el-select>
          <span class="user-name">{{ session.user?.display_name }}</span>
          <el-button text type="danger" @click="handleLogout">
            <el-icon><SwitchButton /></el-icon>
            退出
          </el-button>
        </div>
      </header>
      <main class="content-area">
        <router-view />
      </main>
    </section>
  </div>
  <div v-else class="loading-screen">正在加载...</div>

</template>
