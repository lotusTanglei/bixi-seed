<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";

import { useSessionStore } from "../stores/session";
import { useSiteStore } from "../stores/site";

const router = useRouter();
const session = useSessionStore();
const site = useSiteStore();
const loading = ref(false);
const form = reactive({ username: "", password: "" });

onMounted(() => site.load());

async function submit() {
  if (!form.username || !form.password) {
    ElMessage.warning("请输入账号和密码");
    return;
  }
  loading.value = true;
  try {
    await session.login(form.username, form.password);
    await router.push({ name: "dashboard" });
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "登录失败");
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-panel">
      <div class="login-heading">
        <span v-if="site.settings.logo_url" class="brand-logo large">
          <img :src="site.settings.logo_url" :alt="site.settings.site_name" />
        </span>
        <span v-else class="brand-symbol large">B</span>
        <div>
          <div class="eyebrow">{{ site.settings.site_name }}</div>
          <h1>{{ site.settings.login_welcome }}</h1>
        </div>
      </div>
      <p class="login-description">{{ site.settings.login_description }}</p>
      <el-form :model="form" label-position="top" @submit.prevent="submit">
        <el-form-item label="账号">
          <el-input v-model="form.username" autocomplete="username" placeholder="请输入账号" @keyup.enter="submit" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password autocomplete="current-password" placeholder="请输入密码" @keyup.enter="submit" />
        </el-form-item>
        <el-button type="primary" size="large" :loading="loading" class="submit-button" @click="submit">登录</el-button>
      </el-form>
    </div>
  </div>
</template>
