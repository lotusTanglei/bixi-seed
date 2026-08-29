<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { Delete, Picture, Refresh, Upload } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";

import { useSiteStore } from "../stores/site";

const site = useSiteStore();
const saving = ref(false);
const logoFile = ref<File | null>(null);
const logoPreview = ref<string | null>(null);
const clearLogo = ref(false);
const form = reactive({
  site_name: "",
  login_welcome: "",
  login_description: "",
  home_title: "",
  home_description: "",
});

function syncForm() {
  form.site_name = site.settings.site_name;
  form.login_welcome = site.settings.login_welcome;
  form.login_description = site.settings.login_description;
  form.home_title = site.settings.home_title;
  form.home_description = site.settings.home_description;
}

onMounted(async () => {
  await site.load();
  syncForm();
  logoPreview.value = site.settings.logo_url;
});

function chooseLogo(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  if (!/\.(png|jpe?g|webp)$/i.test(file.name)) {
    ElMessage.warning("Logo 只支持 PNG、JPG 或 WebP 图片");
    input.value = "";
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    ElMessage.warning("Logo 不能超过 10 MB");
    input.value = "";
    return;
  }
  logoFile.value = file;
  clearLogo.value = false;
  logoPreview.value = URL.createObjectURL(file);
}

function removeLogo() {
  logoFile.value = null;
  logoPreview.value = null;
  clearLogo.value = true;
}

async function save() {
  if (saving.value) return;
  saving.value = true;
  const payload = new FormData();
  Object.entries(form).forEach(([key, value]) => payload.append(key, value));
  if (logoFile.value) payload.append("logo", logoFile.value);
  if (clearLogo.value) payload.append("clear_logo", "true");
  try {
    await site.update(payload);
    syncForm();
    logoPreview.value = site.settings.logo_url;
    logoFile.value = null;
    clearLogo.value = false;
    ElMessage.success("站点设置已保存");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存站点设置失败");
  } finally {
    saving.value = false;
  }
}

async function reset() {
  await site.refresh();
  syncForm();
  logoPreview.value = site.settings.logo_url;
  logoFile.value = null;
  clearLogo.value = false;
}
</script>

<template>
  <div class="page-header">
    <div>
      <div class="eyebrow">BRAND SETTINGS</div>
      <h1>站点设置</h1>
      <p>设置登录页和首页的品牌内容，业务功能不会因此增加。</p>
    </div>
    <el-button :icon="Refresh" circle title="重新加载" aria-label="重新加载" @click="reset" />
  </div>

  <section class="surface-section settings-section">
    <div class="settings-layout">
      <div class="logo-setting">
        <div class="section-heading">
          <div>
            <h2>Logo</h2>
            <p>用于登录页和左侧导航。</p>
          </div>
          <el-icon class="app-icon app-icon--accent"><Picture /></el-icon>
        </div>
        <div class="logo-preview" :class="{ 'is-empty': !logoPreview }">
          <img v-if="logoPreview" :src="logoPreview" :alt="form.site_name" />
          <span v-else class="brand-symbol large">B</span>
        </div>
        <label class="upload-button">
          <el-icon><Upload /></el-icon>
          <span>选择图片</span>
          <input type="file" accept=".png,.jpg,.jpeg,.webp" @change="chooseLogo" />
        </label>
        <el-button v-if="logoPreview" text type="danger" :icon="Delete" @click="removeLogo">移除 Logo</el-button>
      </div>

      <el-form :model="form" label-position="top" class="settings-form">
        <el-form-item label="站点名称" required>
          <el-input v-model="form.site_name" maxlength="80" show-word-limit />
        </el-form-item>
        <el-form-item label="登录页欢迎语" required>
          <el-input v-model="form.login_welcome" maxlength="160" show-word-limit />
        </el-form-item>
        <el-form-item label="登录页描述" required>
          <el-input v-model="form.login_description" type="textarea" :rows="3" maxlength="300" show-word-limit resize="none" />
        </el-form-item>
        <el-form-item label="首页标题" required>
          <el-input v-model="form.home_title" maxlength="160" show-word-limit />
        </el-form-item>
        <el-form-item label="首页描述" required>
          <el-input v-model="form.home_description" type="textarea" :rows="3" maxlength="300" show-word-limit resize="none" />
        </el-form-item>
        <div class="settings-actions">
          <el-button type="primary" :loading="saving" :disabled="!form.site_name.trim() || !form.login_welcome.trim() || !form.login_description.trim() || !form.home_title.trim() || !form.home_description.trim()" @click="save">保存设置</el-button>
        </div>
      </el-form>
    </div>
  </section>
</template>
